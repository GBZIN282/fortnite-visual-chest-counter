"""
The install helper: swaps the runtime folder, proves the new version starts, and undoes everything if it does not.

It runs from a temporary copy of the official Python in .update/helper, so nothing it needs is inside the folder it replaces.
This file is the INSTALLED version's own code, copied there before the swap, and never comes from the downloaded package: a
broken release cannot affect the code that has to roll it back. For the same reason, STANDARD LIBRARY ONLY, and no imports from
this program.

The journal (.update/transaction.json) is written durably and records how far an installation has got:

    prepared         nothing has moved
    old_retained     runtime/ has moved to .update/old/runtime
    new_installed    .update/new/runtime has moved to runtime/
    awaiting_health  the new version is starting and has not yet proved itself
    committing       it proved itself: finish and never go back
    committed        finished; only cleaning up
    rolling_back     undoing an installation that did not prove itself
    rolled_back      undone; only cleaning up

A journal and a folder rename cannot happen as one step, so recovery looks at which folders exist instead of trusting the phase
alone. Only an explicit health report from the new version can move an installation forward. Everything else, including an
unreadable journal, restores the previous version.

Recovery runs from the launcher, using the helper's own Python, so it works even if the new runtime cannot start at all.
"""

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile
import zlib
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

UPDATE_FOLDER = ".update"
HELPER_FOLDER = "helper"
STAGED_FOLDER = "new"
OLD_FOLDER = "old"
FAILED_FOLDER = "failed"
HEALTH_FOLDER = "health"
BACKUP_FOLDER = "user-backup"
DOWNLOAD_FOLDER = "download"
MARKER_NAME = "staged.json"
SIGNED_FILES = ("update-manifest.json", "update-manifest.json.sig")
JOURNAL_NAME = "transaction.json"
RESULT_NAME = "result.json"
LOG_NAME = "install.log"
RUNTIME = "runtime"
PACKAGE_FILES = "package-files.json"       # in runtime/: every file the release put there
ROOT_FILES = ("Fortnite Visual Chest Counter.exe", "README.html", "LICENSE.txt", "LICENSE-NOTICE.txt", "config.example.toml")
DEFAULT_LAUNCH = ("runtime/python/pythonw.exe", "-m", "fortnite_chest_counter.gui")
JOURNAL_FORMAT = 1
HEALTH_FORMAT = 1

PREPARED, OLD_RETAINED, NEW_INSTALLED, AWAITING_HEALTH = "prepared", "old_retained", "new_installed", "awaiting_health"
COMMITTING, COMMITTED, ROLLING_BACK, ROLLED_BACK = "committing", "committed", "rolling_back", "rolled_back"

EXIT_OK, EXIT_USAGE, EXIT_BUSY, EXIT_STUCK = 0, 2, 3, 4    # the launcher knows 3 and 4

PROCESS_WAIT = 60.0                        # seconds for the old app and its children to exit
PROCESS_POLL = 0.1
HEALTH_DEADLINE = 180.0                    # a first start on a slow PC, with every new file being scanned
HEALTH_POLL = 0.1
RENAME_TRIES = 30                          # antivirus and the search indexer hold files briefly
RENAME_DELAY = 1.0
REPLACE_TRIES = 5
LOCK_TRIES = 100                           # small files: antivirus and the search indexer hold them for moments
LOCK_DELAY = 0.05
KILL_WAIT = 10.0
MIN_FREE_SPACE = 128 * 1024 * 1024         # the swap itself only renames; this is for logs, reports and the first run
KEEP_BACKUPS = 3


def checkpoint(name):
    """Does nothing. Tests replace it to stop this process dead at each step."""


class InstallProblem(Exception):
    def __init__(self, reason, detail):
        super().__init__(detail)
        self.reason = reason


# ---- Windows

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
_SYNCHRONIZE, _TERMINATE, _QUERY_LIMITED = 0x00100000, 0x0001, 0x1000
_ALREADY_EXISTS = 183


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


_kernel32.Process32FirstW.argtypes = _kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))


