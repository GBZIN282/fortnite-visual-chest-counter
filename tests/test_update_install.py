"""
The updater's third layer (v0.2.3): replacing the program, proving the new version starts, and rolling back. The helper runs as a real
separate process on disposable folders, and is stopped dead at every step to prove the recovery. Python scripts stand in for the app.
Run:   python tests/test_update_install.py   (or pytest)
"""

import sys
from pathlib import Path as _P

ROOT = _P(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))   # run without installing

import _winapi
import ast
import atexit
import contextlib
import ctypes
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from ctypes import wintypes
from pathlib import Path

import build_release
import sign_release as S
import test_update_prepare as M2
import update_e2e as E2E
from fortnite_chest_counter import paths
from fortnite_chest_counter.update import archive as Z
from fortnite_chest_counter.update import authenticity as A
from fortnite_chest_counter.update import health
from fortnite_chest_counter.update import install as I
from fortnite_chest_counter.update import install_helper as H
from fortnite_chest_counter.update import releases as R
from fortnite_chest_counter.update import staging as G

OLD, NEW = "0.2.3", "0.2.4"
# A venv's python.exe only starts the real interpreter as a child, so its process id would not be the app's own, as it is in the release.
REAL_PYTHON = str(Path(sys.base_prefix) / "python.exe")
FAST ={"PROCESS_WAIT": 1.5, "PROCESS_POLL": 0.02, "HEALTH_DEADLINE": 8.0, "HEALTH_POLL": 0.01, "RENAME_TRIES": 3, "RENAME_DELAY": 0.03,
        "REPLACE_TRIES": 2, "KILL_WAIT": 2.0}

# Stands in for the application. What it does is set per version in fake_behaviour.json.
FAKE_APP = r"""
import json, os, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
root = here.parent
version = (here / "VERSION").read_text()
args = sys.argv[1:]
spec = json.loads((root / "fake_behaviour.json").read_text()).get(version, {})
with open(root / "fake_log.txt", "a") as f:
    f.write(f"{version} {'health' if args else 'normal'}\n")
(root / f"fake_pid_{version}.txt").write_text(str(os.getpid()))
for name, text in spec.get("write", {}).items():
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text)
for name in spec.get("delete", []):
    (root / name).unlink()
if "exit_early" in spec:
    sys.exit(spec["exit_early"])
if spec.get("hang"):
    time.sleep(40)
if args and not spec.get("no_report"):
    data = {"format": 1, "stage": "ready", "nonce": args[2], "version": version, "pid": os.getpid(), "app_dir": str(root)}
    data.update(spec.get("report", {}))
    text = spec.get("raw_report", json.dumps(data))
    with open(args[1] + ".tmp", "w") as f:
        f.write(text)
    os.replace(args[1] + ".tmp", args[1])
if spec.get("exit_after_report"):
    sys.exit(0)
time.sleep(spec.get("linger", 1.0))
"""

# Runs the real helper from its own folder; `checkpoint` is the only thing replaced, to end the process dead at a chosen step.
WRAPPER = r"""
import json, os, sys
config = json.loads(sys.argv[1])
sys.path.insert(0, config["helper_dir"])
import install_helper as H
for name, value in config["constants"].items():
    setattr(H, name, value)
if config["free_space"] is not None:
    H._free_space = lambda path: config["free_space"]
def checkpoint(name):
    if config["record"]:
        with open(config["record"], "a") as f:
            f.write(name + "\n")
    if name == config["crash_at"]:
        os._exit(42)
    if name == config["raise_at"]:
        raise OSError("simulated failure at " + name)
H.checkpoint = checkpoint
sys.exit(H.main(config["argv"]))
"""

