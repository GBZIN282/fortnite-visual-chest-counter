"""
Downloading a release zip into .update/download, on a background thread, while the app keeps counting.

The unfinished file is NAME.zip.part, with a small note saying which signed file it belongs to. It only becomes NAME.zip once
its size and SHA-256 match the signed manifest, so a finished name always means a verified file.

Resuming never trusts the server. A partial file is continued only if the server answers 206 with exactly the expected range.
A server that ignores the range answers 200, and the file then restarts from its first byte instead of being appended to. If a
resumed file fails the final check, the partial data may be what was bad, so it restarts from zero once.

Speed: BandwidthPolicy decides the limit, and it is re-read for every chunk, so the speed follows counting starting or stopping.
"Adaptive" is based on whether the app is counting. It does not measure the connection.
"""

import contextlib
import errno
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fortnite_chest_counter.update import authenticity as A
from fortnite_chest_counter.update.releases import GITHUB, UpdateError, network_errors, open_response

DOWNLOAD_FOLDER = "download"
MODES = ("adaptive", "unlimited", "custom")
ADAPTIVE_COUNTING_LIMIT = 1_000_000        # bytes per second while counting; to be adjusted from packaged testing
CHUNK = 64 * 1024                          # about 15 small steps a second at 1 MB/s, so the limit stays smooth
MAX_FAILURES = 4                           # attempts in a row without any new data
RETRY_DELAY = 1.0                          # seconds, doubling after each failure
PROGRESS_INTERVAL = 0.1
SPACE_MARGIN = 64 * 1024 * 1024
UNPACK_FACTOR = 4                          # zip + unpacked copy; the real package unpacks to 2.6 times its size
_CONTENT_RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", re.IGNORECASE)
_RETRYABLE = ("timeout", "network", "api_error", "rate_limited", "bad_range")
_DISK_FULL = (39, 112)                     # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
_NO_SPACE = "There is not enough free disk space for this update."


def never():
    return False


def cancelled():
    return UpdateError("cancelled", "The update was cancelled.")


@dataclass(frozen=True)
class BandwidthPolicy:
    mode: str = "adaptive"                 # adaptive | unlimited | custom
    custom_limit: int | None = None        # bytes per second, always applied in "custom" mode
    counting_limit: int = ADAPTIVE_COUNTING_LIMIT

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"unknown download mode {self.mode!r}")
        if self.mode == "custom" and (type(self.custom_limit) is not int or self.custom_limit <= 0):
            raise ValueError("a custom download limit must be a whole number of bytes per second above 0")

    def limit(self, counting):
        """Bytes per second allowed right now, or None for no limit."""
        if self.mode == "custom":
            return self.custom_limit
        return self.counting_limit if self.mode == "adaptive" and counting else None


@dataclass(frozen=True)
class DownloadProgress:
    received: int
    total: int
    bytes_per_second: float
    limit: int | None


@contextlib.contextmanager
def disk_errors():
    try:
        yield
    except OSError as error:
        if error.errno == errno.ENOSPC or getattr(error, "winerror", None) in _DISK_FULL:
            raise UpdateError("disk_space", _NO_SPACE) from None
        raise UpdateError("disk_error", "The update files could not be written. Please try again.") from None


def ensure_folder(path):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError:
        raise UpdateError("not_writable", "The app cannot write to its own folder, so it cannot update itself here.") from None


def require_space(folder, needed):
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return                             # unknown: a full disk is still reported when writing
    if free < needed:
        raise UpdateError("disk_space", _NO_SPACE)


class _Throttle:
    def __init__(self, policy, is_counting, cancel):
        self.policy, self.is_counting, self.cancel = policy, is_counting, cancel
        self.next_time = 0.0

    def limit(self):
        return self.policy.limit(bool(self.is_counting()))

    def pace(self, size):
        limit = self.limit()
        now = time.monotonic()
        if limit is None:
            self.next_time = now
            return
        self.next_time = max(self.next_time, now) + size / limit          # unused time is never saved up into a burst
        if self.next_time > now and self.cancel.wait(self.next_time - now):
            raise cancelled()


class _Reporter:
    def __init__(self, total, throttle, on_progress):
        self.total, self.throttle, self.on_progress = total, throttle, on_progress
        self.last_report, self.speed = 0.0, 0.0
        self.window_time, self.window_bytes = time.monotonic(), None

    def __call__(self, received, final=False):
        now = time.monotonic()
        if self.window_bytes is None:
            self.window_bytes = received
        elif now - self.window_time >= 0.5:
            self.speed = (received - self.window_bytes) / (now - self.window_time)
            self.window_time, self.window_bytes = now, received
        if self.on_progress and (final or now - self.last_report >= PROGRESS_INTERVAL):
            self.last_report = now
            self.on_progress(DownloadProgress(received, self.total, self.speed, self.throttle.limit()))


