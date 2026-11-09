r"""
Packaged updater validation, ONE scenario per run. Manual and demanding: never part of the normal tests.
See "Checking with a real package" in docs/UPDATER.md.

    Once, on a PC with this repository (keeps a test private key, so it must be outside the repository):
        python tests/update_e2e.py make-kit --base <a folder built by build_release.py> --out C:\fcc-kit

    Then on the test PC, one at a time, with nothing else counting. Nothing needs installing:
        C:\fcc-kit\base\<build>\runtime\python\python.exe C:\fcc-kit\update_e2e.py run healthy

Deliberately light: the kit copies the build once, and each scenario then uses hard links. Nothing watches the journal, and the only
thread is the local file server, which is closed when the scenario ends. Everything stays inside the kit folder.
"""

import argparse
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPOSITORY = HERE.parent
if (_REPOSITORY / "src" / "fortnite_chest_counter").is_dir():
    sys.path.insert(0, str(_REPOSITORY / "src"))

from fortnite_chest_counter.update import install_helper as H       # noqa: E402

PREFIX = "Fortnite-Visual-Chest-Counter-v"
MAX_KIT_PATH = 40                          # runs\<scenario>\<build>\.update\new.partial plus the deepest file must stay under 260 characters
CREATE_NO_WINDOW = 0x08000000
GUI_ANCHOR = "    paths.setup_environment()                     # run from the program folder; bundled ffmpeg first\n"
BROKEN_START = ('    if "--update-health" in sys.argv:\n'
                '        if (paths.APP_DIR / "e2e-damage-data").exists():\n'
                '            (paths.APP_DIR / "state" / "chest_state.json").write_text(\'{"schema": 2, "totals": {"certain": 45}}\\n\')\n'
                '        sys.exit(7)\n')
USER_DATA = {"config.toml": b'[display]\nshow = "both"\n', "state/chest_state.json": b'{"certain": 41, "approximate": 57, "events_logged": 0}\n',
             "state/profiles.json": b'{"version": 1, "active": "default", "profiles": [{"id": "default", "name": "Default", "created_at": null, "source": {}}, '
                                    b'{"id": "streamer", "name": "Streamer", "created_at": null, "source": {"url": "https://twitch.tv/x"}}]}\n',
             "state/profiles/streamer.json": b'{"certain": 9, "approximate": 12}\n', "captures/clip.bin": b"video", "logs/session.jsonl": b"{}\n", "my notes.txt": b"unknown user file"}
CRASH_WRAPPER = """
import json, os, sys
import install_helper as H
c = json.loads(sys.argv[1])
def checkpoint(name):
    if name == c["crash_at"]:
        os._exit(42)
H.checkpoint = checkpoint
sys.exit(H.main(c["argv"]))
"""


def ECC_import(text):
    from Crypto.PublicKey import ECC
    return ECC.import_key(text)