USER_DATA = {"config.toml": b'[display]\nshow = "both"\n', "state/chest_state.json": b'{"certain": 41, "approximate": 57}\n',
             "state/profiles.json": b'{"version": 1, "active": "default", "profiles": []}\n', "state/profiles/streamer.json": b'{"certain": 9, "approximate": 12}\n',
             "state/window.json": b'{"version": 1}\n', "obs_output/chest_counter.txt": b"CERTAIN OPENED CHESTS: 41\n", "logs/session.jsonl": b"{}\n",
             "captures/clip.bin": b"video", "my notes.txt": b"a file the updater knows nothing about"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def runtime_files(version):
    files = {"app.py": FAKE_APP.encode(), "VERSION": version.encode(), "lib/module.txt": f"module of {version}\n".encode(), f"only_in_{version}.txt": b"x"}
    files[H.PACKAGE_FILES] = json.dumps({"format": 1, "version": version, "files": sorted(files)}).encode()
    return files


def root_files(version):
    return {name: f"{name} of {version}\n".encode() for name in H.ROOT_FILES}


def write_tree(base, files):
    for relative, data in files.items():
        path = Path(base) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def tree(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(Path(folder).rglob("*")) if p.is_file()}


class Env:
    """A disposable installation of OLD with NEW already staged and a prepared transaction."""

    def __init__(self, tmp, version_from=OLD, version_to=NEW, journal=True):
        self.root = Path(tmp) / "Fortnite-Visual-Chest-Counter-v0.2.3"
        self.update_dir = self.root / ".update"
        self.version_from, self.version_to = version_from, version_to
        write_tree(self.root, {**USER_DATA, **root_files(version_from), **{f"runtime/{k}": v for k, v in runtime_files(version_from).items()}})
        self.behaviour()
        self.helper_dir = self.update_dir / H.HELPER_FOLDER / "lib"
        self.helper_dir.mkdir(parents=True)
        shutil.copyfile(H.__file__, self.helper_dir / "install_helper.py")
        self.stage(version_to)
        if journal:
            self.write_journal()

    def stage(self, version):
        self.zip_name = R.zip_name(version)
        program = {**root_files(version), **{f"runtime/{k}": v for k, v in runtime_files(version).items()}}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for relative, data in sorted(program.items()):
                z.writestr(f"Fortnite-Visual-Chest-Counter-v{version}/{relative}", data)
        self.package = buffer.getvalue()
        write_tree(self.update_dir / H.DOWNLOAD_FOLDER, {self.zip_name: self.package})
        write_tree(self.update_dir / H.STAGED_FOLDER, program)
        write_tree(self.update_dir, {H.MARKER_NAME: b"{}", H.SIGNED_FILES[0]: b"m", H.SIGNED_FILES[1]: b"s"})

    def write_journal(self, **changes):
        self.nonce = secrets.token_hex(32)
        H.write_json_durably(self.update_dir / H.JOURNAL_NAME, {
            "format": H.JOURNAL_FORMAT, "phase": H.PREPARED, "from_version": self.version_from, "to_version": self.version_to, "zip": self.zip_name,
            "sha256": sha(self.package), "nonce": self.nonce, "app_mutex": f"Local\\fcc-test-{self.nonce[:16]}", "launch": [REAL_PYTHON, "runtime/app.py"],
            "state_dir": "state", "config": "config.toml", "new_started": False, **changes})

    def behaviour(self, **by_version):
        (self.root / "fake_behaviour.json").write_text(json.dumps({k.replace("_", "."): v for k, v in by_version.items()}))

    def run(self, mode="install", wait_pid=0, crash_at=None, record=None, constants=None, free_space=None, raise_at=None):
        argv = ["install", str(self.root), str(wait_pid)] if mode == "install" else ["recover", str(self.root)]
        config = {"helper_dir": str(self.helper_dir), "constants": {**FAST, **(constants or {})}, "free_space": free_space, "record": str(record) if record else None,
                  "crash_at": crash_at, "raise_at": raise_at, "argv": argv}
        return subprocess.run([sys.executable, "-B", "-c", WRAPPER, json.dumps(config)], timeout=90, capture_output=True, text=True).returncode

    def result(self):
        return json.loads((self.update_dir / H.RESULT_NAME).read_text(encoding="utf-8"))

    def journal(self):
        return json.loads((self.update_dir / H.JOURNAL_NAME).read_text(encoding="utf-8"))

    def has_journal(self):
        return (self.update_dir / H.JOURNAL_NAME).exists()

    def fake_log(self):
        path = self.root / "fake_log.txt"
        return path.read_text().splitlines() if path.exists() else []

    def wait_for_log(self, line, seconds=5):
        deadline = time.monotonic() + seconds
        while line not in self.fake_log() and time.monotonic() < deadline:
            time.sleep(0.02)
        return line in self.fake_log()


@contextlib.contextmanager
def env(**options):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        environment = Env(tmp, **options)
        environment.before = user_snapshot(environment)
        yield environment


def user_snapshot(environment):
    """Everything of the user's: content and modification time. Files the updater is allowed to add are left out."""
    root = environment.root
    found = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and not relative.startswith((".update/", "runtime/", "state/backups/", "logs/update_")) \
                and relative not in H.ROOT_FILES and not path.name.startswith("fake_"):
            found[relative] = (path.read_bytes(), path.stat().st_mtime_ns)
    return found


def assert_user_data_intact(environment):
    assert user_snapshot(environment) == environment.before


def assert_is_exactly(environment, version):
    assert tree(environment.root / "runtime") == runtime_files(version), f"runtime is not exactly {version}"
    for name, data in root_files(version).items():
        assert (environment.root / name).read_bytes() == data, name


def assert_closed(environment):
    assert not environment.has_journal(), "the transaction is still open"
    for name in (H.OLD_FOLDER, H.FAILED_FOLDER, H.HEALTH_FOLDER, H.BACKUP_FOLDER):
        assert not (environment.update_dir / name).exists(), name


def assert_aborted(environment, reason):
    assert environment.result()["outcome"] == "aborted" and environment.result()["reason"] == reason, environment.result()
    assert_is_exactly(environment, environment.version_from)
    assert_closed(environment)
    assert_user_data_intact(environment)
    assert (environment.update_dir / H.STAGED_FOLDER / "runtime" / "VERSION").read_text() == environment.version_to, "the prepared package should be kept"
    assert (environment.update_dir / H.DOWNLOAD_FOLDER / environment.zip_name).exists()


def assert_rolled_back(environment, reason):
    result = environment.result()
    assert result["outcome"] == "rolled_back" and result["reason"] == reason, result
    assert_is_exactly(environment, environment.version_from)
    assert_closed(environment)


def assert_committed(environment):
    assert environment.result()["outcome"] == "committed", environment.result()
    assert_is_exactly(environment, environment.version_to)
    assert_closed(environment)
    for name in (H.STAGED_FOLDER, H.DOWNLOAD_FOLDER, H.MARKER_NAME, *H.SIGNED_FILES):
        assert not (environment.update_dir / name).exists(), name


# ---- a normal installation

def test_a_normal_installation_leaves_exactly_the_new_version():
    with env() as e:
        assert e.run() == H.EXIT_OK
        assert_committed(e)
        assert_user_data_intact(e)
        assert e.fake_log() == [f"{NEW} health"], e.fake_log()


def test_unknown_files_in_the_program_folder_are_left_alone():
    with env() as e:
        e.run()
        assert (e.root / "my notes.txt").read_bytes() == USER_DATA["my notes.txt"]


def test_the_result_records_what_happened():
    with env() as e:
        e.run()
        result = e.result()
        assert result["from"] == OLD and result["to"] == NEW and result["reason"] == "healthy" and result["restored"] == []
        logs = list((e.root / "logs").glob("update_*committed*.log"))
        assert len(logs) == 1 and "installing" in logs[0].read_text()


def test_a_copy_of_the_users_data_is_kept_after_committing():
    with env() as e:
        e.run()
        backups = list((e.root / "state" / "backups").glob(f"before-v{NEW}-*"))
        assert len(backups) == 1
        index = json.loads((backups[0] / "index.json").read_text())
        names = {item["path"] for item in index}
        assert names == {"config.toml", "state/chest_state.json", "state/profiles.json", "state/profiles/streamer.json"}
        for item in index:
            assert (backups[0] / item["stored"]).read_bytes() == USER_DATA[item["path"]]


def test_only_the_three_newest_update_backups_are_kept():
    with env() as e:
        backups = e.root / "state" / "backups"
        for number in range(5):
            (backups / f"before-v0.2.{number}-x").mkdir(parents=True)
            time.sleep(0.01)
        (backups / "my-own-backup").mkdir()
        e.run()
        names = sorted(p.name for p in backups.iterdir())
        assert len([n for n in names if n.startswith("before-v")]) == H.KEEP_BACKUPS and "my-own-backup" in names and "before-v0.2.0-x" not in names


def test_a_second_update_works_after_the_first():
    with env() as e:
        e.run()
        assert_committed(e)
        before = user_snapshot(e)
        shutil.copyfile(H.__file__, e.helper_dir / "install_helper.py")
        e.version_from, e.version_to = NEW, "0.2.5"
        e.stage("0.2.5")
        e.write_journal()
        (e.root / "fake_log.txt").unlink()
        assert e.run() == H.EXIT_OK
        assert_committed(e)
        assert user_snapshot(e) == before and e.fake_log() == ["0.2.5 health"]


def test_it_waits_for_the_old_app_to_close():
    with env() as e:
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
        started = time.monotonic()
        assert e.run(wait_pid=sleeper.pid) == H.EXIT_OK
        assert time.monotonic() - started >= 0.4
        assert_committed(e)
        sleeper.wait()


# ---- proving the new version really started

def assert_health_failure(detail_word=None, constants=None, **behaviour):
    with env() as e:
        e.behaviour(**{NEW.replace(".", "_"): behaviour})
        assert e.run(constants=constants) == H.EXIT_OK
        assert_rolled_back(e, "health_failed")
        assert_user_data_intact(e)
        if detail_word:
            assert detail_word in e.result()["detail"], e.result()
        assert e.wait_for_log(f"{OLD} normal"), f"the old version was not started again: {e.fake_log()}"
        assert not (e.update_dir / H.DOWNLOAD_FOLDER).exists(), "a package that failed to start should not be kept"


def test_a_new_version_that_exits_early_is_rolled_back():
    assert_health_failure("closed before", exit_early=3)
    assert_health_failure("closed before", exit_early=0)


def test_a_new_version_that_never_reports_is_rolled_back():
    assert_health_failure("in time", constants={"HEALTH_DEADLINE": 0.6}, hang=True)
    assert_health_failure("in time", constants={"HEALTH_DEADLINE": 0.6}, no_report=True, linger=5)


def test_a_hung_new_version_is_stopped():
    with env() as e:
        e.behaviour(**{NEW.replace(".", "_"): {"hang": True}})
        e.run(constants={"HEALTH_DEADLINE": 0.6})
        assert_rolled_back(e, "health_failed")
        assert H.wait_for_process_exit(int((e.root / f"fake_pid_{NEW}.txt").read_text()), 3), "the hung process is still running"


def test_a_process_that_merely_exists_is_not_a_healthy_start():
    assert_health_failure("in time", constants={"HEALTH_DEADLINE": 0.6}, no_report=True, linger=20)


def test_a_new_version_that_dies_right_after_reporting_is_rolled_back():
    assert_health_failure(None, exit_after_report=True)


def test_forged_and_wrong_health_reports_are_rejected():
    for report in ({"nonce": "0" * 64}, {"nonce": None}, {"version": OLD}, {"version": "9.9.9"}, {"format": 2}, {"stage": "starting"},
                   {"pid": 1}, {"app_dir": "C:\\Windows"}, {"app_dir": None}):
        assert_health_failure("closed", report=report, linger=0.3)


def test_damaged_health_reports_are_rejected():
    for raw in ("not json", "[]", "null", '"text"', "["):
        assert_health_failure("closed", raw_report=raw, linger=0.3)


def test_a_stale_report_from_an_earlier_attempt_cannot_pass():
    with env() as e:
        old_report = {"format": 1, "stage": "ready", "nonce": e.nonce, "version": NEW, "pid": 0, "app_dir": str(e.root)}
        write_tree(e.update_dir / H.HEALTH_FOLDER, {"report.json": json.dumps(old_report).encode()})
        e.behaviour(**{NEW.replace(".", "_"): {"no_report": True, "linger": 0.3}})
        e.run()
        assert_rolled_back(e, "health_failed")


def test_a_new_version_that_cannot_launch_is_rolled_back():
    with env() as e:
        e.write_journal(launch=[str(e.root / "does-not-exist.exe")])
        assert e.run() == H.EXIT_OK
        assert_rolled_back(e, "health_failed")
        assert_user_data_intact(e)


def test_the_health_report_written_by_the_app_is_accepted():
    with env() as e:
        e.write_journal(to_version=__import__("fortnite_chest_counter.version", fromlist=["x"]).__version__)
        txn = H.load_transaction(e.root)
        txn.health_report.parent.mkdir(parents=True, exist_ok=True)
        saved = paths.APP_DIR
        paths.APP_DIR = e.root
        try:
            health.write_report(txn.health_report, txn.data["nonce"])
        finally:
            paths.APP_DIR = saved
        assert H.health_report_is_valid(txn, __import__("os").getpid())
        assert not H.health_report_is_valid(txn, 1)


# ---- refusing before anything has moved

def test_it_refuses_if_the_old_app_never_closes():
    with env() as e:
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            assert e.run(wait_pid=sleeper.pid, constants={"PROCESS_WAIT": 0.3}) == H.EXIT_OK
            assert_aborted(e, "old_app_running")
            time.sleep(0.2)
            assert e.fake_log() == [], "a second copy of the app must not be started while the first is open"
        finally:
            sleeper.kill()
            sleeper.wait()


@contextlib.contextmanager
def program_running_from(folder):
    """A real program file inside `folder` that keeps running."""
    copy = Path(folder) / "ping.exe"
    shutil.copyfile(Path(r"C:\Windows\System32\ping.exe"), copy)
    process = subprocess.Popen([str(copy), "-n", "40", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
    time.sleep(0.2)
    try:
        yield process
    finally:
        process.kill()
        process.wait()


def test_it_refuses_while_anything_runs_from_the_runtime():
    with env() as e, program_running_from(e.root / "runtime"):
        assert H.processes_under([e.root / "runtime"]), "the scan should see it"
        e.run(constants={"PROCESS_WAIT": 0.3})
        assert e.result()["reason"] == "runtime_in_use" and "ping.exe" in e.result()["detail"]
        assert not e.has_journal() and (e.root / "runtime" / "VERSION").read_text() == OLD


def test_it_refuses_while_anything_runs_from_the_staged_package():
    with env() as e, program_running_from(e.update_dir / H.STAGED_FOLDER / "runtime"):
        e.run(constants={"PROCESS_WAIT": 0.3})
        assert e.result()["reason"] == "runtime_in_use"
        assert_is_exactly(e, OLD)


def test_it_waits_for_a_straggler_to_finish():
    with env() as e, program_running_from(e.root / "runtime") as process:
        stopper = subprocess.Popen([sys.executable, "-c", f"import time, os; time.sleep(0.4); os.kill({process.pid}, 9)"])
        code = e.run(constants={"PROCESS_WAIT": 5.0})
        stopper.wait()
        assert code == H.EXIT_OK and e.result()["reason"] == "runtime_has_user_files"     # it got past the wait; the copied program is itself an extra file


def test_a_locked_file_stops_the_swap_with_nothing_changed():
    with env() as e:
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], cwd=e.root / "runtime" / "lib")
        time.sleep(0.2)
        try:
            assert e.run() == H.EXIT_OK
            assert_aborted(e, "runtime_locked")
        finally:
            process.kill()
            process.wait()


def test_a_file_held_open_stops_the_swap_with_nothing_changed():
    with env() as e:
        handle = open(e.root / "runtime" / "lib" / "module.txt", "rb")
        try:
            assert e.run() == H.EXIT_OK
            assert_aborted(e, "runtime_locked")
        finally:
            handle.close()


def test_damaged_staging_is_refused_before_the_swap():
    def flip(e):
        path = e.update_dir / H.STAGED_FOLDER / "runtime" / "VERSION"
        path.write_bytes(b"X" + path.read_bytes()[1:])

    def delete(e):
        (e.update_dir / H.STAGED_FOLDER / "runtime" / "lib" / "module.txt").unlink()

    def add(e):
        (e.update_dir / H.STAGED_FOLDER / "runtime" / "planted.dll").write_bytes(b"x")

    def add_user_file(e):
        (e.update_dir / H.STAGED_FOLDER / "config.toml").write_bytes(b"x")

    def replace_zip(e):
        (e.update_dir / H.DOWNLOAD_FOLDER / e.zip_name).write_bytes(b"something else")

    def remove_zip(e):
        (e.update_dir / H.DOWNLOAD_FOLDER / e.zip_name).unlink()

    for damage in (flip, delete, add, add_user_file, replace_zip, remove_zip):
        with env() as e:
            damage(e)
            assert e.run() == H.EXIT_OK
            assert e.result()["reason"] == "staged_damaged", damage.__name__
            assert_is_exactly(e, OLD)
            assert_user_data_intact(e)
            assert not e.has_journal()


def test_a_users_file_inside_the_runtime_stops_the_update():
    with env() as e:
        (e.root / "runtime" / "my_saved_clip.mp4").write_bytes(b"precious")
        e.before = user_snapshot(e)
        e.run()
        assert e.result()["reason"] == "runtime_has_user_files" and "my_saved_clip.mp4" in e.result()["detail"]
        assert (e.root / "runtime" / "my_saved_clip.mp4").read_bytes() == b"precious" and not (e.update_dir / H.OLD_FOLDER).exists()


def test_python_bytecode_caches_do_not_count_as_user_files():
    with env() as e:
        write_tree(e.root / "runtime" / "lib" / "__pycache__", {"module.cpython-313.pyc": b"cache"})
        assert H.unexpected_runtime_files(e.root) == []


def test_a_missing_or_damaged_file_list_stops_the_update():
    def delete(e):
        (e.root / "runtime" / H.PACKAGE_FILES).unlink()

    def damage(e):
        (e.root / "runtime" / H.PACKAGE_FILES).write_text("{ broken")

    def wrong_shape(e):
        (e.root / "runtime" / H.PACKAGE_FILES).write_text("{}")

    for change in (delete, damage, wrong_shape):
        with env() as e:
            change(e)
            e.run()
            assert e.result()["reason"] == "runtime_unrecognised" and (e.root / "runtime" / "VERSION").read_text() == OLD


def test_not_enough_free_space_is_refused_before_anything_moves():
    with env() as e:
        assert e.run(free_space=1000) == H.EXIT_OK
        assert_aborted(e, "disk_space")


def test_a_failed_backup_of_user_data_stops_the_update():
    with env() as e:
        (e.root / "state" / "directory.json").mkdir()
        assert e.run() == H.EXIT_OK
        assert e.result()["reason"] == "backup_failed"
        assert_is_exactly(e, OLD)


# ---- only one at a time

def test_a_second_helper_is_refused_while_one_runs():
    with env() as e:
        guard = H.NamedMutex(H.transaction_mutex_name(e.root.resolve()))
        try:
            assert e.run() == H.EXIT_BUSY
            assert e.run(mode="recover") == H.EXIT_BUSY
            assert e.journal()["phase"] == H.PREPARED
            assert_is_exactly(e, OLD)
        finally:
            guard.close()


def test_the_app_cannot_be_opened_while_the_helper_works():
    with env() as e:
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.2)"])
        name = e.journal()["app_mutex"]
        helper = subprocess.Popen([sys.executable, "-B", "-c", WRAPPER, json.dumps({
            "helper_dir": str(e.helper_dir), "constants": {**FAST, "PROCESS_WAIT": 5.0}, "free_space": None, "record": None, "crash_at": None, "raise_at": None,
            "argv": ["install", str(e.root), str(sleeper.pid)]})])
        try:
            deadline = time.monotonic() + 1.0
            seen = False
            while time.monotonic() < deadline and not seen:
                probe = H.NamedMutex(name)
                seen = probe.already_existed
                probe.close()
                time.sleep(0.02)
            assert seen, "the helper should hold the app's single-instance lock"
        finally:
            helper.wait(timeout=30)
            sleeper.wait()
        assert_committed(e)