class _Partial:
    """The unfinished file and the note of which signed file it belongs to."""

    def __init__(self, final, manifest):
        self.path = final.with_name(final.name + ".part")
        self.note = final.with_name(final.name + ".part.json")
        self.total = manifest.size
        self.identity = {"sha256": manifest.sha256, "size": manifest.size}

    def size(self):
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def discard(self):
        self.path.unlink(missing_ok=True)
        self.note.unlink(missing_ok=True)

    def _note_matches(self):
        try:
            return json.loads(self.note.read_text(encoding="utf-8")) == self.identity
        except (OSError, ValueError):
            return False

    def begin(self):
        """Keep existing data only if it is noted as this exact signed file and is not too long."""
        if self.path.exists() and (self.size() > self.total or not self._note_matches()):
            self.discard()
        if not self.note.exists():
            temporary = self.note.with_name(self.note.name + ".tmp")
            temporary.write_text(json.dumps(self.identity), encoding="utf-8")
            os.replace(temporary, self.note)


def _transfer(url, partial, source, throttle, cancel, report):
    """One request. Appends to the partial file only after the server has confirmed the exact range."""
    have = partial.size()
    response = open_response(url, source, "application/octet-stream", {"Range": f"bytes={have}-"} if have else None)
    with response:
        if response.status == 206:
            found = _CONTENT_RANGE.fullmatch((response.headers.get("Content-Range") or "").strip())
            if not have or not found or int(found[1]) != have or int(found[3]) != partial.total:
                raise UpdateError("bad_range", "The server could not continue the download from where it stopped.")
            mode = "ab"
        elif response.status == 200:
            have, mode = 0, "wb"           # the server ignored the range: this is the whole file from its first byte
        else:
            raise UpdateError("api_error", f"GitHub answered with an unexpected status ({response.status}).")
        with disk_errors(), open(partial.path, mode) as out:
            while have < partial.total:
                if cancel.is_set():
                    raise cancelled()
                with network_errors():
                    chunk = response.read1(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                have += len(chunk)
                report(have)
                throttle.pace(len(chunk))
    if have < partial.total:
        raise UpdateError("network", "The connection was cut off before the download finished. Please try again.")


def download_package(update, update_dir, source=GITHUB, policy=None, is_counting=never, cancel=None, on_progress=None):
    """Download and verify the zip of a VerifiedUpdate. -> the path of the verified file. Blocks: see prepare.Preparation."""
    manifest, asset = update.manifest, update.release.package
    cancel = cancel or threading.Event()
    throttle = _Throttle(policy or BandwidthPolicy(), is_counting, cancel)
    report = _Reporter(manifest.size, throttle, on_progress)
    folder = Path(update_dir) / DOWNLOAD_FOLDER
    ensure_folder(folder)
    final = folder / manifest.zip
    partial = _Partial(final, manifest)
    with disk_errors():
        for leftover in folder.iterdir():  # only the release being downloaded is kept
            if leftover not in (final, partial.path, partial.note):
                leftover.unlink()
        if final.exists():
            try:
                A.verify_package(final, manifest)
                report(manifest.size, final=True)
                return final
            except UpdateError:
                final.unlink()
        partial.begin()
    require_space(folder, manifest.size * UNPACK_FACTOR + SPACE_MARGIN - partial.size())

    routes = [url for url in (asset.download_url, asset.api_url) if url]
    failures, attempt, resumed, restarted = 0, 0, False, False
    while True:
        if cancel.is_set():
            raise cancelled()
        with disk_errors():
            partial.begin()
        before = partial.size()
        resumed = resumed or before > 0
        try:
            if before < manifest.size:
                _transfer(routes[attempt % len(routes)], partial, source, throttle, cancel, report)
            A.verify_package(partial.path, manifest)
            break
        except UpdateError as error:
            if error.kind == "mismatch":
                partial.discard()
                if resumed and not restarted:
                    resumed, restarted = False, True
                    continue
                raise
            if error.kind == "bad_range":
                partial.discard()
            if error.kind not in _RETRYABLE:
                raise
            failures = 0 if partial.size() > before else failures + 1
            if failures >= MAX_FAILURES:
                raise
            attempt += 1
            if cancel.wait(RETRY_DELAY * 2 ** max(failures - 1, 0)):
                raise cancelled() from None
    with disk_errors():
        os.replace(partial.path, final)
        partial.note.unlink(missing_ok=True)
    report(manifest.size, final=True)
    return final
