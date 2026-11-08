"""
Unpacking a verified release into .update/new and proving it works, while the installed app keeps running from runtime/.

    .update/new.partial    being unpacked; never trusted, removed on the next attempt
    .update/new            the unpacked program files
    .update/selftest       reports from the start-up checks
    .update/staged.json    written last: the package is ready

Only program files are unpacked, so the staged folder never holds a config.toml, saved counts, OBS text files, logs or captures.

The start-up checks run the STAGED Python. It finds its program folder from its own location, so it uses .update/new as its
program folder and cannot see the user's real files. The reports must confirm that folder, or the check fails. Everything is
compared with the zip before and after they run, so a check cannot quietly change the package.
"""

import json
import os
import shutil
import subprocess
import threading
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

from fortnite_chest_counter.update import archive, authenticity as A
from fortnite_chest_counter.update.download import SPACE_MARGIN, cancelled, disk_errors, ensure_folder, never, require_space
from fortnite_chest_counter.update.releases import UpdateError

UPDATE_FOLDER = ".update"
PARTIAL_FOLDER = "new.partial"
STAGED_FOLDER = "new"
REPORT_FOLDER = "selftest"
MARKER_NAME = "staged.json"
MARKER_FORMAT = 1
USER_OWNED = ("state", "logs", "obs_output", "captures", "config.toml")
COUNTING_DISK_RATE = 25_000_000            # bytes per second of staging disk work while counting
PACE_STEP = 1024 * 1024
MAX_WINDOWS_PATH = 259
WORKER_CHECK_TIMEOUT = 120                 # generous: a first start on a slow PC, with every new file being scanned
SELF_TEST_TIMEOUT = 180
REMOVE_TRIES = 6
REMOVE_DELAY = 0.5
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_FAILED = "The new version did not pass its start-up check, so it will not be installed."

# Runs in the staged Python. What each version needs is that version's own knowledge (paths.missing_templates).
WORKER_CHECK = """
import json
import fortnite_chest_counter.counter
from fortnite_chest_counter import paths, version
report = {"version": version.__version__, "app_dir": str(paths.APP_DIR), "packaged": paths.PACKAGED,
          "missing_templates": [str(p) for p in paths.missing_templates()], "ffmpeg": paths.ffmpeg_executable()}
try:
    from Crypto.Signature import eddsa
    from fortnite_chest_counter.update.trust import TRUSTED_PUBLIC_KEYS
    report["update_keys"] = len(TRUSTED_PUBLIC_KEYS)
except ImportError:
    report["update_keys"] = 0
with open(REPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(report, f)
"""


@dataclass(frozen=True)
class StagedPackage:
    path: Path
    version: str
    files: int
    bytes: int


class _Pacer:
    """Every step can be cancelled. While counting, staging's disk work is spread out so it does not compete with the counter."""

    def __init__(self, is_counting, cancel, on_bytes=None):
        self.is_counting, self.cancel, self.on_bytes = is_counting, cancel, on_bytes
        self.pending = 0

    def __call__(self, size):
        if self.cancel.is_set():
            raise cancelled()
        if self.on_bytes:
            self.on_bytes(size)
        if self.is_counting():
            self.pending += size
            if self.pending >= PACE_STEP:
                self.pending = 0
                if self.cancel.wait(PACE_STEP / COUNTING_DISK_RATE):
                    raise cancelled()


def _is_link(path):
    return path.is_symlink() or getattr(os.path, "isjunction", lambda p: False)(path)   # isjunction: Python 3.12+


def _remove(path):
    for attempt in range(REMOVE_TRIES):
        try:
            if path.is_dir() and not _is_link(path):
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            return
        except OSError:
            if attempt == REMOVE_TRIES - 1:
                raise UpdateError("cleanup_failed", "Old update files could not be removed. Please try again.") from None
            time.sleep(REMOVE_DELAY)