def replace_file(path, data):
    """Breaks any hard link first, so the file this was linked to keeps its content."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    path.write_bytes(data)


def link_tree(source, target):
    """Hard links: no content is written, so there is nothing for antivirus to scan again. The updater only renames and deletes in a
    program folder, and a file that must differ goes through replace_file."""
    for file in Path(source).rglob("*"):
        if file.is_file():
            destination = Path(target) / file.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(file, destination)
            except OSError:
                shutil.copy2(file, destination)


def _compile(path):
    lib = next(p for p in Path(path).parents if p.name == "lib")
    py_compile.compile(str(path), cfile=str(Path(path).parent / "__pycache__" / f"{Path(path).stem}.cpython-{sys.version_info[0]}{sys.version_info[1]}.pyc"),
                       dfile=f"lib\\{Path(path).relative_to(lib)}", doraise=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)


def _set_source(path, text):
    replace_file(path, text.encode("utf-8"))
    _compile(path)


def _write_listing(runtime, version):
    files = sorted(p.relative_to(runtime).as_posix() for p in runtime.rglob("*") if p.is_file() and p.name != H.PACKAGE_FILES)
    replace_file(runtime / H.PACKAGE_FILES, (json.dumps({"format": 1, "version": version, "files": files}, indent=0) + "\n").encode("utf-8"))


def _derive(kit, installed, version, broken, key, sign_package):
    release = kit / "releases" / version
    name = PREFIX + version
    tree = release / "tree" / name
    link_tree(installed, tree)
    lib = tree / "runtime/lib/fortnite_chest_counter"
    _set_source(lib / "version.py", re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', (lib / "version.py").read_text(encoding="utf-8")))
    if broken:
        gui = (lib / "gui/app.py").read_text(encoding="utf-8")
        if GUI_ANCHOR not in gui:
            raise SystemExit("gui/app.py has changed: update GUI_ANCHOR in this tool.")
        _set_source(lib / "gui/app.py", gui.replace(GUI_ANCHOR, GUI_ANCHOR + BROKEN_START, 1))
    _write_listing(tree / "runtime", version)
    launcher = tree / H.ROOT_FILES[0]
    replace_file(launcher, launcher.read_bytes() + version.encode())       # so a replaced launcher can be told from the old one
    zip_path = release / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for file in sorted(p for p in tree.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(f"{name}/{file.relative_to(tree).as_posix()}", (2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            with file.open("rb") as source, z.open(info, "w", force_zip64=True) as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
    sign_package(zip_path, version, [key])
    shutil.rmtree(release / "tree")


def make_kit(base, out, max_path=MAX_KIT_PATH):
    """Everything needed on the test PC. The build is copied once and three small variations of it are packed."""
    base, out = Path(base).resolve(), Path(out).resolve()
    found = re.fullmatch(re.escape(PREFIX) + r"([0-9]+)\.([0-9]+)\.([0-9]+)", base.name)
    if not found:
        raise SystemExit(f"{base.name} is not a build folder.")
    if out.is_relative_to(_REPOSITORY):
        raise SystemExit("The kit holds a test private key, so it must be outside the repository.")
    if len(str(out)) > max_path:
        raise SystemExit(f"Use a path of at most {max_path} characters, or files will not fit under the Windows path limit.")
    if out.exists():
        raise SystemExit(f"{out} already exists.")
    if not (base / "runtime" / "python" / f"python{sys.version_info[0]}{sys.version_info[1]}._pth").exists():
        raise SystemExit("Run this with the same Python version as the build.")
    sys.path.insert(0, str(_REPOSITORY / "packaging"))
    from Crypto.PublicKey import ECC
    import sign_release as S

    installed = out / "base" / base.name
    shutil.copytree(base, installed)
    lib, source = installed / "runtime/lib/fortnite_chest_counter", _REPOSITORY / "src/fortnite_chest_counter"
    for file in source.rglob("*.py"):              # all our code, so a kit made from an older build tests today's program
        if file != source / "version.py":          # the kit keeps the build's own version number
            _set_source(lib / file.relative_to(source), file.read_text(encoding="utf-8"))
    replace_file(installed / "config.example.toml", (_REPOSITORY / "config.example.toml").read_bytes())
    key = ECC.generate(curve="ed25519")
    (out / "test_key.pem").write_text(key.export_key(format="PEM"), encoding="ascii")
    trust = (lib / "update/trust.py").read_text(encoding="utf-8")
    _set_source(lib / "update/trust.py", re.sub(r"(?m)^TRUSTED_PUBLIC_KEYS = .*$", "TRUSTED_PUBLIC_KEYS = " + repr((S.public_key_hex(key),)), trust))
    major, minor, patch = int(found[1]), int(found[2]), int(found[3])
    _write_listing(installed / "runtime", f"{major}.{minor}.{patch}")
    healthy, broken, later = (f"{major}.{minor}.{patch + n}" for n in (1, 2, 3))
    for version, is_broken in ((healthy, False), (broken, True), (later, False)):
        _derive(out, installed, version, is_broken, key, S.sign_package)
    shutil.copy2(__file__, out / "update_e2e.py")
    (out / "kit.json").write_text(json.dumps({"base": base.name, "base_version": f"{major}.{minor}.{patch}", "healthy": healthy, "broken": broken, "next": later}), encoding="utf-8")
    print(f"Kit ready: {out}\nRun one scenario at a time:\n  {installed / 'runtime/python/python.exe'} {out / 'update_e2e.py'} run healthy")


def other_counters(kit, programs):
    """Copies of the real app running outside the kit: a scenario must not run beside a real counting session."""
    prefix = os.path.normcase(str(kit)) + os.sep
    tails = (os.path.normcase("\\runtime\\python\\python.exe"), os.path.normcase("\\runtime\\python\\pythonw.exe"))
    return [path for _, path in programs if os.path.normcase(path).endswith(tails) and not os.path.normcase(path).startswith(prefix)]


class Session:
    def __init__(self, kit, name):
        self.kit, self.info = kit, json.loads((kit / "kit.json").read_text(encoding="utf-8"))
        self.folder = kit / "runs" / name
        self.live = self.folder / self.info["base"]
        self.update_dir = self.live / H.UPDATE_FOLDER
        self.launcher = self.live / H.ROOT_FILES[0]
        self.server = None

    def fresh_install(self):
        self.stop_programs()
        if self.folder.exists():
            shutil.rmtree(self.folder)
        link_tree(self.kit / "base" / self.info["base"], self.live)
        for relative, data in USER_DATA.items():
            replace_file(self.live / relative, data)

    def stop_programs(self):
        for _ in range(100):
            running = H.processes_under([self.folder])
            if not running:
                return
            for pid, _path in running:
                H._terminate(pid)
            time.sleep(0.1)
        raise RuntimeError(f"could not stop {H.processes_under([self.folder])}")

    def serve(self, version):
        self.close_server()
        release = self.kit / "releases" / version
        zip_name = f"{PREFIX}{version}.zip"
        files = {f"/dl/{name}": release / name for name in (zip_name, *H.SIGNED_FILES)}
        owner = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                try:
                    if self.path == "/releases":
                        body = owner["listing"]
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    elif self.path in files:
                        self.send_response(200)
                        self.send_header("Content-Length", str(files[self.path].stat().st_size))
                        self.end_headers()
                        with files[self.path].open("rb") as f:
                            shutil.copyfileobj(f, self.wfile, 1024 * 1024)
                    else:
                        self.send_response(404)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        assets = [{"name": path.name, "size": path.stat().st_size, "state": "uploaded", "browser_download_url": self.url + route, "url": self.url + route} for route, path in files.items()]
        owner["listing"] = json.dumps([{"tag_name": f"v{version}", "name": "test", "body": "test", "draft": False, "prerelease": True, "html_url": self.url, "assets": assets}]).encode()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close_server(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    def close(self):
        self.close_server()
        self.stop_programs()

    def drive(self, mode):
        """check, prepare and begin_install, run by the installed copy's own Python, as the app will."""
        result = subprocess.run([str(self.live / "runtime/python/python.exe"), str(self.kit / "update_e2e.py"), "_drive", self.url, mode], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", cwd=self.live, timeout=900, creationflags=CREATE_NO_WINDOW)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr + self.prepare_log())
        return result.stdout

    def prepare_log(self):
        path = self.update_dir / "prepare.log"
        return "\nprepare.log:\n" + path.read_text(encoding="utf-8") if path.exists() else ""

    def install_log(self):
        path = self.update_dir / H.LOG_NAME
        return path.read_text(encoding="utf-8") if path.exists() else "(no install log)"

    def wait_finished(self, seconds=420):
        """Only asks whether two names exist. It never opens the journal, which is what broke the first real run."""
        result, journal = self.update_dir / H.RESULT_NAME, self.update_dir / H.JOURNAL_NAME
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if result.exists() and not journal.exists():
                return
            time.sleep(0.5)
        raise AssertionError("timed out waiting for the update to finish\n" + self.install_log())

    def result(self):
        return json.loads((self.update_dir / H.RESULT_NAME).read_text(encoding="utf-8"))

    def version(self):
        text = (self.live / "runtime/lib/fortnite_chest_counter/version.py").read_text(encoding="utf-8")
        return re.search(r'__version__ = "([^"]+)"', text).group(1)

    def real_version(self):
        done = subprocess.run([str(self.live / "runtime/python/python.exe"), "-m", "fortnite_chest_counter", "--version"], capture_output=True, text=True, cwd=self.live, timeout=120, creationflags=CREATE_NO_WINDOW)
        return done.stdout + done.stderr

    def app_running(self):
        return any(Path(p).name.lower() == "pythonw.exe" for _, p in H.processes_under([self.live / "runtime"]))

    def wait_app(self, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.app_running():
                return
            time.sleep(0.5)
        raise AssertionError("the app did not open")

    def assert_user_data(self):
        changed = [name for name, data in USER_DATA.items() if (self.live / name).read_bytes() != data]
        assert not changed, f"user data changed: {changed}"

    def crash_helper(self, step):
        helper = self.update_dir / H.HELPER_FOLDER
        code = subprocess.run([str(helper / "python/python.exe"), "-B", "-c", CRASH_WRAPPER, json.dumps({"crash_at": step, "argv": ["install", str(self.live), "0"]})],
                              cwd=helper, timeout=300, creationflags=CREATE_NO_WINDOW).returncode
        assert code == 42, f"the helper did not stop at {step} (exit {code})"

    def run_launcher(self):
        subprocess.run([str(self.launcher)], cwd=self.live, timeout=300)


def scenario_healthy(s):
    from fortnite_chest_counter.update import install as I
    s.fresh_install()
    s.serve(s.info["healthy"])
    old_launcher = s.launcher.read_bytes()
    started = time.perf_counter()
    s.drive("spawn")
    s.wait_finished()
    assert s.result()["outcome"] == "committed", s.result()
    assert s.version() == s.info["healthy"] and s.info["healthy"] in s.real_version(), s.real_version()
    assert s.launcher.read_bytes() != old_launcher, "the launcher was not replaced"
    s.assert_user_data()
    assert s.app_running(), "the new version should be open"
    assert len(list((s.live / "state/backups").glob("before-v*"))) == 1
    s.stop_programs()
    assert I.cleanup_finished(s.live) is True
    return f"committed {s.info['base_version']} to {s.info['healthy']} in {time.perf_counter() - started:.0f} s; real Qt window reported healthy; user data unchanged"


def scenario_failed_start(s):
    s.fresh_install()
    s.serve(s.info["broken"])
    s.drive("spawn")
    s.wait_finished()
    result = s.result()
    assert result["outcome"] == "rolled_back" and "exit code 7" in result["detail"], result
    assert s.version() == s.info["base_version"] and s.info["base_version"] in s.real_version()
    s.assert_user_data()
    s.wait_app()
    return f"rolled back ({result['detail']}); the old version reopened; user data unchanged"


def scenario_damaged_data(s):
    s.fresh_install()
    replace_file(s.live / "e2e-damage-data", b"x")
    s.serve(s.info["broken"])
    s.drive("spawn")
    s.wait_finished()
    result = s.result()
    assert result["outcome"] == "rolled_back" and result["restored"] == ["state/chest_state.json"], result
    s.assert_user_data()
    kept = list((s.live / "state/backups").glob("from-failed-v*/*"))
    assert len(kept) == 1 and b'"schema": 2' in kept[0].read_bytes(), kept
    return f"restored {result['restored']} and kept the newer file as {kept[0].name}"


def scenario_crash_after_swap(s):
    s.fresh_install()
    s.serve(s.info["healthy"])
    s.drive("nospawn")
    s.crash_helper("new_installed")
    assert s.version() == s.info["healthy"], "the new runtime should be in place at the crash"
    s.run_launcher()
    s.wait_finished(120)
    assert s.result()["outcome"] == "rolled_back", s.result()
    assert s.version() == s.info["base_version"]
    s.assert_user_data()
    s.wait_app()
    return "the real launcher restored the old version and opened it; user data unchanged"


def scenario_chained(s):
    first = scenario_healthy(s)
    s.stop_programs()
    (s.update_dir / H.RESULT_NAME).unlink()
    s.serve(s.info["next"])
    s.drive("spawn")
    s.wait_finished()
    assert s.result()["outcome"] == "committed" and s.result()["from"] == s.info["healthy"], s.result()
    assert s.version() == s.info["next"] and s.info["next"] in s.real_version()
    s.assert_user_data()
    return f"{first}; then the updated copy installed {s.info['next']} using its own helper"


SCENARIOS = {"healthy": scenario_healthy, "failed-start": scenario_failed_start, "damaged-data": scenario_damaged_data,
             "crash-after-swap": scenario_crash_after_swap, "chained": scenario_chained}


def drive(url, mode):
    from fortnite_chest_counter.update import check, download, install, prepare, releases
    source = releases.ReleaseSource(url + "/releases", allow_loopback_http=True, timeout=30.0, total_timeout=120.0)
    found = check.check_for_update(source=source)
    print("check:", found.status, found.kind, flush=True)
    if found.status != "available":
        return 2
    prepared = prepare.prepare_update(found.update, source=source, policy=download.BandwidthPolicy("unlimited"))
    print("prepare:", prepared.status, prepared.kind, prepared.message, prepared.detail, flush=True)
    if prepared.status != "ready":
        return 3
    print("begin_install:", install.begin_install(spawn=mode == "spawn"), flush=True)
    return 0


def run(name):
    kit = HERE
    if not (kit / "kit.json").exists():
        print("Run this from inside a kit made with make-kit.")
        return 2
    others = other_counters(kit, H.running_programs())
    if others:
        print("A real copy of the counter is running. Close it first:\n  " + "\n  ".join(others))
        return 2
    session = Session(kit, name)
    try:
        detail, status = SCENARIOS[name](session), "PASS"
    except Exception:
        detail, status = traceback.format_exc() + "\nInstall log:\n" + session.install_log() + session.prepare_log(), "FAIL"
    finally:
        session.close()
    report = f"{status}  {name}\n{detail}\n"
    print(report)
    session.folder.mkdir(parents=True, exist_ok=True)
    (session.folder / "report.txt").write_text(report, encoding="utf-8")
    return 0 if status == "PASS" else 1


def main(argv):
    if argv[:1] == ["_drive"]:
        return drive(argv[1], argv[2])
    if argv[:1] == ["run"] and (len(argv) != 2 or argv[1] not in SCENARIOS):
        print("Name exactly one scenario: " + ", ".join(SCENARIOS))
        return 2
    if argv[:1] == ["run"]:
        return run(argv[1])
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    kit = commands.add_parser("make-kit")
    kit.add_argument("--base", required=True, help="a folder built by packaging/build_release.py")
    kit.add_argument("--out", required=True, help="a new, short folder outside this repository")
    arguments = parser.parse_args(argv)
    make_kit(arguments.base, arguments.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