def test_an_install_will_not_run_twice_or_from_a_finished_journal():
    with env() as e:
        e.run()
        assert e.run() == H.EXIT_STUCK                                        # no journal any more
    with env() as e:
        e.write_journal(phase=H.NEW_INSTALLED)
        assert e.run() == H.EXIT_STUCK
        assert_is_exactly(e, OLD)


# ---- stopped dead at every step

def recorded_steps(mode="install", prepare=None, **behaviour):
    with env() as e, tempfile.TemporaryDirectory() as tmp:
        record = Path(tmp) / "steps.txt"
        if behaviour:
            e.behaviour(**{NEW.replace(".", "_"): behaviour})
        if prepare:
            prepare(e)
        e.run(mode=mode, record=record)
        return record.read_text().splitlines()


INSTALL_STEPS = recorded_steps()
FORWARD = ("health_reported", "commit_started", "commit_root_files", "commit_backup_kept", "committed", "cleaned")
EITHER = ("launched",)                     # the new version may or may not have reported yet


def test_the_steps_are_the_expected_transaction():
    assert INSTALL_STEPS == ["started", "old_app_gone", "processes_gone", "staged_verified", "snapshot_done", "old_retained", "new_installed", "awaiting_health",
                             "launched", "health_reported", "commit_started", "commit_root_files", "commit_backup_kept", "committed", "cleaned"], INSTALL_STEPS


def assert_recovered(e, step):
    allowed = (NEW,) if step in FORWARD else (OLD, NEW) if step in EITHER else (OLD,)
    version = (e.root / "runtime" / "VERSION").read_text()
    assert version in allowed, f"after a crash at {step}: runtime is {version}"
    assert tree(e.root / "runtime") == runtime_files(version), f"after a crash at {step}: the runtime is not whole"
    assert_closed(e)
    assert_user_data_intact(e)
    outcome = e.result()["outcome"]
    assert (outcome == "committed") == (version == NEW), f"after a crash at {step}: result says {outcome}, runtime is {version}"
    assert outcome in ("committed", "rolled_back", "aborted")


def test_a_crash_at_every_install_step_recovers_on_the_next_launch():
    for step in INSTALL_STEPS:
        with env() as e:
            assert e.run(crash_at=step) == 42, step
            assert e.has_journal() or step == "cleaned", step
            assert e.run(mode="recover") == H.EXIT_OK, step
            if step == "cleaned":
                assert not e.has_journal() and (e.root / "runtime" / "VERSION").read_text() == NEW
                continue
            assert_recovered(e, step)


def test_a_crash_before_the_commit_is_never_reported_as_success():
    for step in INSTALL_STEPS[:INSTALL_STEPS.index("launched")]:
        with env() as e:
            e.run(crash_at=step)
            assert not (e.update_dir / H.RESULT_NAME).exists(), step
            assert e.run(mode="recover") == H.EXIT_OK
            assert e.result()["outcome"] != "committed", step