def discard_staging(update_dir):
    """Remove everything staged (never the download). Only ever touches the .update folder."""
    update_dir = Path(update_dir)
    if update_dir.name != UPDATE_FOLDER:
        raise ValueError(f"not an update folder: {update_dir}")
    for name in (MARKER_NAME, PARTIAL_FOLDER, STAGED_FOLDER, REPORT_FOLDER):
        _remove(update_dir / name)


def _corrupt(detail):
    return UpdateError("staging_corrupt", f"The prepared update is damaged ({detail}). It will be prepared again.")


def verify_tree(folder, plan, pace):
    """The folder must hold exactly the planned files, byte for byte (size and CRC-32 from the zip)."""
    expected = {f.path: f for f in plan.files}
    found = set()
    with disk_errors():
        for current, folders, names in os.walk(folder):
            base = Path(current)
            if any(_is_link(base / name) for name in folders):
                raise _corrupt("a link inside the package")
            for name in names:
                file = base / name
                relative = file.relative_to(folder).as_posix()
                item = expected.get(relative)
                if item is None or _is_link(file):
                    raise _corrupt(f"unexpected file {relative}")
                if file.stat().st_size != item.size:
                    raise _corrupt(f"wrong size for {relative}")
                crc = 0
                with open(file, "rb") as f:
                    while chunk := f.read(archive.CHUNK):
                        crc = zlib.crc32(chunk, crc)
                        pace(len(chunk))
                if crc != item.crc:
                    raise _corrupt(f"wrong content in {relative}")
                found.add(relative)
    if len(found) != len(expected):
        raise _corrupt(f"missing {min(set(expected) - found)}")


def _self_test_command(staged, report):
    return [str(staged / "runtime" / "python" / "pythonw.exe"), "-B", "-m", "fortnite_chest_counter.gui", "--self-test", str(report)]


def _worker_check_command(staged, report):
    return [str(staged / "runtime" / "python" / "python.exe"), "-B", "-c", WORKER_CHECK.replace("REPORT_PATH", repr(str(report)))]


def _run_check(command, report_path, staged, timeout, cancel):
    """Run one check at below-normal priority. -> (exit code, its report). -B: Python must not write new files into the package.
    Any earlier report is removed first, so a check that writes nothing can never be judged by an old result."""
    with disk_errors():
        report_path.unlink(missing_ok=True)
    try:
        process = subprocess.Popen(command, cwd=staged, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS)
    except OSError:
        raise UpdateError("self_test_failed", _FAILED + " (It could not be started.)") from None
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if cancel.wait(0.05):
                raise cancelled()
            if time.monotonic() > deadline:
                raise UpdateError("self_test_failed", _FAILED + " (It did not finish in time.)")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return process.returncode, _read_report(report_path)


