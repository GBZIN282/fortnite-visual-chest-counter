"""
Starting an installation from the running app, after the user has confirmed it and counting has stopped.

begin_install() does every check that can refuse the update while the app is still open and nothing has changed, then writes the
"prepared" journal and starts the helper. The app must close right after it returns: the helper (install_helper.py) waits for that.
"""

import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fortnite_chest_counter import paths
from fortnite_chest_counter.update import authenticity as A
from fortnite_chest_counter.update import install_helper as H
from fortnite_chest_counter.update import staging
from fortnite_chest_counter.update.download import require_space
from fortnite_chest_counter.update.releases import UpdateError, parse_version
from fortnite_chest_counter.version import __version__

INSTALL_SPACE_MARGIN = 256 * 1024 * 1024   # renames need none; this covers the helper, the data backup, logs and the first run
_DETACHED, _NEW_GROUP, _BREAKAWAY = 0x00000008, 0x00000200, 0x01000000


@dataclass(frozen=True)
class InstallStarted:
    version: str
    helper_pid: int | None


def _is_link(path):
    return path.is_symlink() or getattr(os.path, "isjunction", lambda p: False)(path)


def _probe_writable(folder):
    probe = folder / f".write-test-{secrets.token_hex(4)}"
    moved = probe.with_name(probe.name + "-moved")
    try:
        probe.mkdir()
        (probe / "file").write_bytes(b"x")
        H.while_locked(os.rename, probe, moved)
        H.while_locked(shutil.rmtree, moved)
    except OSError as error:
        for leftover in (probe, moved):
            shutil.rmtree(leftover, ignore_errors=True)
        raise UpdateError("not_writable", "The app cannot change its own folder, so it cannot update itself here.",
                          f"testing {folder}: {type(error).__name__}: {error}") from None


def _check_folders(root, update_dir, data_paths):
    """Renames only work, and only stay atomic, on one real volume, with real folders and nothing of the user's inside runtime."""
    runtime = root / H.RUNTIME
    folders = (root, update_dir, runtime, update_dir / H.STAGED_FOLDER / H.RUNTIME)
    if any(not folder.is_dir() or _is_link(folder) for folder in folders):
        raise UpdateError("unsupported_folder", "The program folder has links in it, so the app cannot update itself here.")
    if len({os.stat(folder).st_dev for folder in folders}) != 1:
        raise UpdateError("unsupported_folder", "The program folder spans several drives, so the app cannot update itself here.")
    _probe_writable(root)
    _probe_writable(update_dir)
    for data in data_paths:
        if Path(data).resolve().is_relative_to(runtime.resolve()):
            raise UpdateError("data_in_runtime", f"Your settings keep data inside the program's runtime folder ({data}). Move it first.")
    try:
        extras = H.unexpected_runtime_files(root)
    except H.InstallProblem as problem:
        raise UpdateError(problem.reason, str(problem)) from None
    if extras:
        raise UpdateError("runtime_has_user_files", f"There is an unexpected file in the program's runtime folder: {extras[0]}. Move it first.")


def _folder_size(folder):
    return sum(p.stat().st_size for p in Path(folder).rglob("*") if p.is_file())


def build_helper(update_dir, python_folder):
    """A private copy of the official Python, and this version's helper script, outside anything that will be renamed."""
    helper = update_dir / H.HELPER_FOLDER
    staging._remove(helper)
    try:
        shutil.copytree(python_folder, helper / "python", ignore=shutil.ignore_patterns("__pycache__"))
        (helper / "lib").mkdir()
        script = helper / "lib" / "install_helper.py"
        shutil.copyfile(H.__file__, script)
        checks = [(Path(H.__file__), script)] + [(Path(python_folder) / n, helper / "python" / n) for n in ("python.exe", "pythonw.exe")]
        if any(A.file_sha256(a) != A.file_sha256(b) for a, b in checks if a.exists() or b.exists()):
            raise OSError("copy differs")
    except OSError:
        staging._remove(helper)
        raise UpdateError("helper_failed", "The update could not be started. Please try again.") from None
    return helper


def _clear_orphaned_journal(root, update_dir):
    """The launcher's last resort restores the old runtime when the helper is gone, and cannot remove the journal. With no helper, no
    retained runtime and a working one in place, that journal describes nothing, and must not block later updates."""
    helper_python = update_dir / H.HELPER_FOLDER / "python" / "pythonw.exe"
    old_runtime = update_dir / H.OLD_FOLDER / H.RUNTIME
    if (update_dir / H.JOURNAL_NAME).exists() and not helper_python.exists() and not old_runtime.exists() and (root / H.RUNTIME).is_dir():
        (update_dir / H.JOURNAL_NAME).unlink(missing_ok=True)


def _spawn_helper(helper, root, wait_pid):
    """On its own, so it outlives the app. Some launchers run apps in a job that forbids breaking away, so that is optional."""
    command = [str(helper / "python" / "pythonw.exe"), "-B", "-m", "install_helper", "install", str(root), str(wait_pid)]
    for flags in (_DETACHED | _NEW_GROUP | _BREAKAWAY, _DETACHED | _NEW_GROUP):
        try:
            return subprocess.Popen(command, cwd=helper, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    close_fds=True, creationflags=flags).pid
        except OSError:
            continue
    raise UpdateError("helper_failed", "The update could not be started. Please try again.")