def test_a_crash_during_recovery_is_recovered_by_the_next_launch():
    interesting = ["old_retained", "new_installed", "awaiting_health", "health_reported", "commit_root_files"]
    for step in interesting:
        with env() as e, tempfile.TemporaryDirectory() as tmp:
            e.run(crash_at=step)
            record = Path(tmp) / "recover.txt"
            e.run(mode="recover", record=record)
            recovery_steps = record.read_text().splitlines()
        for second in recovery_steps:
            if second == "cleaned":
                continue
            with env() as e:
                e.run(crash_at=step)
                assert e.run(mode="recover", crash_at=second) == 42, (step, second)
                assert e.has_journal(), (step, second)
                assert e.run(mode="recover") == H.EXIT_OK, (step, second)
                assert_recovered(e, step)


def test_a_crash_at_every_rollback_step_finishes_the_rollback():
    behaviour = {"exit_early": 1}
    steps = recorded_steps(**behaviour)
    rollback_steps = [s for s in steps if s.startswith("rollback") or s == "rolled_back"]
    assert rollback_steps == ["rollback_started", "rollback_new_moved_aside", "rollback_old_restored", "rollback_data_reconciled", "rolled_back"], rollback_steps
    for step in rollback_steps:
        with env() as e:
            e.behaviour(**{NEW.replace(".", "_"): behaviour})
            assert e.run(crash_at=step) == 42, step
            assert e.run(mode="recover") == H.EXIT_OK, step
            assert_rolled_back(e, "health_failed")
            assert_user_data_intact(e)
            assert not (e.update_dir / H.DOWNLOAD_FOLDER).exists(), "a package that failed its start must be removed even after a crash"


def test_a_failure_at_every_install_step_ends_consistently():
    for step in INSTALL_STEPS:
        with env() as e:
            code = e.run(raise_at=step)
            assert code in (H.EXIT_OK, H.EXIT_STUCK), (step, code)
            if e.has_journal():
                assert e.run(mode="recover") == H.EXIT_OK, step
            assert_recovered(e, step)


def test_a_failure_at_every_rollback_step_is_finished_by_the_next_launch():
    behaviour = {"exit_early": 1}
    for step in ("rollback_started", "rollback_new_moved_aside", "rollback_old_restored", "rollback_data_reconciled", "rolled_back"):
        with env() as e:
            e.behaviour(**{NEW.replace(".", "_"): behaviour})
            assert e.run(raise_at=step) in (H.EXIT_OK, H.EXIT_STUCK), step
            if e.has_journal():
                assert e.run(mode="recover") == H.EXIT_OK, step
            assert_rolled_back(e, "health_failed")
            assert_user_data_intact(e)


def test_a_version_that_proved_itself_is_never_undone_by_a_later_failure():
    for step in ("health_reported", "commit_started", "commit_root_files", "commit_backup_kept", "committed"):
        with env() as e:
            assert e.run(raise_at=step) == H.EXIT_STUCK, step
            assert (e.root / "runtime" / "VERSION").read_text() == NEW, f"a failure at {step} undid a healthy update"
            assert not (e.update_dir / H.FAILED_FOLDER).exists(), step
            assert e.run(mode="recover") == H.EXIT_OK, step
            assert_committed(e)
            assert_user_data_intact(e)


def test_a_program_reading_the_journal_cannot_break_an_install():
    """What actually happened in the first real run: something else had the journal open at the moment it was replaced."""
    with env() as e:
        stop = threading.Event()

        def keep_reading():
            journal = e.update_dir / H.JOURNAL_NAME
            while not stop.is_set():
                try:
                    journal.read_bytes()
                except OSError:
                    pass
                time.sleep(0.002)

        reader = threading.Thread(target=keep_reading)
        reader.start()
        try:
            assert e.run() == H.EXIT_OK
        finally:
            stop.set()
            reader.join()
        assert_committed(e)
        assert_user_data_intact(e)


def test_waiting_out_a_lock_is_bounded_and_only_for_locks():
    calls = []

    def locked():
        calls.append(1)
        raise PermissionError(13, "in use")

    def broken():
        calls.append(1)
        raise OSError(5, "a real failure")

    def locked_twice():
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "in use")
        return "done"

    with M2.patched(H, LOCK_TRIES=4, LOCK_DELAY=0.0):
        try:
            H.while_locked(locked)
        except PermissionError:
            assert len(calls) == 4
        else:
            raise AssertionError("it should give up")
        calls.clear()
        try:
            H.while_locked(broken)
        except OSError:
            assert len(calls) == 1, "only a lock is worth waiting for"
        calls.clear()
        assert H.while_locked(locked_twice) == "done" and len(calls) == 3


def test_a_journal_write_waits_out_a_brief_lock():
    real, calls = os.replace, []

    def locked_twice(source, target):
        calls.append(source)
        if len(calls) < 3:
            raise PermissionError(13, "in use")
        real(source, target)

    with tempfile.TemporaryDirectory() as tmp, M2.patched(H, LOCK_DELAY=0.0):
        path = Path(tmp) / H.JOURNAL_NAME
        H.write_json_durably(path, {"phase": "first"})
        calls.clear()
        with M2.patched(H.os, replace=locked_twice):
            H.write_json_durably(path, {"phase": "second"})
        assert json.loads(path.read_text())["phase"] == "second" and len(calls) == 3


def test_a_journal_that_cannot_be_written_keeps_the_last_complete_record():
    def locked(source, target):
        raise PermissionError(13, "in use")

    with tempfile.TemporaryDirectory() as tmp, M2.patched(H, LOCK_TRIES=3, LOCK_DELAY=0.0):
        path = Path(tmp) / H.JOURNAL_NAME
        H.write_json_durably(path, {"phase": "first"})
        with M2.patched(H.os, replace=locked):
            try:
                H.write_json_durably(path, {"phase": "second"})
            except PermissionError:
                pass
            else:
                raise AssertionError("it should report the failure")
        assert json.loads(path.read_text())["phase"] == "first"


def test_the_transaction_in_memory_never_gets_ahead_of_the_journal():
    def locked(source, target):
        raise PermissionError(13, "in use")

    with env() as e, M2.patched(H, LOCK_TRIES=2, LOCK_DELAY=0.0):
        txn = H.load_transaction(e.root)
        with M2.patched(H.os, replace=locked):
            try:
                txn.save(phase=H.COMMITTING)
            except PermissionError:
                pass
        assert txn.phase == H.PREPARED and e.journal()["phase"] == H.PREPARED


@contextlib.contextmanager
def exclusively_locked(path):
    handle = _winapi.CreateFile(str(path), 0x80000000, 0, 0, 3, 0, 0)         # GENERIC_READ, no sharing at all, OPEN_EXISTING
    try:
        yield
    finally:
        _winapi.CloseHandle(handle)


def test_a_locked_journal_is_not_mistaken_for_a_damaged_one():
    with env() as e:
        e.run(crash_at="new_installed")
        with exclusively_locked(e.update_dir / H.JOURNAL_NAME):
            with M2.patched(H, LOCK_TRIES=2, LOCK_DELAY=0.0):
                try:
                    H.load_transaction(e.root)
                except PermissionError:
                    pass
                else:
                    raise AssertionError("a locked journal must not be read as a damaged one")
            assert e.run(mode="recover", constants={"LOCK_TRIES": 3, "LOCK_DELAY": 0.01}) == H.EXIT_STUCK
            assert not (e.update_dir / H.RESULT_NAME).exists(), "it acted on a journal it could not read"
            assert (e.root / "runtime" / "VERSION").read_text() == NEW and (e.update_dir / H.OLD_FOLDER / "runtime").exists()
        assert e.run(mode="recover") == H.EXIT_OK
        assert_rolled_back(e, "interrupted")
        assert_user_data_intact(e)