def _read_report(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _same_folder(reported, staged):
    try:
        return os.path.samefile(reported, staged)
    except (OSError, TypeError, ValueError):
        return False


def _inside(reported, staged):
    try:
        return Path(reported).resolve().is_relative_to(staged.resolve())
    except (OSError, TypeError, ValueError):
        return False


def run_staged_checks(staged, report_dir, version, cancel, require_updater=True):
    """The package's own start-up checks, run from staging. Raises UpdateError unless both pass and describe `staged`."""
    ensure_folder(report_dir)
    report_path = report_dir / "worker.json"
    code, report = _run_check(_worker_check_command(staged, report_path), report_path, staged, WORKER_CHECK_TIMEOUT, cancel)
    if code != 0 or report.get("version") != version or report.get("packaged") is not True \
            or report.get("missing_templates") != [] or not _same_folder(report.get("app_dir"), staged) \
            or not _inside(report.get("ffmpeg"), staged):
        raise UpdateError("self_test_failed", _FAILED + " (Its program files did not load.)")
    if require_updater and not (type(report.get("update_keys")) is int and report["update_keys"] > 0):
        raise UpdateError("self_test_failed", _FAILED + " (It could not install later updates.)")
    report_path = report_dir / "window.json"
    code, report = _run_check(_self_test_command(staged, report_path), report_path, staged, SELF_TEST_TIMEOUT, cancel)
    if code != 0 or report.get("ok") is not True or report.get("version") != version or report.get("packaged") is not True \
            or not _same_folder(report.get("app_dir"), staged):
        raise UpdateError("self_test_failed", _FAILED + " (Its window did not start.)")


def _read_marker(update_dir):
    try:
        data = json.loads((Path(update_dir) / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def staged_package(update_dir, zip_path, manifest, is_counting=never, cancel=None):
    """The prepared package for this manifest if it is still intact, else None. Compares every file with the verified zip."""
    update_dir = Path(update_dir)
    marker, folder = _read_marker(update_dir), update_dir / STAGED_FOLDER
    if not marker or marker.get("format") != MARKER_FORMAT or marker.get("sha256") != manifest.sha256 or not folder.is_dir():
        return None
    cancel = cancel or threading.Event()
    try:
        A.verify_package(zip_path, manifest)
        plan = archive.inspect(zip_path, manifest)
        verify_tree(folder, plan, _Pacer(is_counting, cancel))
    except UpdateError as error:
        if error.kind == "cancelled":
            raise
        return None
    return StagedPackage(folder, manifest.version, len(plan.files), plan.total_size)


def _write_marker(update_dir, manifest, plan):
    temporary = update_dir / (MARKER_NAME + ".tmp")
    temporary.write_text(json.dumps({"format": MARKER_FORMAT, "version": manifest.version, "zip": manifest.zip, "sha256": manifest.sha256,
                                     "files": len(plan.files), "bytes": plan.total_size}), encoding="utf-8")
    os.replace(temporary, update_dir / MARKER_NAME)


def stage_package(zip_path, update, update_dir, is_counting=never, cancel=None, on_stage=None, on_bytes=None, checks=run_staged_checks):
    """Verify, inspect, unpack and test one downloaded release. -> StagedPackage. The installed app is never touched."""
    manifest = update.manifest
    update_dir = Path(update_dir)
    cancel = cancel or threading.Event()
    stage = on_stage or (lambda name: None)
    stage("verifying")
    A.verify_package(zip_path, manifest)   # nothing in the zip is read before its signed hash has matched
    plan = archive.inspect(zip_path, manifest)
    ready = staged_package(update_dir, zip_path, manifest, is_counting, cancel)
    if ready is not None:
        return ready
    try:
        discard_staging(update_dir)
        partial, staged, reports = update_dir / PARTIAL_FOLDER, update_dir / STAGED_FOLDER, update_dir / REPORT_FOLDER
        require_space(update_dir, plan.total_size + SPACE_MARGIN)
        if len(str(partial)) + 1 + plan.longest_path > MAX_WINDOWS_PATH:
            raise UpdateError("path_too_long", "The program folder path is too long. Move the folder somewhere shorter, then try again.")
        ensure_folder(partial)
        stage("extracting")
        pace = _Pacer(is_counting, cancel, on_bytes)
        with disk_errors():
            archive.extract(zip_path, plan, partial, pace)
        stage("validating")
        verify = _Pacer(is_counting, cancel)
        verify_tree(partial, plan, verify)
        with disk_errors():
            os.replace(partial, staged)
        stage("checking")
        checks(staged, reports, manifest.version, cancel)
        for name in USER_OWNED:            # whatever the start-up checks created there; none of it is program files
            _remove(staged / name)
        verify_tree(staged, plan, verify)
        with disk_errors():
            _write_marker(update_dir, manifest, plan)
    except BaseException:
        try:
            discard_staging(update_dir)
        except UpdateError:
            pass                           # the next attempt starts by removing it again
        raise
    return StagedPackage(staged, manifest.version, len(plan.files), plan.total_size)