def begin_install(app_dir=None, installed=__version__, public_keys=None, wait_pid=None, state_dir="state", data_paths=(), launch=None,
                  python_folder=None, app_mutex=None, spawn=True):
    """Check everything, record the transaction and start the helper. -> InstallStarted. Raises UpdateError with nothing changed."""
    root = Path(app_dir if app_dir is not None else paths.APP_DIR).resolve()
    update_dir = root / H.UPDATE_FOLDER
    _clear_orphaned_journal(root, update_dir)
    if (update_dir / H.JOURNAL_NAME).exists():
        raise UpdateError("transaction_active", "An update is already being installed.")
    guard = H.NamedMutex(H.transaction_mutex_name(root))
    busy = guard.already_existed
    guard.close()
    if busy:
        raise UpdateError("transaction_active", "An update is already being installed.")
    current = parse_version(installed)
    try:
        manifest_bytes = (update_dir / H.SIGNED_FILES[0]).read_bytes()
        signature_bytes = (update_dir / H.SIGNED_FILES[1]).read_bytes()
    except OSError:
        raise UpdateError("not_prepared", "No update has been prepared.") from None
    A.verify_signature(manifest_bytes, signature_bytes, A.TRUSTED_PUBLIC_KEYS if public_keys is None else public_keys)
    manifest = A.parse_manifest(manifest_bytes)
    if current is None or parse_version(manifest.version) <= current:
        raise UpdateError("downgrade", "This release is not newer than the installed version, so it will not be installed.")
    staged = staging.staged_package(update_dir, update_dir / H.DOWNLOAD_FOLDER / manifest.zip, manifest)
    if staged is None:
        raise UpdateError("not_prepared", "The prepared update is damaged or out of date. It needs to be prepared again.")
    _check_folders(root, update_dir, data_paths)
    python_folder = Path(python_folder if python_folder is not None else root / H.RUNTIME / "python")
    require_space(root, _folder_size(python_folder) + INSTALL_SPACE_MARGIN)
    for leftover in (H.OLD_FOLDER, H.FAILED_FOLDER, H.HEALTH_FOLDER, H.BACKUP_FOLDER, H.RESULT_NAME):      # an old result must never be reported for this update
        staging._remove(update_dir / leftover)
    helper = build_helper(update_dir, python_folder)
    H.write_json_durably(update_dir / H.JOURNAL_NAME, {
        "format": H.JOURNAL_FORMAT, "phase": H.PREPARED, "from_version": installed, "to_version": manifest.version, "zip": manifest.zip,
        "sha256": manifest.sha256, "nonce": secrets.token_hex(32), "app_mutex": app_mutex if app_mutex is not None else paths.app_mutex_name(),
        "launch": list(launch if launch is not None else H.DEFAULT_LAUNCH), "state_dir": str(state_dir), "config": "config.toml", "new_started": False})
    if not spawn:
        return InstallStarted(manifest.version, None)
    try:
        pid = _spawn_helper(helper, root, os.getpid() if wait_pid is None else wait_pid)
    except UpdateError:
        (update_dir / H.JOURNAL_NAME).unlink(missing_ok=True)
        raise
    return InstallStarted(manifest.version, pid)


def last_result(app_dir=None):
    """What the last installation did (the helper's result.json), or None."""
    import json
    try:
        data = json.loads((Path(app_dir if app_dir is not None else paths.APP_DIR) / H.UPDATE_FOLDER / H.RESULT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def acknowledge_result(app_dir=None):
    """The result has been shown to the user, so it is not shown again."""
    try:
        H.while_locked((Path(app_dir if app_dir is not None else paths.APP_DIR) / H.UPDATE_FOLDER / H.RESULT_NAME).unlink, True)
    except OSError:
        pass


def clear_orphaned_journal(app_dir=None):
    root = Path(app_dir if app_dir is not None else paths.APP_DIR).resolve()
    _clear_orphaned_journal(root, root / H.UPDATE_FOLDER)


def transaction_left_open(app_dir=None):
    """True if an update did not finish and nothing is working on it. While the helper runs, this is False."""
    root = Path(app_dir if app_dir is not None else paths.APP_DIR).resolve()
    if not (root / H.UPDATE_FOLDER / H.JOURNAL_NAME).exists():
        return False
    guard = H.NamedMutex(H.transaction_mutex_name(root))
    busy = guard.already_existed
    guard.close()
    return not busy


def cleanup_finished(app_dir=None):
    """Remove what the helper could not remove itself (its own files). Does nothing while a transaction is open or the helper runs."""
    root = Path(app_dir if app_dir is not None else paths.APP_DIR).resolve()
    update_dir = root / H.UPDATE_FOLDER
    if (update_dir / H.JOURNAL_NAME).exists() or not update_dir.is_dir():
        return False
    guard = H.NamedMutex(H.transaction_mutex_name(root))
    busy = guard.already_existed
    guard.close()
    if busy:
        return False
    try:
        staging._remove(update_dir / H.HELPER_FOLDER)
    except UpdateError:
        return False
    return True