def test_a_valid_report_left_by_a_crashed_helper_completes_the_update():
    with env() as e:
        e.behaviour(**{NEW.replace(".", "_"): {"linger": 1.5}})
        assert e.run(crash_at="launched") == 42
        deadline = time.monotonic() + 5
        while not (e.update_dir / H.HEALTH_FOLDER / "report.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert e.run(mode="recover") == H.EXIT_OK
        assert_committed(e)


def test_recovery_with_no_transaction_does_nothing():
    with env(journal=False) as e:
        before = tree(e.root / "runtime")
        assert e.run(mode="recover") == H.EXIT_OK
        assert tree(e.root / "runtime") == before and not (e.update_dir / H.RESULT_NAME).exists()


def test_an_unreadable_journal_is_never_treated_as_success():
    for text in ("", "{ broken", "[]", "null", '{"phase": "committing"}', '{"format": 99, "phase": "committing"}', '{"format": 1}'):
        with env() as e:                                                      # nothing had moved
            (e.update_dir / H.JOURNAL_NAME).write_text(text)
            assert e.run(mode="recover") == H.EXIT_OK, text
            assert_aborted(e, "interrupted")
        with env() as e:                                                      # the old runtime had already been moved away
            e.run(crash_at="new_installed")
            (e.update_dir / H.JOURNAL_NAME).write_text(text)
            assert e.run(mode="recover") == H.EXIT_OK, text
            assert e.result()["outcome"] == "rolled_back", text
            assert_is_exactly(e, OLD)
            assert_user_data_intact(e)


def test_a_torn_journal_write_leaves_the_last_complete_record():
    with env() as e:
        e.run(crash_at="new_installed")
        (e.update_dir / (H.JOURNAL_NAME + ".tmp")).write_text('{"format": 1, "phase": "comm')          # power lost while writing the next one
        assert e.run(mode="recover") == H.EXIT_OK
        assert e.result()["outcome"] == "rolled_back"
        assert_is_exactly(e, OLD)


def test_recovery_reports_it_is_stuck_rather_than_claiming_success():
    with env() as e:
        e.run(crash_at="new_installed")
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], cwd=e.root / "runtime" / "lib")     # holds the new runtime
        time.sleep(0.2)
        try:
            assert e.run(mode="recover") == H.EXIT_STUCK
            assert e.has_journal() and not (e.update_dir / H.RESULT_NAME).exists()
        finally:
            process.kill()
            process.wait()
        assert e.run(mode="recover") == H.EXIT_OK                             # and the next launch finishes it
        assert_rolled_back(e, "interrupted")


def test_if_both_runtimes_are_gone_it_says_so():
    with env() as e:
        e.run(crash_at="old_retained")
        shutil.rmtree(e.update_dir / H.OLD_FOLDER)
        assert e.run(mode="recover") == H.EXIT_STUCK
        assert not (e.update_dir / H.RESULT_NAME).exists()


# ---- user data across a rollback

NEW_KEY = NEW.replace(".", "_")


def rolled_back_after(**behaviour):
    e = env()
    entered = e.__enter__()
    entered.behaviour(**{NEW_KEY: {"exit_early": 1, **behaviour}})
    entered.run()
    return e, entered


def test_changes_the_old_version_can_read_are_kept():
    newer = '{"certain": 45, "approximate": 60}\n'
    e, env_ = rolled_back_after(write={"state/chest_state.json": newer})
    try:
        assert_rolled_back(env_, "health_failed")
        assert (env_.root / "state/chest_state.json").read_text() == newer, "the user's newer numbers were overwritten"
        result = env_.result()
        assert result["kept_newer"] == ["state/chest_state.json"] and result["restored"] == []
    finally:
        e.__exit__(None, None, None)


def test_a_format_the_old_version_cannot_read_is_restored_and_the_newer_file_kept():
    migrated = '{"schema": 2, "totals": {"certain": 45}}\n'
    e, env_ = rolled_back_after(write={"state/chest_state.json": migrated})
    try:
        assert (env_.root / "state/chest_state.json").read_bytes() == USER_DATA["state/chest_state.json"]
        result = env_.result()
        assert result["restored"] == ["state/chest_state.json"] and result["kept_newer"] == []
        kept = list((env_.root / "state" / "backups").glob(f"from-failed-v{NEW}-*/*"))
        assert len(kept) == 1 and kept[0].read_text() == migrated, "the newer file must be kept, never discarded"
    finally:
        e.__exit__(None, None, None)


def test_every_kind_of_user_file_is_checked():
    cases = {"state/profiles.json": ('{"profiles": "not a list"}', '{"version": 1, "active": "x", "profiles": []}'),
             "state/profiles/streamer.json": ('{"certain": -1, "approximate": 0}', '{"certain": 10, "approximate": 20}'),
             "config.toml": ("[broken", '[display]\nshow = "certain"\n')}
    for name, (unreadable, readable) in cases.items():
        e, env_ = rolled_back_after(write={name: unreadable})
        try:
            assert (env_.root / name).read_bytes() == USER_DATA[name] and env_.result()["restored"] == [name], name
        finally:
            e.__exit__(None, None, None)
        e, env_ = rolled_back_after(write={name: readable})
        try:
            assert (env_.root / name).read_text() == readable and env_.result()["kept_newer"] == [name], name
        finally:
            e.__exit__(None, None, None)


def test_a_file_the_new_version_deleted_is_restored():
    e, env_ = rolled_back_after(delete=["state/profiles/streamer.json"])
    try:
        assert (env_.root / "state/profiles/streamer.json").read_bytes() == USER_DATA["state/profiles/streamer.json"]
        assert env_.result()["restored"] == ["state/profiles/streamer.json"]
    finally:
        e.__exit__(None, None, None)


def test_a_new_file_the_new_version_created_is_left_alone():
    e, env_ = rolled_back_after(write={"state/profiles/new-person.json": '{"certain": 1, "approximate": 1}'})
    try:
        assert (env_.root / "state/profiles/new-person.json").exists() and env_.result()["restored"] == []
    finally:
        e.__exit__(None, None, None)


def test_if_nothing_changed_nothing_is_restored():
    e, env_ = rolled_back_after()
    try:
        assert env_.result()["restored"] == [] and env_.result()["kept_newer"] == []
        assert_user_data_intact(env_)
    finally:
        e.__exit__(None, None, None)


def test_a_rollback_before_the_new_version_ran_does_not_compare_data():
    with env() as e:
        e.run(crash_at="old_retained")
        (e.root / "state/chest_state.json").write_text("the user edited this by hand")
        e.before = user_snapshot(e)
        assert e.run(mode="recover") == H.EXIT_OK
        assert_user_data_intact(e)


def test_a_data_folder_outside_the_program_folder_is_protected_too():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as elsewhere, env() as e:
        data = Path(elsewhere) / "counts"
        write_tree(data, {"chest_state.json": USER_DATA["state/chest_state.json"]})
        e.write_journal(state_dir=str(data))
        path = data / "chest_state.json"
        e.run(crash_at="awaiting_health")
        path.write_text('{"unreadable": true}')
        assert e.run(mode="recover") == H.EXIT_OK
        assert path.read_bytes() == USER_DATA["state/chest_state.json"] and e.result()["restored"] == [str(path)]


def test_a_committed_version_keeps_what_it_wrote():
    migrated = '{"schema": 2, "totals": {"certain": 45}}\n'
    with env() as e:
        e.behaviour(**{NEW_KEY: {"write": {"state/chest_state.json": migrated}}})
        e.run()
        assert_committed(e)
        assert (e.root / "state/chest_state.json").read_text() == migrated
        backup = next((e.root / "state/backups").glob(f"before-v{NEW}-*"))
        index = json.loads((backup / "index.json").read_text())
        item = next(i for i in index if i["path"] == "state/chest_state.json")
        assert (backup / item["stored"]).read_bytes() == USER_DATA["state/chest_state.json"], "the pre-update copy must survive a commit"


# ---- starting an installation from the app

@contextlib.contextmanager
def prepared_workspace(**stage_options):
    package = M2.build_zip()
    with M2.workspace() as ws:
        live = tree(ws.app / "runtime")
        listing = json.dumps({"format": 1, "version": "0.2.2", "files": sorted(live)}).encode()
        (ws.app / "runtime" / H.PACKAGE_FILES).write_bytes(listing)
        M2.stage(ws, package, **stage_options)
        python = ws.app.parent / "official-python"
        write_tree(python, {"python.exe": b"python", "pythonw.exe": b"pythonw", "python313._pth": b"python313.zip\n.\n..\\lib\n"})
        ws.python = python
        ws.package = package
        ws.options = dict(app_dir=ws.app, installed="0.2.2", public_keys=[S.public_key_hex(M2.KEY)], python_folder=python, app_mutex="Local\\fcc-test-m3", spawn=False)
        yield ws