class NamedMutex:
    """Held for as long as this process lives; Windows releases it however the process ends."""

    def __init__(self, name):
        self.handle = _kernel32.CreateMutexW(None, False, name)
        self.already_existed = bool(self.handle) and ctypes.get_last_error() == _ALREADY_EXISTS

    def close(self):
        if self.handle:
            _kernel32.CloseHandle(self.handle)
            self.handle = None


def transaction_mutex_name(root):
    return "Local\\FortniteVisualChestCounter-Update-" + hashlib.sha1(str(root).lower().encode()).hexdigest()[:16]


def running_programs():
    """[(pid, program path)] of every process this user can inspect."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(2, 0)       # TH32CS_SNAPPROCESS
    entry = _ProcessEntry(dwSize=ctypes.sizeof(_ProcessEntry))
    found = []
    more = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
    while more:
        handle = _kernel32.OpenProcess(_QUERY_LIMITED, False, entry.th32ProcessID)
        if handle:
            buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                found.append((entry.th32ProcessID, buffer.value))
            _kernel32.CloseHandle(handle)
        more = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    _kernel32.CloseHandle(snapshot)
    return found


def processes_under(folders):
    """[(pid, program path)] of every process whose program file is inside one of `folders`. The folder cannot be renamed safely
    while these run, and a failed rename would not reveal them: Windows allows renaming a folder a running program came from."""
    prefixes = tuple(os.path.normcase(os.path.abspath(f)) + os.sep for f in folders)
    return [(pid, path) for pid, path in running_programs() if os.path.normcase(path).startswith(prefixes) and pid != os.getpid()]


def wait_for_process_exit(pid, seconds):
    handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        return True                        # already gone
    result = _kernel32.WaitForSingleObject(handle, int(seconds * 1000))
    _kernel32.CloseHandle(handle)
    return result == 0


def _terminate(pid):
    handle = _kernel32.OpenProcess(_TERMINATE, False, pid)
    if handle:
        _kernel32.TerminateProcess(handle, 1)
        _kernel32.CloseHandle(handle)


def _free_space(path):
    return shutil.disk_usage(path).free


# ---- small durable files

def while_locked(action, *args):
    """Run a file operation, waiting out the moments when another program has the file open: on Windows that refuses a rename or
    replace with a permission error. Antivirus and the search indexer do this to freshly written files. Bounded, and only for that
    error: anything else is a real failure and is raised at once."""
    for attempt in range(LOCK_TRIES):
        try:
            return action(*args)
        except PermissionError:
            if attempt == LOCK_TRIES - 1:
                raise
            time.sleep(LOCK_DELAY)


def read_text_when_free(path):
    return while_locked(Path(path).read_text, "utf-8")


def write_json_durably(path, data):
    """Complete on disk before it replaces the old file, so a power cut leaves the old record or the new one, never half."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")

    def write_temporary():
        with open(temporary, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

    while_locked(write_temporary)
    while_locked(os.replace, temporary, path)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class Transaction:
    def __init__(self, root, data):
        self.root = Path(root)
        self.data = data
        self.update_dir = self.root / UPDATE_FOLDER
        self.journal = self.update_dir / JOURNAL_NAME
        self.runtime = self.root / RUNTIME
        self.old_runtime = self.update_dir / OLD_FOLDER / RUNTIME
        self.staged = self.update_dir / STAGED_FOLDER
        self.staged_runtime = self.staged / RUNTIME
        self.health_report = self.update_dir / HEALTH_FOLDER / "report.json"
        self.backup = self.update_dir / BACKUP_FOLDER

    @property
    def phase(self):
        return self.data.get("phase")

    def get(self, name, default=None):
        return self.data.get(name, default)

    def save(self, **changes):
        updated = {**self.data, **changes}
        write_json_durably(self.journal, updated)
        self.data = updated                # only once it is on disk, so the journal and this object cannot disagree

    def log(self, text):
        try:
            with open(self.update_dir / LOG_NAME, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
        except OSError:
            pass

    def resolve(self, text):
        path = Path(text)
        return path if path.is_absolute() else self.root / path

    def stored(self, path):
        try:
            return Path(path).relative_to(self.root).as_posix()
        except ValueError:
            return str(path)


def load_transaction(root):
    """The transaction in `root`, or None if there is none. A damaged journal still counts: its phase is "unreadable". A journal
    that stays locked raises PermissionError instead, because being locked says nothing about what is in it."""
    journal = Path(root) / UPDATE_FOLDER / JOURNAL_NAME
    try:
        text = read_text_when_free(journal)
    except FileNotFoundError:
        return None
    except PermissionError:
        raise
    except (OSError, ValueError):
        text = ""
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("format") != JOURNAL_FORMAT or not isinstance(data.get("phase"), str):
            raise ValueError
    except (ValueError, RecursionError):
        data = {"format": JOURNAL_FORMAT, "phase": "unreadable", "new_started": True}
    return Transaction(root, data)


# ---- checks before anything moves

def unexpected_runtime_files(root):
    """Files in runtime/ that the installed package did not put there. They would be lost with the old runtime, so they stop the
    installation instead. Python's bytecode caches are not user files."""
    runtime = Path(root) / RUNTIME
    try:
        known = set(json.loads(read_text_when_free(runtime / PACKAGE_FILES))["files"])
    except (OSError, ValueError, KeyError, TypeError):
        raise InstallProblem("runtime_unrecognised", "The list of installed program files is missing or damaged.") from None
    known.add(PACKAGE_FILES)
    extras = []
    for folder, _, names in os.walk(runtime):
        for name in names:
            relative = (Path(folder) / name).relative_to(runtime).as_posix()
            if relative not in known and "__pycache__" not in relative.split("/"):
                extras.append(relative)
    return sorted(extras)


def _verify_staged(txn):
    """The staged files must still be byte for byte what the verified zip holds, and the zip still the one that was signed."""
    zip_path = txn.update_dir / DOWNLOAD_FOLDER / txn.data["zip"]
    damaged = InstallProblem("staged_damaged", "The prepared update is damaged.")
    try:
        if _sha256(zip_path) != txn.data["sha256"]:
            raise damaged
        prefix = f"Fortnite-Visual-Chest-Counter-v{txn.data['to_version']}/"
        with zipfile.ZipFile(zip_path) as archive:
            expected = {}
            for info in archive.infolist():
                relative = info.filename[len(prefix):]
                if info.filename.startswith(prefix) and (relative in ROOT_FILES or relative.startswith(RUNTIME + "/")):
                    expected[relative] = (info.file_size, info.CRC)
        found = 0
        for folder, _, names in os.walk(txn.staged):
            for name in names:
                file = Path(folder) / name
                wanted = expected.get(file.relative_to(txn.staged).as_posix())
                if wanted is None or file.stat().st_size != wanted[0]:
                    raise damaged
                crc = 0
                with open(file, "rb") as f:
                    while chunk := f.read(1024 * 1024):
                        crc = zlib.crc32(chunk, crc)
                if crc != wanted[1]:
                    raise damaged
                found += 1
        if found != len(expected):
            raise damaged
    except (OSError, zipfile.BadZipFile, KeyError):
        raise damaged from None


def _state_dir(txn):
    return txn.resolve(txn.get("state_dir", "state"))


def _user_data_files(txn):
    """[(path, kind)] of the small files that hold counts, profiles and settings. Captures and logs are never copied."""
    base = _state_dir(txn)
    files = [(f, "registry" if f.name == "profiles.json" else "counter") for f in sorted(base.glob("*.json")) if f.name != "window.json"]
    files += [(f, "counter") for f in sorted((base / "profiles").glob("*.json"))]
    config = txn.resolve(txn.get("config", "config.toml"))
    if config.is_file():
        files.append((config, "config"))
    return files


def _snapshot_user_data(txn):
    """Copies only: the live files are not touched. Written complete, then named in index.json, so a partial copy is never used."""
    shutil.rmtree(txn.backup, ignore_errors=True)
    txn.backup.mkdir(parents=True)
    index = []
    try:
        for number, (path, kind) in enumerate(_user_data_files(txn)):
            stored = f"{number:06d}_{path.name}"
            shutil.copyfile(path, txn.backup / stored)
            digest = _sha256(txn.backup / stored)
            if digest != _sha256(path):
                raise OSError("the copy differs")
            index.append({"path": txn.stored(path), "kind": kind, "sha256": digest, "stored": stored})
        write_json_durably(txn.backup / "index.json", index)
    except OSError as error:
        raise InstallProblem("backup_failed", f"Your saved data could not be backed up ({error}).") from None


def _check_can_swap(txn, wait_pid):
    if wait_pid and not wait_for_process_exit(wait_pid, PROCESS_WAIT):
        raise InstallProblem("old_app_running", "The app did not close, so the update was not installed.")
    checkpoint("old_app_gone")
    deadline = time.monotonic() + PROCESS_WAIT
    folders = [txn.runtime, txn.staged_runtime]
    while (running := processes_under(folders)) and time.monotonic() < deadline:
        time.sleep(PROCESS_POLL)
    if running:
        raise InstallProblem("runtime_in_use", f"{Path(running[0][1]).name} is still running from the program folder.")
    checkpoint("processes_gone")
    _verify_staged(txn)
    checkpoint("staged_verified")
    extras = unexpected_runtime_files(txn.root)
    if extras:
        raise InstallProblem("runtime_has_user_files", f"Unexpected file in the program's runtime folder: {extras[0]}")
    size = sum(path.stat().st_size for path, _ in _user_data_files(txn))
    if _free_space(txn.root) < size + MIN_FREE_SPACE:
        raise InstallProblem("disk_space", "There is not enough free disk space to install this update safely.")
    _snapshot_user_data(txn)
    checkpoint("snapshot_done")


def _rename(source, target):
    for attempt in range(RENAME_TRIES):
        try:
            os.rename(source, target)
            return
        except OSError:
            if attempt == RENAME_TRIES - 1:
                raise
            time.sleep(RENAME_DELAY)


# ---- the new version proves itself

def health_report_is_valid(txn, pid=None):
    """Only a report written for this exact installation counts. The nonce is new for every attempt, so an old report or one written
    without it cannot pass. A process merely existing proves nothing."""
    try:
        report = json.loads(read_text_when_free(txn.health_report))
        return (isinstance(report, dict) and report.get("format") == HEALTH_FORMAT and report.get("stage") == "ready"
                and report.get("nonce") == txn.data["nonce"] and report.get("version") == txn.data["to_version"]
                and (pid is None or report.get("pid") == pid) and os.path.samefile(report.get("app_dir"), txn.root))
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return False


def _start_app(txn, health):
    command = [str(part) for part in txn.get("launch", DEFAULT_LAUNCH)]
    if not Path(command[0]).is_absolute():
        command[0] = str(txn.root / command[0])
    if health:
        command += ["--update-health", str(txn.health_report), txn.data["nonce"]]
    return subprocess.Popen(command, cwd=txn.root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000)        # CREATE_NO_WINDOW


def _wait_for_health(txn, process):
    """-> None if the new version proved itself, else why it did not."""
    deadline = time.monotonic() + HEALTH_DEADLINE
    while time.monotonic() < deadline:
        if health_report_is_valid(txn, process.pid):
            return None if process.poll() is None else "It closed straight after starting."
        code = process.poll()
        if code is not None:
            return f"It closed before it finished starting (exit code {code})."
        time.sleep(HEALTH_POLL)
    return "It did not finish starting in time."


# ---- finishing

def _write_result(txn, outcome, reason, detail="", restored=(), kept_newer=()):
    write_json_durably(txn.update_dir / RESULT_NAME, {"outcome": outcome, "reason": reason, "detail": detail, "from": txn.get("from_version"),
                                                      "to": txn.get("to_version"), "restored": list(restored), "kept_newer": list(kept_newer),
                                                      "finished_at": datetime.now().isoformat(timespec="seconds")})
    txn.log(f"result: {outcome} ({reason}) {detail}")


def _copy_log_to_logs_folder(txn, outcome):
    try:
        folder = txn.root / "logs"
        folder.mkdir(exist_ok=True)
        shutil.copyfile(txn.update_dir / LOG_NAME, folder / f"update_{txn.get('to_version', 'unknown')}_{outcome}_{_stamp()}.log")
    except OSError:
        pass


def _remove_quietly(path):
    """Leftovers are only wasted space; the next installation or start-up removes them."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _clean_and_close(txn, keep_staged, keep_download):
    names = [OLD_FOLDER, FAILED_FOLDER, HEALTH_FOLDER, BACKUP_FOLDER]
    if not keep_staged:
        names += [STAGED_FOLDER, MARKER_NAME, *SIGNED_FILES]
    if not keep_download:
        names.append(DOWNLOAD_FOLDER)
    for name in names:
        _remove_quietly(txn.update_dir / name)
    checkpoint("cleaned")
    while_locked(txn.journal.unlink, True)


def _keep_user_backup(txn):
    """The pre-update copy of the user's data stays with their data. Only this updater's own older copies are ever removed."""
    if not txn.backup.is_dir():
        return
    backups = _state_dir(txn) / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"before-v{txn.get('to_version', 'unknown')}-{txn.get('commit_stamp', _stamp())}"
    if target.exists():
        shutil.rmtree(txn.backup, ignore_errors=True)
    else:
        shutil.move(str(txn.backup), str(target))
    for old in sorted(backups.glob("before-v*"), key=lambda p: p.stat().st_mtime, reverse=True)[KEEP_BACKUPS:]:
        _remove_quietly(old)


def _replace_root_file(txn, source, target):
    """Atomic, so the file is always old or new, never missing. It may be in use (the launcher runs during recovery): then the old
    one stays. The launcher, guide and licences do not depend on the version of the runtime."""
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(source, target)
            return
        except OSError as error:
            if attempt == REPLACE_TRIES - 1:
                txn.log(f"could not replace {target.name}: {error}")
                return
            time.sleep(RENAME_DELAY)


def commit(txn):
    if txn.phase != COMMITTING:
        txn.save(phase=COMMITTING, commit_stamp=_stamp())
    checkpoint("commit_started")
    for name in ROOT_FILES:
        if (txn.staged / name).exists():
            _replace_root_file(txn, txn.staged / name, txn.root / name)
    checkpoint("commit_root_files")
    _keep_user_backup(txn)
    checkpoint("commit_backup_kept")
    _write_result(txn, "committed", "healthy")
    txn.save(phase=COMMITTED)
    checkpoint("committed")
    _copy_log_to_logs_folder(txn, "committed")
    _clean_and_close(txn, keep_staged=False, keep_download=False)


def abort(txn, reason, detail):
    """Nothing was moved: the installed version is untouched, and the prepared package can be tried again."""
    _write_result(txn, "aborted", reason, detail)
    _copy_log_to_logs_folder(txn, "aborted")
    _clean_and_close(txn, keep_staged=True, keep_download=True)


def _readable_by_this_version(kind, path):
    """Can the version being rolled back TO read this file? This file is that version's own code, so it knows. A release that changes
    one of these formats must update this function to describe what THAT release can read."""
    try:
        if kind == "config":
            tomllib.loads(path.read_text(encoding="utf-8-sig"))
            return True
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False
        if kind == "registry":
            return isinstance(data.get("profiles"), list)
        return all(type(data.get(key)) is int and data[key] >= 0 for key in ("certain", "approximate"))
    except (OSError, ValueError, RecursionError):
        return False


def _reconcile_user_data(txn):
    """After a new version ran and was rolled back. A file it changed stays if the old version can read it, because those may be the
    user's newer numbers. A file the old version cannot read goes back to the pre-update copy, and the newer one is kept beside the
    user's data. Both are recorded, so nothing is restored silently. -> (restored, kept_newer)."""
    try:
        index = json.loads(read_text_when_free(txn.backup / "index.json"))
    except (OSError, ValueError):
        return [], []
    restored, kept_newer = [], []
    aside = _state_dir(txn) / "backups" / f"from-failed-v{txn.get('to_version', 'unknown')}-{txn.get('failed_stamp', 'update')}"
    for item in index:
        live = txn.resolve(item["path"])
        try:
            current = _sha256(live)
        except OSError:
            current = None
        if current == item["sha256"]:
            continue
        if current is not None and _readable_by_this_version(item["kind"], live):
            kept_newer.append(item["path"])
            continue
        if current is not None:
            aside.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(live, aside / item["stored"])
        live.parent.mkdir(parents=True, exist_ok=True)
        temporary = live.with_name(live.name + ".restoring")
        shutil.copyfile(txn.backup / item["stored"], temporary)
        while_locked(os.replace, temporary, live)
        restored.append(item["path"])
    return restored, kept_newer


def _stop_new_version(txn):
    """Only the new version can be running from runtime/ at this point: the old one has been moved away."""
    for pid, _ in processes_under([txn.runtime]):
        _terminate(pid)
    deadline = time.monotonic() + KILL_WAIT
    while processes_under([txn.runtime]) and time.monotonic() < deadline:
        time.sleep(PROCESS_POLL)


def rollback(txn, reason, detail=""):
    """Restore the previous runtime. Safe to run again from any point: it looks at which folders exist."""
    if txn.phase != ROLLING_BACK:
        txn.save(phase=ROLLING_BACK, rollback_reason=reason, rollback_detail=detail, failed_stamp=_stamp())
    checkpoint("rollback_started")
    if txn.get("new_started"):
        _stop_new_version(txn)
    if txn.old_runtime.exists():
        if txn.runtime.exists():
            failed = txn.update_dir / FAILED_FOLDER
            failed.mkdir(parents=True, exist_ok=True)
            _remove_quietly(failed / RUNTIME)
            _rename(txn.runtime, failed / RUNTIME)
            checkpoint("rollback_new_moved_aside")
        _rename(txn.old_runtime, txn.runtime)
        checkpoint("rollback_old_restored")
    if not txn.runtime.exists():
        raise InstallProblem("runtime_missing", "The program files are missing.")
    restored, kept_newer = _reconcile_user_data(txn) if txn.get("new_started") else ([], [])
    checkpoint("rollback_data_reconciled")
    _write_result(txn, "rolled_back", txn.get("rollback_reason", reason), txn.get("rollback_detail", detail), restored, kept_newer)
    txn.save(phase=ROLLED_BACK)
    checkpoint("rolled_back")
    _copy_log_to_logs_folder(txn, "rolled_back")
    _clean_and_close(txn, keep_staged=False, keep_download=txn.get("rollback_reason") != "health_failed")


# ---- the two jobs

def _proved_itself(txn):
    """Past this point the new version is good, and a later problem such as a locked file must never undo it."""
    return txn.phase in (COMMITTING, COMMITTED) or (txn.phase == AWAITING_HEALTH and health_report_is_valid(txn, txn.get("launched_pid")))


def _install_steps(txn, app_mutex):
    """Everything after the old runtime has started to move. -> True if the old app should be started again."""
    txn.save(phase=OLD_RETAINED)
    checkpoint("old_retained")
    try:
        _rename(txn.staged_runtime, txn.runtime)
    except OSError as error:
        rollback(txn, "swap_failed", str(error))
        return True
    txn.save(phase=NEW_INSTALLED)
    checkpoint("new_installed")
    txn.health_report.parent.mkdir(parents=True, exist_ok=True)
    while_locked(txn.health_report.unlink, True)
    txn.save(phase=AWAITING_HEALTH, new_started=True)
    checkpoint("awaiting_health")
    app_mutex.close()                      # the new version takes it when it opens
    try:
        process = _start_app(txn, health=True)
    except OSError as error:
        rollback(txn, "health_failed", f"It could not be started ({error}).")
        return True
    txn.save(launched_pid=process.pid)
    checkpoint("launched")
    problem = _wait_for_health(txn, process)
    if problem:
        txn.log(f"health check failed: {problem}")
        if process.poll() is None:
            process.kill()
        rollback(txn, "health_failed", problem)
        return True
    checkpoint("health_reported")
    commit(txn)
    return False


def install(root, wait_pid):
    root = Path(root).resolve()
    try:
        txn = load_transaction(root)
    except PermissionError:
        return EXIT_STUCK
    if txn is None or txn.phase != PREPARED:
        return EXIT_STUCK
    guard = NamedMutex(transaction_mutex_name(root))
    if guard.already_existed:
        return EXIT_BUSY
    app_mutex = NamedMutex(txn.get("app_mutex")) if txn.get("app_mutex") else NamedMutex(None)
    txn.log(f"installing {txn.get('from_version')} -> {txn.get('to_version')}")
    restart_old = True
    try:
        checkpoint("started")
        try:
            _check_can_swap(txn, wait_pid)
            txn.old_runtime.parent.mkdir(parents=True, exist_ok=True)
            try:
                _rename(txn.runtime, txn.old_runtime)
            except OSError as error:
                raise InstallProblem("runtime_locked", f"A file in the program folder is in use ({error}).") from None
        except InstallProblem as problem:
            txn.log(f"not installed: {problem.reason}: {problem}")
            abort(txn, problem.reason, str(problem))
            restart_old = problem.reason != "old_app_running"
        else:
            restart_old = _install_steps(txn, app_mutex)
    except Exception as error:             # anything unexpected once files may have moved: restore, or leave it to the next launch
        txn.log(f"unexpected problem: {type(error).__name__}: {error}")
        if _proved_itself(txn) or txn.phase == ROLLED_BACK:
            txn.log("the outcome is already decided: the next launch finishes the remaining steps")
            return EXIT_STUCK
        try:
            if txn.phase == PREPARED and not txn.old_runtime.exists():
                abort(txn, "unexpected", f"{type(error).__name__}: {error}")
            else:
                rollback(txn, "unexpected", f"{type(error).__name__}: {error}")
        except Exception as second:
            txn.log(f"rollback could not finish: {type(second).__name__}: {second}")
            return EXIT_STUCK
    app_mutex.close()
    if restart_old:
        try:
            _start_app(txn, health=False)
        except OSError as error:
            txn.log(f"could not restart the app: {error}")
    return EXIT_OK


def recover(root):
    """Finish whatever an interrupted installation left, using only the journal and which folders exist."""
    root = Path(root).resolve()
    if not (root / UPDATE_FOLDER / JOURNAL_NAME).exists():
        return EXIT_OK
    guard = NamedMutex(transaction_mutex_name(root))
    if guard.already_existed:
        return EXIT_BUSY                   # an installation is running right now
    try:
        txn = load_transaction(root)
    except PermissionError:
        return EXIT_STUCK                  # still locked after waiting: leave everything for the next launch
    if txn is None:
        return EXIT_OK
    try:
        checkpoint("recover_started")
        txn.log(f"recovering from phase {txn.phase}")
        if txn.phase == COMMITTED:
            _clean_and_close(txn, keep_staged=False, keep_download=False)
        elif _proved_itself(txn):
            commit(txn)
        elif txn.phase == ROLLED_BACK:
            _clean_and_close(txn, keep_staged=False, keep_download=txn.get("rollback_reason") != "health_failed")
        elif txn.phase in (PREPARED, "unreadable") and not txn.old_runtime.exists():
            abort(txn, "interrupted", "The installation stopped before anything was changed.")
        else:
            rollback(txn, "interrupted", "The installation was interrupted.")
    except Exception as error:             # whatever it was, keep the journal: the next launch tries again
        txn.log(f"recovery could not finish: {type(error).__name__}: {error}")
        return EXIT_STUCK
    return EXIT_OK


def main(argv):
    if len(argv) == 3 and argv[0] == "install" and argv[2].isdigit():
        return install(argv[1], int(argv[2]))
    if len(argv) == 2 and argv[0] == "recover":
        return recover(argv[1])
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
