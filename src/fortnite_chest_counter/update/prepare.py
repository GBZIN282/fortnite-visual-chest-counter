"""
Getting one verified update ready to install: download, verify, unpack, test. It only starts when the user asks for it.

Everything runs on its own thread and stays inside .update, so the app window, the counting worker and the installed program
files are not involved. The window polls status() and result() from a timer, the same way it reads the counting worker.

What is kept after a problem:
    cancelled or network failure    the partial download, so it can resume
    download fails its checksum     nothing (the download layer deletes it)
    unsafe or damaged package       nothing: it can never become valid
    start-up check or disk failure  the verified zip, so a retry need not download it again
"""

import ctypes
import threading
from ctypes import wintypes
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from fortnite_chest_counter import paths
from fortnite_chest_counter.update import download, staging
from fortnite_chest_counter.update.download import BandwidthPolicy, never
from fortnite_chest_counter.update.releases import GITHUB, UpdateError

_REJECTED_PACKAGES = ("archive_unsafe", "archive_layout", "archive_too_large", "archive_invalid")


@dataclass(frozen=True)
class PreparationStatus:
    stage: str = "waiting"                 # waiting | downloading | verifying | extracting | validating | checking | finished
    received: int = 0
    total: int = 0
    bytes_per_second: float = 0.0
    limit: int | None = None


@dataclass(frozen=True)
class PreparationResult:
    status: str                            # ready | failed | cancelled
    message: str
    kind: str | None = None
    staged: staging.StagedPackage | None = None
    detail: str = ""                       # the technical cause, also written to .update/prepare.log


def _log_failure(folder, error):
    try:
        with open(folder / "prepare.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {error.kind}: {error} [{error.detail}]\n")
    except OSError:
        pass


def update_folder(app_dir=None):
    return Path(app_dir if app_dir is not None else paths.APP_DIR) / staging.UPDATE_FOLDER


def prepare_update(update, app_dir=None, source=GITHUB, policy=None, is_counting=never, cancel=None, on_status=None,
                   checks=staging.run_staged_checks):
    """Download and stage one VerifiedUpdate. -> PreparationResult. Blocks: the app uses Preparation."""
    cancel = cancel or threading.Event()
    report = on_status or (lambda **changes: None)
    folder = update_folder(app_dir)
    zip_path = None
    try:
        download.ensure_folder(folder)
        report(stage="downloading")
        zip_path = download.download_package(update, folder, source, policy, is_counting, cancel,
                                             lambda p: report(received=p.received, total=p.total, bytes_per_second=p.bytes_per_second,
                                                              limit=p.limit))
        staged = staging.stage_package(zip_path, update, folder, is_counting, cancel, lambda stage: report(stage=stage), None, checks)
    except UpdateError as error:
        if error.kind == "cancelled":
            return PreparationResult("cancelled", str(error), error.kind)
        _log_failure(folder, error)
        if error.kind in _REJECTED_PACKAGES and zip_path is not None:
            zip_path.unlink(missing_ok=True)
        return PreparationResult("failed", str(error), error.kind, detail=error.detail)
    return PreparationResult("ready", f"Version v{update.manifest.version} is ready to install.", staged=staged)


def _lower_thread_priority():
    """Below normal, not "background": the thread sometimes holds Python's lock, and the window must not end up waiting for a
    thread Windows hardly runs."""
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentThread.restype = wintypes.HANDLE
        kernel32.SetThreadPriority.argtypes = (wintypes.HANDLE, ctypes.c_int)
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), -1)        # THREAD_PRIORITY_BELOW_NORMAL
    except (AttributeError, OSError):
        pass


class Preparation:
    """prepare_update on its own thread."""

    def __init__(self, update, **options):
        self._update, self._options = update, options
        self._cancel = threading.Event()
        self._status = PreparationStatus()
        self._result = None

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="update-prepare").start()
        return self

    def cancel(self):
        self._cancel.set()

    def _report(self, **changes):
        self._status = replace(self._status, **changes)

    def _run(self):
        _lower_thread_priority()
        try:
            self._result = prepare_update(self._update, cancel=self._cancel, on_status=self._report, **self._options)
        except Exception as error:         # a bug here must never take the app down or look like a ready update
            self._result = PreparationResult("failed", f"The update could not be prepared ({type(error).__name__}).", "unexpected")
        self._report(stage="finished")

    def status(self):
        return self._status

    def result(self):
        """The PreparationResult, or None while it is still running."""
        return self._result