def expect(kind, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except R.UpdateError as error:
        assert error.kind == kind, f"got {error.kind}, wanted {kind}: {error}"
        return error
    raise AssertionError(f"expected an UpdateError of kind {kind}")


def assert_nothing_started(ws):
    assert not (ws.update_dir / H.JOURNAL_NAME).exists() and (ws.app / "runtime/python/python.exe").read_bytes() == b"the old python"


def test_begin_install_prepares_a_transaction_and_moves_nothing():
    with prepared_workspace() as ws:
        before = M2.snapshot(ws.app)
        started = I.begin_install(**ws.options)
        assert started.version == M2.VERSION and M2.snapshot(ws.app) == before
        journal = json.loads((ws.update_dir / H.JOURNAL_NAME).read_text())
        assert journal["phase"] == H.PREPARED and journal["from_version"] == "0.2.2" and journal["to_version"] == M2.VERSION
        assert journal["sha256"] == sha(ws.package) and len(journal["nonce"]) == 64 and journal["new_started"] is False
        helper = ws.update_dir / H.HELPER_FOLDER
        assert (helper / "lib" / "install_helper.py").read_bytes() == Path(H.__file__).read_bytes()
        assert tree(helper / "python") == tree(ws.python)


def test_every_installation_gets_a_new_nonce():
    with prepared_workspace() as ws:
        I.begin_install(**ws.options)
        first = json.loads((ws.update_dir / H.JOURNAL_NAME).read_text())["nonce"]
        (ws.update_dir / H.JOURNAL_NAME).unlink()
        I.begin_install(**ws.options)
        assert json.loads((ws.update_dir / H.JOURNAL_NAME).read_text())["nonce"] != first


def test_the_signature_is_checked_again_at_install_time():
    with prepared_workspace() as ws:
        manifest = ws.update_dir / H.SIGNED_FILES[0]
        original = manifest.read_bytes()
        manifest.write_bytes(original.replace(b'"size":', b'"size":1'))
        expect("signature_invalid", I.begin_install, **ws.options)
        assert_nothing_started(ws)
        manifest.write_bytes(original)
        (ws.update_dir / H.SIGNED_FILES[1]).write_bytes(b"garbage")
        expect("signature_invalid", I.begin_install, **ws.options)
        assert_nothing_started(ws)


def test_only_keys_installed_in_this_app_count_at_install_time():
    with prepared_workspace() as ws:
        expect("no_trusted_keys", I.begin_install, **{**ws.options, "public_keys": ()})
        stranger = S.ECC.generate(curve="ed25519")
        expect("untrusted_key", I.begin_install, **{**ws.options, "public_keys": [S.public_key_hex(stranger)]})
        assert_nothing_started(ws)


def test_a_downgrade_is_refused_at_install_time():
    with prepared_workspace() as ws:
        for installed in (M2.VERSION, "9.9.9", "not a version"):
            expect("downgrade", I.begin_install, **{**ws.options, "installed": installed})
        assert_nothing_started(ws)


def test_nothing_prepared_or_damaged_staging_is_refused():
    with M2.workspace() as ws:
        expect("not_prepared", I.begin_install, app_dir=ws.app, installed="0.2.2", public_keys=[S.public_key_hex(M2.KEY)], spawn=False)
    with prepared_workspace() as ws:
        (ws.update_dir / H.STAGED_FOLDER / Z.VERSION_FILE).write_bytes(b"changed")
        expect("not_prepared", I.begin_install, **ws.options)
        assert_nothing_started(ws)


def test_a_second_installation_is_refused():
    with prepared_workspace() as ws:
        I.begin_install(**ws.options)
        expect("transaction_active", I.begin_install, **ws.options)
    with prepared_workspace() as ws:
        guard = H.NamedMutex(H.transaction_mutex_name(ws.app.resolve()))
        try:
            expect("transaction_active", I.begin_install, **ws.options)
            assert_nothing_started(ws)
        finally:
            guard.close()


def test_a_journal_left_by_the_launchers_last_resort_does_not_block_updates():
    with prepared_workspace() as ws:
        write_tree(ws.update_dir, {H.JOURNAL_NAME: b'{"format": 1, "phase": "old_retained"}'})     # no helper, no retained runtime
        assert I.begin_install(**ws.options).version == M2.VERSION
        assert json.loads((ws.update_dir / H.JOURNAL_NAME).read_text())["phase"] == H.PREPARED
    with prepared_workspace() as ws:                                          # a retained runtime means it is NOT finished
        write_tree(ws.update_dir, {H.JOURNAL_NAME: b'{"format": 1, "phase": "old_retained"}', f"{H.OLD_FOLDER}/runtime/x": b"x"})
        expect("transaction_active", I.begin_install, **ws.options)
    with prepared_workspace() as ws:                                          # a helper present means the launcher can still finish it
        write_tree(ws.update_dir, {H.JOURNAL_NAME: b'{"format": 1, "phase": "old_retained"}', f"{H.HELPER_FOLDER}/python/pythonw.exe": b"x"})
        expect("transaction_active", I.begin_install, **ws.options)


def test_user_files_inside_the_runtime_are_refused_up_front():
    with prepared_workspace() as ws:
        (ws.app / "runtime" / "my_clip.mp4").write_bytes(b"x")
        error = expect("runtime_has_user_files", I.begin_install, **ws.options)
        assert "my_clip.mp4" in str(error)
        assert_nothing_started(ws)


def test_settings_that_keep_data_inside_the_runtime_are_refused():
    with prepared_workspace() as ws:
        expect("data_in_runtime", I.begin_install, **{**ws.options, "data_paths": [ws.app / "runtime" / "captures"]})
        assert_nothing_started(ws)
        I.begin_install(**{**ws.options, "data_paths": [ws.app / "captures", ws.app / "state", ws.app.parent / "elsewhere"]})


def test_linked_folders_are_refused():
    with prepared_workspace() as ws:
        real = ws.app.parent / "real-runtime"
        (ws.app / "runtime").rename(real)
        _winapi.CreateJunction(str(real), str(ws.app / "runtime"))
        try:
            expect("unsupported_folder", I.begin_install, **ws.options)
            assert not (ws.update_dir / H.JOURNAL_NAME).exists()
        finally:
            __import__("os").rmdir(ws.app / "runtime")


def test_a_folder_that_cannot_be_changed_is_refused():
    def refuse(*args, **kwargs):
        raise OSError("denied")

    with prepared_workspace() as ws:
        with M2.patched(I.os, rename=refuse):
            expect("not_writable", I.begin_install, **ws.options)
        assert_nothing_started(ws)


def test_not_enough_space_is_refused_up_front():
    with prepared_workspace() as ws, M2.patched(shutil, disk_usage=lambda path: M2.SimpleNamespace(free=1000)):
        expect("disk_space", I.begin_install, **ws.options)
        assert_nothing_started(ws)


def test_if_the_helper_cannot_start_the_transaction_is_withdrawn():
    def cannot_start(*args):
        raise R.UpdateError("helper_failed", "no")

    with prepared_workspace() as ws, M2.patched(I, _spawn_helper=cannot_start):
        expect("helper_failed", I.begin_install, **{**ws.options, "spawn": True})
        assert_nothing_started(ws)


def test_leftovers_of_an_old_attempt_are_cleared():
    with prepared_workspace() as ws:
        write_tree(ws.update_dir / H.OLD_FOLDER / "runtime", {"junk": b"x"})
        write_tree(ws.update_dir / H.FAILED_FOLDER / "runtime", {"junk": b"x"})
        I.begin_install(**ws.options)
        assert not (ws.update_dir / H.OLD_FOLDER).exists() and not (ws.update_dir / H.FAILED_FOLDER).exists()


def test_the_helper_files_are_removed_only_after_the_transaction():
    with env() as e:
        assert I.cleanup_finished(e.root) is False and (e.update_dir / H.HELPER_FOLDER).exists()
        e.run()
        guard = H.NamedMutex(H.transaction_mutex_name(e.root.resolve()))
        assert I.cleanup_finished(e.root) is False
        guard.close()
        assert I.last_result(e.root)["outcome"] == "committed"
        assert I.cleanup_finished(e.root) is True and not (e.update_dir / H.HELPER_FOLDER).exists()


# ---- the real launcher and the real embedded Python, on a tiny program (no Qt, no FFmpeg, no package build)
# Uses the launcher and the 22 MB Python of a local disposable build if there is one. Files are hard links, so almost nothing is written.

REAL_BUILD = next(iter(sorted(ROOT.glob("build_out/e2e/out_a/Fortnite-Visual-Chest-Counter-v*"))), None)
STUB_APP = FAKE_APP.replace('here = Path(__file__).resolve().parent\nroot = here.parent', 'root = Path(sys.executable).resolve().parents[2]\nhere = root / "runtime"')
assert STUB_APP != FAKE_APP
REAL_WRAPPER = r"""
import json, os, sys
import install_helper as H
c = json.loads(sys.argv[1])
for name, value in c["constants"].items():
    setattr(H, name, value)
def checkpoint(name):
    if name == c["crash_at"]:
        os._exit(42)
H.checkpoint = checkpoint
sys.exit(H.main(c["argv"]))
"""
_real_package = {}


def _link(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


class RealInstall(Env):
    """A tiny installation whose launcher and Python are the real, built ones. Only the app itself is a stand-in."""

    def __init__(self, tmp):
        self.root = Path(tmp) / "Fortnite-Visual-Chest-Counter-v0.2.3"
        self.update_dir = self.root / H.UPDATE_FOLDER
        self.launcher = self.root / H.ROOT_FILES[0]
        self.version_from, self.version_to = OLD, NEW
        write_tree(self.root, USER_DATA)
        self.behaviour(**{OLD.replace(".", "_"): {"linger": 8}, NEW.replace(".", "_"): {"linger": 8}})
        self.place_program(self.root, OLD)
        staged = self.update_dir / H.STAGED_FOLDER
        self.place_program(staged, NEW)
        self.zip_name = R.zip_name(NEW)
        self.package = b""
        if "path" not in _real_package:
            folder = Path(tempfile.mkdtemp(prefix="fcc-real-"))
            atexit.register(shutil.rmtree, folder, True)
            path = folder / self.zip_name
            with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
                for file in sorted(p for p in staged.rglob("*") if p.is_file()):
                    z.write(file, f"Fortnite-Visual-Chest-Counter-v{NEW}/{file.relative_to(staged).as_posix()}")
            _real_package.update(path=path, sha=H._sha256(path))
        _link(_real_package["path"], self.update_dir / H.DOWNLOAD_FOLDER / self.zip_name)
        self.helper = I.build_helper(self.update_dir, self.root / "runtime" / "python")
        self.write_journal(launch=list(H.DEFAULT_LAUNCH), sha256=_real_package["sha"])
        self.before = user_snapshot(self)

    @staticmethod
    def place_program(target, version):
        for file in (REAL_BUILD / "runtime" / "python").iterdir():
            if file.is_file():
                _link(file, target / "runtime" / "python" / file.name)
        write_tree(target / "runtime", {"VERSION": version.encode(), "lib/fortnite_chest_counter/__init__.py": b"", "lib/fortnite_chest_counter/gui/__init__.py": b"",
                                        "lib/fortnite_chest_counter/gui/__main__.py": STUB_APP.encode()})
        runtime = target / "runtime"
        files = sorted(p.relative_to(runtime).as_posix() for p in runtime.rglob("*") if p.is_file())
        (runtime / H.PACKAGE_FILES).write_text(json.dumps({"format": 1, "version": version, "files": files}))
        launcher = (REAL_BUILD / H.ROOT_FILES[0]).read_bytes()
        write_tree(target, {H.ROOT_FILES[0]: launcher if version == OLD else launcher + b"new", **{n: f"{n} {version}".encode() for n in H.ROOT_FILES[1:]}})

    def version(self):
        return (self.root / "runtime" / "VERSION").read_text()

    def helper_run(self, crash_at=None, mode="install", constants=None):
        argv = ["install", str(self.root), "0"] if mode == "install" else ["recover", str(self.root)]
        return subprocess.run([str(self.helper / "python" / "python.exe"), "-B", "-c", REAL_WRAPPER, json.dumps({"crash_at": crash_at, "constants": constants or {}, "argv": argv})],
                              cwd=self.helper, timeout=120, creationflags=0x08000000).returncode

    def run_launcher(self):
        subprocess.run([str(self.launcher)], cwd=self.root, timeout=150)

    def finished(self):
        return (self.update_dir / H.RESULT_NAME).exists() and not self.has_journal()

    def app_running(self):
        return any(Path(p).name.lower() == "pythonw.exe" for _, p in H.processes_under([self.root / "runtime"]))

    def stop(self):
        for _ in range(100):
            running = H.processes_under([self.root])
            if not running:
                return
            for pid, _name in running:
                H._terminate(pid)
            time.sleep(0.05)


def wait_until(condition, seconds, what):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


@contextlib.contextmanager
def real_install():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        install = RealInstall(tmp)
        try:
            yield install
        finally:
            install.stop()


def no_real_build():
    if REAL_BUILD is None or not (REAL_BUILD / H.ROOT_FILES[0]).exists():
        print("      (skipped: no local disposable build in build_out/e2e)")
        return True
    return False


def close_dialog(process, seconds):
    """Close a message box the way a user would. -> True if one appeared."""
    user32 = ctypes.WinDLL("user32")
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and process.poll() is None:
        found = []

        def visit(window, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if owner.value == process.pid and user32.IsWindowVisible(window):
                found.append(window)
            return True

        user32.EnumWindows(callback(visit), 0)
        if found:
            user32.PostMessageW(found[0], 0x0010, 0, 0)                       # WM_CLOSE
            process.wait(timeout=10)
            return True
        time.sleep(0.05)
    return False


def test_real_detached_helper_installs_and_the_new_version_opens():
    if no_real_build():
        return
    with real_install() as r:
        I._spawn_helper(r.helper, r.root, 0)
        wait_until(r.finished, 60, "the update")
        assert r.result()["outcome"] == "committed" and r.version() == NEW, r.result()
        assert r.launcher.read_bytes().endswith(b"new"), "the launcher should have been replaced"
        assert r.app_running() and r.fake_log() == [f"{NEW} health"], r.fake_log()
        assert_user_data_intact(r)


def test_real_failed_start_rolls_back_and_reopens_the_old_version():
    if no_real_build():
        return
    with real_install() as r:
        r.behaviour(**{OLD.replace(".", "_"): {"linger": 8}, NEW.replace(".", "_"): {"exit_early": 7}})
        I._spawn_helper(r.helper, r.root, 0)
        wait_until(r.finished, 60, "the rollback")
        result = r.result()
        assert result["outcome"] == "rolled_back" and "exit code 7" in result["detail"] and r.version() == OLD, result
        assert r.wait_for_log(f"{OLD} normal", 15) and not r.launcher.read_bytes().endswith(b"new")
        assert_user_data_intact(r)


def test_real_process_scan_refuses_while_the_runtime_is_in_use():
    if no_real_build():
        return
    with real_install() as r:
        sleeper = subprocess.Popen([str(r.root / "runtime" / "python" / "python.exe"), "-c", "import time; time.sleep(40)"], cwd=r.root, creationflags=0x08000000)
        time.sleep(0.5)
        assert r.helper_run(constants={"PROCESS_WAIT": 0.5}) == H.EXIT_OK
        sleeper.kill()
        sleeper.wait()
        assert r.result()["outcome"] == "aborted" and r.result()["reason"] == "runtime_in_use" and r.version() == OLD, r.result()


def crash_and_use_the_real_launcher(step, expected_outcome, expected_version):
    with real_install() as r:
        assert r.helper_run(crash_at=step) == 42, step
        if step == "launched":
            wait_until((r.update_dir / H.HEALTH_FOLDER / "report.json").exists, 30, "the health report")
        r.run_launcher()
        wait_until(r.finished, 60, f"recovery after {step}")
        assert r.result()["outcome"] == expected_outcome and r.version() == expected_version, (step, r.result())
        wait_until(r.app_running, 20, "the app to open")
        assert_user_data_intact(r)


def test_real_launcher_recovers_a_crash_with_the_old_runtime_moved_away():
    if not no_real_build():
        crash_and_use_the_real_launcher("old_retained", "rolled_back", OLD)


def test_real_launcher_recovers_a_crash_with_the_new_runtime_in_place():
    if not no_real_build():
        crash_and_use_the_real_launcher("new_installed", "rolled_back", OLD)


def test_real_launcher_recovers_a_crash_just_before_the_new_version_starts():
    if not no_real_build():
        crash_and_use_the_real_launcher("awaiting_health", "rolled_back", OLD)


def test_real_launcher_completes_an_update_whose_new_version_reported():
    if not no_real_build():
        crash_and_use_the_real_launcher("launched", "committed", NEW)


def test_real_launcher_finishes_an_interrupted_commit():
    if not no_real_build():
        crash_and_use_the_real_launcher("commit_root_files", "committed", NEW)


def test_real_launcher_last_resort_when_the_helper_is_gone():
    if no_real_build():
        return
    with real_install() as r:
        assert r.helper_run(crash_at="old_retained") == 42 and not (r.root / "runtime").exists()
        shutil.rmtree(r.helper)
        r.run_launcher()
        assert r.version() == OLD and not (r.update_dir / H.OLD_FOLDER / "runtime").exists()
        wait_until(r.app_running, 20, "the app to open")
        assert_user_data_intact(r)


def test_real_launcher_starts_the_app_normally_with_no_update_pending():
    if no_real_build():
        return
    with real_install() as r:
        (r.update_dir / H.JOURNAL_NAME).unlink()
        r.run_launcher()
        wait_until(r.app_running, 20, "the app to open")
        assert r.wait_for_log(f"{OLD} normal", 15)


def test_real_launcher_will_not_open_the_app_during_an_update():
    if no_real_build():
        return
    with real_install() as r:
        guard = H.NamedMutex(H.transaction_mutex_name(r.root.resolve()))
        launcher = subprocess.Popen([str(r.launcher)], cwd=r.root)
        try:
            assert close_dialog(launcher, 60), "the launcher should explain"
        finally:
            guard.close()
        assert launcher.wait(timeout=10) == 0 and not r.app_running() and r.has_journal() and r.fake_log() == []


def test_real_launcher_explains_a_stuck_update_and_recovers_later():
    if no_real_build():
        return
    with real_install() as r:
        assert r.helper_run(crash_at="new_installed") == 42
        holder = subprocess.Popen([REAL_PYTHON, "-c", "import time; time.sleep(120)"], cwd=r.root / "runtime" / "lib", creationflags=0x08000000)
        time.sleep(0.3)
        launcher = subprocess.Popen([str(r.launcher)], cwd=r.root)
        try:
            assert close_dialog(launcher, 100), "the launcher should explain"
            assert not r.app_running() and r.has_journal() and not (r.update_dir / H.RESULT_NAME).exists()
        finally:
            holder.kill()
            holder.wait()
        r.run_launcher()
        wait_until(r.finished, 60, "recovery")
        assert r.result()["outcome"] == "rolled_back" and r.version() == OLD
        assert_user_data_intact(r)


# ---- the manual packaged test tool (only its light parts: it is never run against a real package here)

def tiny_build(folder):
    base = Path(folder) / "Fortnite-Visual-Chest-Counter-v0.2.90"
    lib = "runtime/lib/fortnite_chest_counter"
    write_tree(base, {**root_files("0.2.90"), "runtime/python/python313._pth": b"python313.zip\n.\n..\\lib\n", "runtime/python/python.exe": b"x", f"{lib}/version.py": b'__version__ = "0.2.90"\n',
                      f"{lib}/update/trust.py": b"TRUSTED_PUBLIC_KEYS = ()\n", "state/README.txt": b"s", "logs/README.txt": b"l", "obs_output/chest_counter.txt": b"0"})
    (base / "runtime" / H.PACKAGE_FILES).write_text(json.dumps({"format": 1, "version": "0.2.90", "files": []}))
    return base


def test_the_e2e_kit_is_built_without_touching_its_sources():
    with tempfile.TemporaryDirectory() as tmp:
        base = tiny_build(Path(tmp) / "build")
        before = tree(base)
        kit = Path(tmp) / "kit"
        E2E.make_kit(base, kit, max_path=400)
        assert tree(base) == before, "the build it started from must not change"
        info = json.loads((kit / "kit.json").read_text())
        assert (info["healthy"], info["broken"], info["next"]) == ("0.2.91", "0.2.92", "0.2.93")
        installed = kit / "base" / base.name
        package = ROOT / "src/fortnite_chest_counter"
        for file in package.rglob("*.py"):                                    # a kit made from an older build must test today's program
            assert (installed / "runtime/lib/fortnite_chest_counter" / file.relative_to(package)).exists(), file
        assert "[update]" in (installed / "config.example.toml").read_text(encoding="utf-8")
        trust_text = (installed / "runtime/lib/fortnite_chest_counter/update/trust.py").read_text()
        key = E2E.ECC_import((kit / "test_key.pem").read_text())
        assert S.public_key_hex(key) in trust_text
        for version in ("0.2.91", "0.2.92", "0.2.93"):
            release = kit / "releases" / version
            manifest = (release / H.SIGNED_FILES[0]).read_bytes()
            A.verify_signature(manifest, (release / H.SIGNED_FILES[1]).read_bytes(), [S.public_key_hex(key)])
            assert A.parse_manifest(manifest).version == version and not (release / "tree").exists()
            zip_path = release / R.zip_name(version)
            assert A.file_sha256(zip_path) == A.parse_manifest(manifest).sha256
            with zipfile.ZipFile(zip_path) as z:
                assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist()), "storing avoids compressing 400 MB three times"
                name = f"Fortnite-Visual-Chest-Counter-v{version}/runtime/lib/fortnite_chest_counter/"
                assert f'__version__ = "{version}"' in z.read(name + "version.py").decode()
                gui = z.read(name + "gui/app.py").decode()
                assert ("sys.exit(7)" in gui) == (version == "0.2.92"), version
        assert '__version__ = "0.2.90"' in (installed / "runtime/lib/fortnite_chest_counter/version.py").read_text(), "a derived release wrote through a hard link"
        assert "sys.exit(7)" not in (installed / "runtime/lib/fortnite_chest_counter/gui/app.py").read_text(encoding="utf-8")


def test_the_e2e_kit_stays_outside_the_repository_and_on_a_short_path():
    with tempfile.TemporaryDirectory() as tmp:
        base = tiny_build(Path(tmp) / "build")
        for out, limit in ((ROOT / "build_out" / "must-not-exist-kit", 400), (Path(tmp) / "kit", 3)):
            try:
                E2E.make_kit(base, out, max_path=limit)
            except SystemExit:
                assert not out.exists()
            else:
                raise AssertionError(out)


def test_the_e2e_tool_runs_one_named_scenario_and_never_watches_the_journal():
    assert set(E2E.SCENARIOS) == {"healthy", "failed-start", "damaged-data", "crash-after-swap", "chained"}
    assert E2E.main(["run", "all"]) == 2 and E2E.main(["run", "no-such-scenario"]) == 2
    source = (ROOT / "tests" / "update_e2e.py").read_text(encoding="utf-8")
    tree_ = ast.parse(source)
    calls = [n.func.attr for n in ast.walk(tree_) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert calls.count("Thread") == 1, "only the local file server may run on a thread: no monitors"
    assert "journal.read" not in source and ".read_text(encoding=\"utf-8\")" not in source.split("def wait_finished")[1].split("def result")[0]


def test_the_e2e_tool_refuses_to_run_beside_a_real_counter():
    kit = Path("C:/fcc-kit")
    real = [(1, r"C:\Users\x\Downloads\app\runtime\python\pythonw.exe"), (2, r"C:\Windows\explorer.exe"), (3, r"C:\fcc-kit\base\app\runtime\python\python.exe")]
    assert E2E.other_counters(kit, real) == [real[0][1]]


def test_hard_linked_trees_do_not_share_later_changes():
    with tempfile.TemporaryDirectory() as tmp:
        source, target = Path(tmp) / "a", Path(tmp) / "b"
        write_tree(source, {"x/file.txt": b"original"})
        E2E.link_tree(source, target)
        E2E.replace_file(target / "x/file.txt", b"changed")
        assert (source / "x/file.txt").read_bytes() == b"original" and (target / "x/file.txt").read_bytes() == b"changed"


# ---- what the pieces rely on

def test_the_helper_uses_only_the_standard_library():
    tree_ = ast.parse(Path(H.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree_):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


def test_the_helper_runs_alone_from_an_empty_folder():
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copyfile(H.__file__, Path(tmp) / "install_helper.py")
        result = subprocess.run([sys.executable, "-I", "-B", str(Path(tmp) / "install_helper.py"), "recover", str(Path(tmp) / "nothing")], capture_output=True, text=True, cwd=tmp)
        assert result.returncode == H.EXIT_OK, result.stderr


def test_the_helper_comes_from_the_installed_app_and_never_from_the_package():
    source = Path(I.__file__).read_text(encoding="utf-8")
    assert "shutil.copyfile(H.__file__, script)" in source and "STAGED_FOLDER / H.RUNTIME / \"lib\"" not in source


def test_the_two_sides_agree_on_names():
    assert H.ROOT_FILES == Z.ROOT_FILES and H.UPDATE_FOLDER == G.UPDATE_FOLDER and H.STAGED_FOLDER == G.STAGED_FOLDER and H.MARKER_NAME == G.MARKER_NAME
    assert H.SIGNED_FILES == (R.MANIFEST_NAME, R.SIGNATURE_NAME) and H.DOWNLOAD_FOLDER == M2.D.DOWNLOAD_FOLDER


def test_the_launcher_knows_the_helper():
    text = (ROOT / "packaging" / "launcher" / "launcher.c").read_text(encoding="utf-8")
    for fragment in ("\\\\.update\\\\transaction.json", "\\\\.update\\\\helper\\\\python\\\\pythonw.exe", "\\\\.update\\\\old\\\\runtime",
                     f"#define HELPER_BUSY {H.EXIT_BUSY}", f"#define HELPER_STUCK {H.EXIT_STUCK}", "-m install_helper recover"):
        assert fragment in text, fragment


def test_the_app_writes_the_health_report():
    text = (ROOT / "src/fortnite_chest_counter/gui/app.py").read_text(encoding="utf-8")
    assert 'args[0] == "--update-health"' in text and "health.write_report(args[1], args[2])" in text and '"update_health": True' in text
    assert text.index("window.show()", text.index("def main(argv=None)")) < text.index("health.write_report")


def test_the_release_build_lists_its_program_files():
    with tempfile.TemporaryDirectory() as tmp:
        write_tree(tmp, {"python/python.exe": b"x", "lib/a.py": b"y"})
        build_release.write_package_files(Path(tmp))
        listing = json.loads((Path(tmp) / H.PACKAGE_FILES).read_text())
        assert listing["files"] == ["lib/a.py", "python/python.exe"]
    source = (ROOT / "packaging" / "build_release.py").read_text(encoding="utf-8")
    assert source.index("write_package_files(runtime)") < source.index("audit(app_root)\n\n    # ---- 6")


def test_the_same_app_lock_name_is_used_everywhere():
    assert paths.app_mutex_name().startswith("Local\\FortniteVisualChestCounter-App-")
    text = (ROOT / "src/fortnite_chest_counter/gui/app.py").read_text(encoding="utf-8")
    assert "paths.app_mutex_name()" in text and "FortniteVisualChestCounter-App-" not in text


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        started = time.monotonic()
        try:
            fn()
            print(f"  ok    {name}  ({time.monotonic() - started:.1f}s)", flush=True)
        except Exception:
            failed += 1
            import traceback
            print(f"  FAIL  {name}", flush=True)
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} update install checks passed")
    sys.exit(1 if failed else 0)
