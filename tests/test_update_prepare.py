"""
The updater's second layer (v0.2.3): downloading a release, resuming it, unpacking it safely and testing it from staging, against
a mock file server on this PC and synthetic zips. Hostile zips are "validly signed" on purpose: a signature says who built a file,
not that it is safe to unpack.                                            Run:   python tests/test_update_prepare.py   (or pytest)
"""

import sys
from pathlib import Path as _P

ROOT = _P(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))   # run without installing

import contextlib
import errno
import hashlib
import io
import json
import shutil
import socket
import stat
import struct
import tempfile
import threading
import time
import warnings
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from Crypto.PublicKey import ECC

import sign_release as S
from fortnite_chest_counter import paths as app_paths
from fortnite_chest_counter.update import archive as Z
from fortnite_chest_counter.update import authenticity as A
from fortnite_chest_counter.update import check as C
from fortnite_chest_counter.update import download as D
from fortnite_chest_counter.update import prepare as P
from fortnite_chest_counter.update import releases as R
from fortnite_chest_counter.update import staging as G

KEY = ECC.generate(curve="ed25519")
VERSION = "0.2.3"
ROOT_FOLDER = f"Fortnite-Visual-Chest-Counter-v{VERSION}"
PLACEHOLDER_FILES = {"state/README.txt": b"Your counter lives here.\n", "logs/README.txt": b"Session logs.\n",
                     "obs_output/chest_counter.txt": b"CERTAIN OPENED CHESTS: 0\n", "obs_output/last_chest.txt": b"NO CHESTS YET\n"}
BLOB = bytes(range(256)) * 1200            # 307 KB, for the download tests
D.RETRY_DELAY = 0.0                        # no waiting between attempts in this test run


def sha(data):
    return hashlib.sha256(data).hexdigest()


@contextlib.contextmanager
def patched(target, **values):
    saved = {name: getattr(target, name) for name in values}
    for name, value in values.items():
        setattr(target, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(target, name, value)


@contextlib.contextmanager
def workspace():
    """A live program folder with user data, as it would be during an update. -> SimpleNamespace(app, update_dir)."""
    with tempfile.TemporaryDirectory() as tmp:
        app = Path(tmp) / "Fortnite-Visual-Chest-Counter-v0.2.2"
        live = {"config.toml": b"[display]\nshow = \"both\"\n", "state/chest_state.json": b'{"certain": 41, "approximate": 57}\n',
                "state/profiles.json": b'{"version": 1}\n', "state/profiles/streamer.json": b'{"certain": 9}\n',
                "state/profiles/deleted/old-20261101.json": b'{"certain": 2}\n', "state/window.json": b"{}\n",
                "obs_output/chest_counter.txt": b"CERTAIN OPENED CHESTS: 41\n", "logs/session_1.jsonl": b"{}\n",
                "captures/clip.bin": b"video", "runtime/python/python.exe": b"the old python",
                "runtime/lib/fortnite_chest_counter/version.py": b'__version__ = "0.2.2"\n', Z.LAUNCHER: b"the old launcher",
                "README.html": b"old guide"}
        for relative, data in live.items():
            path = app / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        yield SimpleNamespace(app=app, update_dir=app / G.UPDATE_FOLDER)


def snapshot(app):
    """Every file of the live installation, with its content and modification time. `.update` is ours and is left out."""
    return {p.relative_to(app).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(app.rglob("*"))
            if p.is_file() and G.UPDATE_FOLDER not in p.relative_to(app).parts}


# ---- synthetic release packages

def program_files(version=VERSION):
    files = {path: f"program file {path}\n".encode() for path in Z.REQUIRED_FILES}
    files.update({name: f"{name}\n".encode() for name in Z.ROOT_FILES})
    files[Z.VERSION_FILE] = f'__version__ = "{version}"\nRELEASE_CHANNEL = "public beta"\n'.encode()
    files["runtime/python/python313._pth"] = b"python313.zip\n.\n..\\lib\n"
    files["runtime/lib/extra/data.bin"] = bytes(range(256)) * 40
    return files


def build_zip(files=None, placeholders=PLACEHOLDER_FILES, root=ROOT_FOLDER, extra=()):
    """`extra`: (full name, data, optional function to adjust the ZipInfo) written exactly as given."""
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                                       # zipfile warns about duplicate names
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for relative, data in sorted({**(program_files() if files is None else files), **placeholders}.items()):
                z.writestr(f"{root}/{relative}", data)
            for entry in extra:
                name, data, adjust = (*entry, None)[:3]
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                if adjust:
                    adjust(info)
                z.writestr(info, data)
    return buffer.getvalue()


def central_entries(data):
    """{name: offset of its central directory header}."""
    offsets, position = {}, data.find(b"PK\x01\x02")
    while position != -1 and data[position:position + 4] == b"PK\x01\x02":
        name_size, extra_size, comment_size = struct.unpack("<HHH", data[position + 28:position + 34])
        offsets[data[position + 46:position + 46 + name_size]] = position
        position += 46 + name_size + extra_size + comment_size
    return offsets


def patch_central(data, name, offset, layout, value):
    """Change one field of a central directory header, as a hostile zip tool would."""
    position = central_entries(data)[name.encode()] + offset
    return data[:position] + struct.pack(layout, value) + data[position + struct.calcsize(layout):]


def in_runtime(name):
    return f"{ROOT_FOLDER}/runtime/{name}"


def make_update(package, version=VERSION, url="http://127.0.0.1:1", api_route=True, digest=True):
    """A VerifiedUpdate for `package`, through the real signature check with a temporary key."""
    name = R.zip_name(version)
    manifest = A.build_manifest(version, name, sha(package), len(package))
    signature = S.sign_manifest(manifest, [KEY])
    small = R.Asset("small", 1, url + "/small", None, None)
    asset = R.Asset(name, len(package), f"{url}/dl/{name}", f"{url}/api/{name}" if api_route else None, sha(package) if digest else None)
    release = R.Release(R.parse_version(version), f"v{version}", "title", "notes", True, "", asset, small, small)
    return A.verify_release(release, manifest, signature, (0, 2, 2), [S.public_key_hex(KEY)])


class Checks:
    """Stands in for the staged start-up checks. `effect` runs inside them (raise to fail, or change the staged files)."""

    def __init__(self, effect=None):
        self.calls, self.effect = [], effect

    def __call__(self, staged, report_dir, version, cancel):
        self.calls.append((staged, version))
        if self.effect:
            self.effect(staged)


def expect(kind, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except R.UpdateError as error:
        assert error.kind == kind, f"got {error.kind}, wanted {kind}: {error}"
        return error
    raise AssertionError(f"expected an UpdateError of kind {kind}")


def tree(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def plant_download(update_dir, update, package):
    folder = update_dir / D.DOWNLOAD_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / update.manifest.zip
    path.write_bytes(package)
    return path


def stage(ws, package, checks=None, version=VERSION, **options):
    """Stage `package`, signed as a genuine release."""
    update = make_update(package, version)
    path = plant_download(ws.update_dir, update, package)
    return G.stage_package(path, update, ws.update_dir, checks=checks or Checks(), **options)


def assert_rejected(kind, package):
    with workspace() as ws:
        before = snapshot(ws.app)
        checks = Checks()
        expect(kind, stage, ws, package, checks)
        assert checks.calls == [], "the start-up checks ran on a rejected package"
        assert not (ws.update_dir / G.PARTIAL_FOLDER).exists() and not (ws.update_dir / G.STAGED_FOLDER).exists()
        assert snapshot(ws.app) == before


# ---- a mock file server

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        owner = self.server.owner
        owner.requests.append((self.path, self.headers.get("Range")))
        try:
            owner.faults[self.path](self) if self.path in owner.faults else owner.serve(self)
        except OSError:
            pass                               # the client left, which several tests do on purpose


class FileServer:
    """Serves one package with real Range support, or with a chosen misbehaviour (`range_mode`)."""

    def __init__(self, package=BLOB, **options):
        self.package, self.options = package, options
        self.requests, self.faults, self.cut_after, self.stall_after = [], {}, [], []
        self.range_mode = "honor"

    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        self.server.handle_error = lambda *args: None
        self.server.owner = self
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.source = R.ReleaseSource(self.url + "/releases", allow_loopback_http=True, **{"timeout": 2.0, **self.options})
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def update(self, package=None, **options):
        return make_update(BLOB if package is None else package, url=self.url, **options)

    def serve(self, handler):
        body, asked = self.package, handler.headers.get("Range")
        mode = self.range_mode
        if mode == "416" and asked:
            handler.send_response(416)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        start = int(asked.split("=")[1].split("-")[0]) if asked and mode != "ignore" else 0
        payload = body[start:]
        if mode == "always206" or (asked and mode != "ignore"):
            first = start + 1 if mode == "wrong_start" else start
            total = len(body) + 1 if mode == "wrong_total" else len(body)
            handler.send_response(206)
            if mode != "no_header":
                handler.send_header("Content-Range", f"bytes {first}-{len(body) - 1}/{total}")
        else:
            handler.send_response(200)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        cut = self.cut_after.pop(0) if self.cut_after else None
        stall = self.stall_after.pop(0) if self.stall_after else None
        if stall is not None:
            handler.wfile.write(payload[:stall])
            time.sleep(1.0)
        else:
            handler.wfile.write(payload if cut is None else payload[:cut])


def part_of(update_dir, update):
    return update_dir / D.DOWNLOAD_FOLDER / (update.manifest.zip + ".part")


def plant_partial(update_dir, update, data, note=True):
    part = part_of(update_dir, update)
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(data)
    if note:
        part.with_name(part.name + ".json").write_text(json.dumps({"sha256": update.manifest.sha256, "size": update.manifest.size}))
    return part


def fetch(server, ws, update=None, **options):
    return D.download_package(update or server.update(), ws.update_dir, server.source, **options)


# ---- downloading

def test_a_download_ends_as_exactly_the_signed_file():
    with workspace() as ws, FileServer() as server:
        final = fetch(server, ws)
        assert final.read_bytes() == BLOB and final.name == R.zip_name(VERSION)
        assert sorted(p.name for p in final.parent.iterdir()) == [final.name]
        assert server.requests == [(f"/dl/{final.name}", None)]


def test_redirects_are_followed_and_keep_the_resume_range():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        path = f"/dl/{update.manifest.zip}"

        def redirect(handler):
            handler.send_response(302)
            handler.send_header("Location", server.url + "/storage")
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        def storage(handler):
            server.serve(handler)

        server.faults.update({path: redirect, "/storage": storage})
        plant_partial(ws.update_dir, update, BLOB[:100_000])
        assert fetch(server, ws, update).read_bytes() == BLOB
        assert server.requests == [(path, "bytes=100000-"), ("/storage", "bytes=100000-")]


def test_a_redirect_may_not_leave_https():
    with workspace() as ws, FileServer() as server:
        update = server.update()

        def redirect(handler):
            handler.send_response(302)
            handler.send_header("Location", "http://example.com/x")
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        server.faults[f"/dl/{update.manifest.zip}"] = redirect
        expect("bad_redirect", fetch, server, ws, update)


def test_the_second_route_is_used_when_the_first_fails():
    def fail(handler):
        handler.send_response(500)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    with workspace() as ws, FileServer() as server:
        update = server.update()
        server.faults[f"/dl/{update.manifest.zip}"] = fail
        server.faults[f"/api/{update.manifest.zip}"] = lambda handler: server.serve(handler)
        assert fetch(server, ws, update).read_bytes() == BLOB
        assert [path.split("/")[1] for path, _ in server.requests] == ["dl", "api"]


def test_a_connection_cut_mid_download_resumes_by_itself():
    with workspace() as ws, FileServer() as server:
        server.cut_after = [100_000]
        assert fetch(server, ws).read_bytes() == BLOB
        assert [asked for _, asked in server.requests] == [None, "bytes=100000-"]


def test_an_interrupted_download_keeps_its_data_and_resumes_on_the_next_try():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        server.cut_after = [50_000, 0, 0, 0, 0]
        expect("network", fetch, server, ws, update)
        assert part_of(ws.update_dir, update).read_bytes() == BLOB[:50_000]
        assert not (ws.update_dir / D.DOWNLOAD_FOLDER / update.manifest.zip).exists()
        server.requests.clear()
        assert fetch(server, ws, update).read_bytes() == BLOB
        assert [asked for _, asked in server.requests] == ["bytes=50000-"]


def test_a_stalled_connection_times_out_and_resumes():
    with workspace() as ws, FileServer(timeout=0.25) as server:
        server.stall_after = [40_000]
        assert fetch(server, ws).read_bytes() == BLOB
        assert [asked for _, asked in server.requests] == [None, "bytes=40000-"]


def test_a_server_that_ignores_the_range_never_corrupts_the_file():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        server.range_mode = "ignore"
        plant_partial(ws.update_dir, update, BLOB[:100_000])
        final = fetch(server, ws, update)
        assert final.read_bytes() == BLOB and server.requests[0][1] == "bytes=100000-" and len(server.requests) == 1


def test_a_wrong_or_missing_content_range_restarts_cleanly():
    for mode in ("wrong_start", "wrong_total", "no_header", "416"):
        with workspace() as ws, FileServer() as server:
            update = server.update()
            server.range_mode = mode
            plant_partial(ws.update_dir, update, BLOB[:100_000])
            assert fetch(server, ws, update).read_bytes() == BLOB, mode
            assert [asked for _, asked in server.requests] == ["bytes=100000-", None], mode


def test_a_range_answer_nobody_asked_for_is_refused():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        server.range_mode = "always206"
        expect("bad_range", fetch, server, ws, update)
        assert not (ws.update_dir / D.DOWNLOAD_FOLDER / update.manifest.zip).exists()


def test_a_partial_download_must_belong_to_this_signed_release():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        part = plant_partial(ws.update_dir, update, BLOB[:100_000])
        part.with_name(part.name + ".json").write_text(json.dumps({"sha256": sha(b"another release"), "size": len(BLOB)}))
        assert fetch(server, ws, update).read_bytes() == BLOB
        assert [asked for _, asked in server.requests] == [None]
    with workspace() as ws, FileServer() as server:                           # no note at all
        update = server.update()
        plant_partial(ws.update_dir, update, BLOB[:100_000], note=False)
        assert fetch(server, ws, update).read_bytes() == BLOB
        assert [asked for _, asked in server.requests] == [None]
    with workspace() as ws, FileServer() as server:                           # longer than the release can be
        update = server.update()
        plant_partial(ws.update_dir, update, BLOB + b"more")
        assert fetch(server, ws, update).read_bytes() == BLOB
        assert [asked for _, asked in server.requests] == [None]


def test_a_finished_partial_needs_no_network():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        plant_partial(ws.update_dir, update, BLOB)
        assert fetch(server, ws, update).read_bytes() == BLOB and server.requests == []


def test_a_verified_download_is_reused_and_a_damaged_one_is_replaced():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        final = plant_download(ws.update_dir, update, BLOB)
        assert fetch(server, ws, update) == final and server.requests == []
        final.write_bytes(BLOB[:-1] + b"?")
        assert fetch(server, ws, update).read_bytes() == BLOB and len(server.requests) == 1


def test_downloads_of_other_releases_are_removed():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        folder = ws.update_dir / D.DOWNLOAD_FOLDER
        folder.mkdir(parents=True)
        (folder / R.zip_name("0.2.1")).write_bytes(b"old")
        (folder / (R.zip_name("0.2.1") + ".part")).write_bytes(b"old")
        fetch(server, ws, update)
        assert [p.name for p in folder.iterdir()] == [update.manifest.zip]


def test_a_resumed_file_that_fails_its_checksum_restarts_from_zero():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        plant_partial(ws.update_dir, update, b"\x00" * 100_000)               # right size so far, wrong content
        assert fetch(server, ws, update).read_bytes() == BLOB
        assert [asked for _, asked in server.requests] == ["bytes=100000-", None]


def test_a_fresh_download_that_fails_its_checksum_leaves_nothing():
    wrong = BLOB[:-1] + b"?"
    with workspace() as ws, FileServer(package=wrong) as server:
        update = server.update(BLOB)
        expect("mismatch", fetch, server, ws, update)
        assert list((ws.update_dir / D.DOWNLOAD_FOLDER).iterdir()) == [] and len(server.requests) == 1


def test_more_data_than_the_signed_size_is_refused():
    with workspace() as ws, FileServer(package=BLOB + b"x" * 100_000) as server:
        update = server.update(BLOB)
        expect("mismatch", fetch, server, ws, update)
        assert list((ws.update_dir / D.DOWNLOAD_FOLDER).iterdir()) == []


def test_network_failures_end_cleanly():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    source = R.ReleaseSource("http://127.0.0.1/releases", allow_loopback_http=True, timeout=5.0)
    with workspace() as ws:
        expect("network", D.download_package, make_update(BLOB, url=f"http://127.0.0.1:{port}", api_route=False), ws.update_dir, source)


def test_server_errors_end_cleanly_after_a_limited_number_of_tries():
    def fail(handler):
        handler.send_response(503)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    with workspace() as ws, FileServer() as server:
        update = server.update(api_route=False)
        server.faults[f"/dl/{update.manifest.zip}"] = fail
        expect("api_error", fetch, server, ws, update)
        assert len(server.requests) == D.MAX_FAILURES


def test_cancelling_keeps_the_partial_for_a_later_resume():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        cancel = threading.Event()
        expect("cancelled", fetch, server, ws, update, cancel=cancel, on_progress=lambda progress: cancel.set())
        kept = part_of(ws.update_dir, update).stat().st_size
        assert 0 < kept < len(BLOB)
        server.requests.clear()
        assert fetch(server, ws, update).read_bytes() == BLOB
        assert [asked for _, asked in server.requests] == [f"bytes={kept}-"]


def test_cancelling_works_during_a_speed_limit_pause():
    with workspace() as ws, FileServer() as server:
        cancel = threading.Event()
        threading.Timer(0.15, cancel.set).start()
        started = time.monotonic()
        expect("cancelled", fetch, server, ws, cancel=cancel, policy=D.BandwidthPolicy("custom", custom_limit=1000))
        assert time.monotonic() - started < 2.0


def test_not_enough_disk_space_is_refused_before_any_network_use():
    with workspace() as ws, FileServer() as server:
        with patched(shutil, disk_usage=lambda path: SimpleNamespace(free=1000)):
            expect("disk_space", fetch, server, ws)
        assert server.requests == []


def test_a_folder_that_cannot_be_written_is_reported():
    with workspace() as ws, FileServer() as server:
        ws.update_dir.write_bytes(b"a file where the folder should go")
        result = P.prepare_update(server.update(), ws.app, server.source, checks=Checks())
        assert result.status == "failed" and result.kind == "not_writable"


# ---- download speed

def test_the_bandwidth_policy():
    adaptive = D.BandwidthPolicy()
    assert adaptive.mode == "adaptive" and adaptive.limit(True) == D.ADAPTIVE_COUNTING_LIMIT == 1_000_000 and adaptive.limit(False) is None
    unlimited = D.BandwidthPolicy("unlimited")
    assert unlimited.limit(True) is None and unlimited.limit(False) is None
    custom = D.BandwidthPolicy("custom", custom_limit=250_000)
    assert custom.limit(True) == 250_000 and custom.limit(False) == 250_000
    assert D.BandwidthPolicy(counting_limit=500_000).limit(True) == 500_000
    for bad in (dict(mode="fast"), dict(mode="custom"), dict(mode="custom", custom_limit=0), dict(mode="custom", custom_limit=-5),
                dict(mode="custom", custom_limit=True), dict(mode="custom", custom_limit="1")):
        try:
            D.BandwidthPolicy(**bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def timed_fetch(**options):
    with workspace() as ws, FileServer() as server:
        started = time.monotonic()
        fetch(server, ws, **options)
        return time.monotonic() - started


def test_adaptive_slows_down_only_while_counting():
    assert timed_fetch(policy=D.BandwidthPolicy(counting_limit=600_000), is_counting=lambda: False) < 0.4
    assert timed_fetch(policy=D.BandwidthPolicy(counting_limit=600_000), is_counting=lambda: True) >= 0.45


def test_unlimited_and_custom_speeds():
    assert timed_fetch(policy=D.BandwidthPolicy("unlimited"), is_counting=lambda: True) < 0.4
    assert timed_fetch(policy=D.BandwidthPolicy("custom", custom_limit=600_000)) >= 0.45


def test_the_speed_follows_counting_stopping_mid_download():
    counting = [True]

    def progress(update):
        counting[0] = False

    elapsed = timed_fetch(policy=D.BandwidthPolicy(counting_limit=100_000), is_counting=lambda: counting[0], on_progress=progress)
    assert elapsed < 1.5, elapsed                                             # 3 seconds if the limit had stayed on


def test_progress_is_reported_up_to_the_exact_total():
    seen = []
    with workspace() as ws, FileServer() as server:
        fetch(server, ws, on_progress=seen.append, policy=D.BandwidthPolicy("custom", custom_limit=1_500_000))
    received = [p.received for p in seen]
    assert received == sorted(received) and received[-1] == len(BLOB) and all(p.total == len(BLOB) for p in seen)
    assert seen[0].limit == 1_500_000


# ---- staging

def test_a_good_package_is_staged_with_program_files_only():
    with workspace() as ws:
        before = snapshot(ws.app)
        checks = Checks()
        staged = stage(ws, build_zip(), checks)
        assert staged.path == ws.update_dir / G.STAGED_FOLDER and staged.version == VERSION
        assert tree(staged.path) == sorted(program_files())
        assert [version for _, version in checks.calls] == [VERSION]
        assert not (ws.update_dir / G.PARTIAL_FOLDER).exists()
        assert json.loads((ws.update_dir / G.MARKER_NAME).read_text())["version"] == VERSION
        assert snapshot(ws.app) == before


def test_release_placeholders_are_never_unpacked():
    with workspace() as ws:
        staged = stage(ws, build_zip())
        for name in G.USER_OWNED:
            assert not (staged.path / name).exists(), name
        assert (ws.app / "obs_output/chest_counter.txt").read_bytes() == b"CERTAIN OPENED CHESTS: 41\n"


def test_the_zip_must_match_the_signed_manifest_before_anything_is_read():
    package = build_zip()
    with workspace() as ws:
        update = make_update(package)
        path = plant_download(ws.update_dir, update, package[:-1] + bytes([package[-1] ^ 1]))
        checks = Checks()
        with patched(Z, inspect=lambda *args: (_ for _ in ()).throw(AssertionError("the zip was read before its hash matched"))):
            expect("mismatch", G.stage_package, path, update, ws.update_dir, checks=checks)
        assert checks.calls == [] and not (ws.update_dir / G.STAGED_FOLDER).exists()


UNSAFE_NAMES = ("../evil.txt", f"{ROOT_FOLDER}/../../evil.txt", in_runtime("../../evil.txt"), in_runtime("a/../../../evil"), "/abs/evil.txt",
                "C:/Windows/evil.txt", "C:evil.txt", "//server/share/evil.txt", in_runtime("stream.txt:hidden"), in_runtime("nul"),
                in_runtime("NUL.txt"), in_runtime("con.dll"), in_runtime("COM1"), in_runtime("lpt9.log"), in_runtime("trailing."),
                in_runtime("space "), in_runtime("a//b"), in_runtime("./b"), in_runtime("bad|name"), in_runtime("bad?name"),
                in_runtime("bad*name"), in_runtime('bad"name'), in_runtime("bad<name"), in_runtime("control\x01name"))


def test_unsafe_file_names_are_rejected():
    for name in UNSAFE_NAMES:
        assert_rejected("archive_unsafe", build_zip(extra=[(name, b"x")]))


def test_backslash_and_null_names_are_rejected_from_the_raw_zip():
    for tail in ("..\\..\\evil.txt", "null\x00me.txt"):                        # zipfile would clean these if asked to write them
        stand_in = in_runtime("A" * len(tail))
        assert_rejected("archive_unsafe", build_zip(extra=[(stand_in, b"x")]).replace(stand_in.encode(), in_runtime(tail).encode()))


def symlink(info):
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16


def test_links_devices_and_reparse_points_are_rejected():
    def fifo(info):
        info.external_attr = (stat.S_IFIFO | 0o644) << 16

    def block(info):
        info.external_attr = (stat.S_IFBLK | 0o644) << 16

    def directory_type(info):
        info.external_attr = (stat.S_IFDIR | 0o755) << 16

    def reparse(info):
        info.external_attr = 0x400

    for adjust in (symlink, fifo, block, directory_type, reparse):
        assert_rejected("archive_unsafe", build_zip(extra=[(in_runtime("lib/link"), b"C:/Windows", adjust)]))


def test_encrypted_and_unusual_compression_are_rejected():
    name = in_runtime("lib/extra/data.bin")
    package = build_zip()
    assert_rejected("archive_unsafe", patch_central(package, name, 8, "<H", 1))
    assert_rejected("archive_unsafe", patch_central(package, name, 10, "<H", 99))
    assert_rejected("archive_unsafe", patch_central(package, name, 10, "<H", 12))


def test_duplicate_destination_names_are_rejected():
    variants = ((in_runtime("dup.txt"), in_runtime("dup.txt")), (in_runtime("Case.txt"), in_runtime("case.TXT")),
                (in_runtime("caf\u00e9.txt"), in_runtime("cafe\u0301.txt")), (in_runtime("STRASSE"), in_runtime("stra\u00dfe")))
    for first, second in variants:
        assert_rejected("archive_unsafe", build_zip(extra=[(first, b"1"), (second, b"2")]))


def test_a_file_cannot_share_a_name_with_a_folder():
    assert_rejected("archive_unsafe", build_zip(extra=[(in_runtime("thing"), b"file"), (in_runtime("thing/inner.txt"), b"x")]))
    assert_rejected("archive_unsafe", build_zip(extra=[(in_runtime("THING"), b"file"), (in_runtime("thing/inner.txt"), b"x")]))


def test_decompression_limits():
    package = build_zip()
    with patched(Z, MAX_ENTRIES=5):
        assert_rejected("archive_too_large", package)
    with patched(Z, MAX_FILE_SIZE=1000):
        assert_rejected("archive_too_large", package)
    with patched(Z, MAX_TOTAL_SIZE=1000):
        assert_rejected("archive_too_large", package)
    assert_rejected("archive_too_large", build_zip(extra=[(in_runtime("bomb.bin"), b"\x00" * (3 * 1024 * 1024))]))


def test_a_zip_that_lies_about_its_sizes_is_stopped():
    name = in_runtime("lib/extra/data.bin")
    package = build_zip()
    real = program_files()["runtime/lib/extra/data.bin"]
    assert_rejected("archive_invalid", patch_central(package, name, 24, "<I", len(real) // 2))
    assert_rejected("archive_invalid", patch_central(package, name, 24, "<I", len(real) * 2))
    assert_rejected("archive_invalid", patch_central(package, name, 16, "<I", 12345))


def test_damaged_zips_are_rejected():
    for package in (b"this is not a zip", b"PK\x03\x04broken"):
        assert_rejected("archive_invalid", package)
    assert_rejected("archive_layout", b"PK\x05\x06" + b"\x00" * 18)            # a valid zip with nothing in it
    good = build_zip()
    position = good.find(b"program file") if b"program file" in good else 200
    assert_rejected("archive_invalid", good[:position] + bytes([good[position] ^ 0xFF]) + good[position + 1:])


def test_a_package_layout_is_enforced():
    root = ROOT_FOLDER
    for name in (f"{root}/config.toml", f"{root}/CONFIG.TOML", f"{root}/state/chest_state.json", f"{root}/state/profiles.json",
                 f"{root}/state/profiles/x.json", f"{root}/obs_output/sub/x.txt", f"{root}/obs_output/x.json", f"{root}/logs/session.jsonl",
                 f"{root}/captures/clip.mp4", f"{root}/unknown.txt", f"{root}/evil.exe", f"{root}/Runtime/x", "stray.txt",
                 "__MACOSX/x", "Fortnite-Visual-Chest-Counter-v9.9.9/runtime/x"):
        assert_rejected("archive_layout", build_zip(extra=[(name, b"x")]))
    assert_rejected("archive_layout", build_zip(extra=[(in_runtime("folder/"), b"")]))


def test_the_root_folder_must_be_this_version():
    assert_rejected("archive_layout", build_zip(root="Fortnite-Visual-Chest-Counter-v0.2.4"))
    assert_rejected("archive_layout", build_zip(root="something-else"))


def test_every_required_program_file_must_be_present():
    for missing in Z.REQUIRED_FILES:
        assert_rejected("archive_layout", build_zip(files={k: v for k, v in program_files().items() if k != missing}))
    assert_rejected("archive_layout", build_zip(files={k: v for k, v in program_files().items() if not k.endswith("._pth")}))


def test_the_program_inside_must_be_the_signed_version():
    for text in (b'__version__ = "0.2.4"\n', b"nothing here\n", b'__version__ = 3\n'):
        assert_rejected("archive_layout", build_zip(files={**program_files(), Z.VERSION_FILE: text}))
    assert_rejected("archive_layout", build_zip(files={**program_files(), Z.VERSION_FILE: b'__version__ = "0.2.3"\n' + b"#" * Z.MAX_VERSION_FILE}))


def test_a_path_too_long_for_windows_is_refused_with_a_clear_reason():
    with workspace() as ws, patched(G, MAX_WINDOWS_PATH=20):
        expect("path_too_long", stage, ws, build_zip())


def test_not_enough_space_to_unpack_is_refused():
    with workspace() as ws, patched(shutil, disk_usage=lambda path: SimpleNamespace(free=10)):
        expect("disk_space", stage, ws, build_zip())
        assert not (ws.update_dir / G.PARTIAL_FOLDER).exists()


def test_a_disk_failure_while_unpacking_cleans_up():
    def full(*args):
        raise OSError(errno.ENOSPC, "No space left on device")

    with workspace() as ws, patched(Z, extract=full):
        expect("disk_space", stage, ws, build_zip())
        assert not (ws.update_dir / G.PARTIAL_FOLDER).exists() and not (ws.update_dir / G.MARKER_NAME).exists()


def test_a_zip_briefly_held_open_is_still_finished():
    with workspace() as ws, FileServer() as server:
        update = server.update()
        real = A.verify_package

        def held_open_while_checked(path, manifest):
            handle = open(path, "rb")                                         # as a virus scan would: the rename is refused until it closes
            threading.Timer(0.3, handle.close).start()
            real(path, manifest)

        with patched(A, verify_package=held_open_while_checked), patched(D, RENAME_DELAY=0.05):
            final = fetch(server, ws, update)
        assert final.read_bytes() == BLOB


def test_a_folder_briefly_held_open_is_still_moved_into_place():
    def hold_a_file(ws):
        def on_stage(name):
            if name == "validating":
                handle = open(ws.update_dir / G.PARTIAL_FOLDER / Z.VERSION_FILE, "rb")
                threading.Timer(0.3, handle.close).start()
        return on_stage

    with workspace() as ws, patched(D, RENAME_DELAY=0.05):
        staged = stage(ws, build_zip(), on_stage=hold_a_file(ws))
        assert tree(staged.path) == sorted(program_files())


def test_a_lock_that_never_clears_is_reported_with_its_real_cause():
    with workspace() as ws, patched(D, RENAME_TRIES=2, RENAME_DELAY=0.01), patched(G, REMOVE_TRIES=1):
        held = []

        def on_stage(name):
            if name == "validating":
                held.append(open(ws.update_dir / G.PARTIAL_FOLDER / Z.VERSION_FILE, "rb"))

        try:
            error = expect("disk_error", stage, ws, build_zip(), on_stage=on_stage)
        finally:
            for handle in held:
                handle.close()
        assert "moving the unpacked files into place" in error.detail and "PermissionError" in error.detail, error.detail
        assert "PermissionError" not in str(error), "the message is for the user"


def test_a_failure_keeps_its_real_cause_for_the_log():
    def refuse(*args):
        raise OSError(errno.EIO, "the device is not responding", "C:/somewhere/file.bin")

    package = build_zip()
    with workspace() as ws, FileServer(package=package) as server, patched(Z, extract=refuse):
        result = preparation(server, ws)
        assert result.status == "failed" and result.kind == "disk_error"
        assert "unpacking the update" in result.detail and "not responding" in result.detail and "somewhere" in result.detail, result.detail
        assert "not responding" not in result.message
        log = (ws.update_dir / "prepare.log").read_text(encoding="utf-8")
        assert "disk_error" in log and "not responding" in log and "unpacking the update" in log


def test_waiting_for_a_large_rename_is_bounded_and_can_be_cancelled():
    calls = []

    def locked(source, target):
        calls.append(source)
        raise PermissionError(13, "in use")

    def missing(source, target):
        calls.append(source)
        raise FileNotFoundError(2, "gone")

    with patched(D.os, replace=locked), patched(D, RENAME_TRIES=3, RENAME_DELAY=0.0):
        try:
            D.replace_when_free("a", "b", threading.Event())
        except PermissionError:
            assert len(calls) == 3
        else:
            raise AssertionError("it should give up")
    cancel = threading.Event()
    cancel.set()
    with patched(D.os, replace=locked), patched(D, RENAME_TRIES=1000, RENAME_DELAY=30.0):
        started = time.monotonic()
        expect("cancelled", D.replace_when_free, "a", "b", cancel)
        assert time.monotonic() - started < 2.0
    calls.clear()
    with patched(D.os, replace=missing), patched(D, RENAME_TRIES=50, RENAME_DELAY=0.0):
        try:
            D.replace_when_free("a", "b", threading.Event())
        except FileNotFoundError:
            assert len(calls) == 1, "only a lock is worth waiting for"
        else:
            raise AssertionError("it should fail at once")


def test_cancelling_while_unpacking_removes_the_partial_folder():
    with workspace() as ws:
        cancel = threading.Event()
        before = snapshot(ws.app)
        checks = Checks()
        expect("cancelled", stage, ws, build_zip(), checks, cancel=cancel, on_bytes=lambda size: cancel.set())
        assert checks.calls == [] and not (ws.update_dir / G.PARTIAL_FOLDER).exists() and not (ws.update_dir / G.STAGED_FOLDER).exists()
        assert snapshot(ws.app) == before


def test_leftovers_of_an_interrupted_attempt_are_replaced():
    with workspace() as ws:
        junk = ws.update_dir / G.PARTIAL_FOLDER / "half" / "unpacked.bin"
        junk.parent.mkdir(parents=True)
        junk.write_bytes(b"left by a power cut")
        staged = stage(ws, build_zip())
        assert tree(staged.path) == sorted(program_files()) and not junk.exists()


def test_a_ready_package_is_reused_after_checking_every_file():
    package = build_zip()
    with workspace() as ws:
        first = Checks()
        stage(ws, package, first)
        second = Checks()
        assert stage(ws, package, second).version == VERSION and len(first.calls) == 1 and second.calls == []


def corrupted_stage(damage):
    package = build_zip()
    with workspace() as ws:
        staged = stage(ws, package)
        update = make_update(package)
        path = ws.update_dir / D.DOWNLOAD_FOLDER / update.manifest.zip
        assert G.staged_package(ws.update_dir, path, update.manifest) is not None
        damage(staged.path, ws.update_dir)
        assert G.staged_package(ws.update_dir, path, update.manifest) is None
        checks = Checks()
        again = G.stage_package(path, update, ws.update_dir, checks=checks)            # prepared again from the verified zip
        assert tree(again.path) == sorted(program_files()) and len(checks.calls) == 1


def test_damaged_staging_is_detected_and_prepared_again():
    python_file = "runtime/python/python.exe"

    def flip(staged, update_dir):
        data = (staged / python_file).read_bytes()
        (staged / python_file).write_bytes(bytes([data[0] ^ 1]) + data[1:])

    def truncate(staged, update_dir):
        (staged / python_file).write_bytes(b"")

    def delete(staged, update_dir):
        (staged / python_file).unlink()

    def add(staged, update_dir):
        (staged / "runtime" / "planted.dll").write_bytes(b"not from the release")

    def add_user_data(staged, update_dir):
        (staged / "config.toml").write_bytes(b"not from the release")

    def wrong_marker(staged, update_dir):
        marker = update_dir / G.MARKER_NAME
        marker.write_text(json.dumps({**json.loads(marker.read_text()), "sha256": sha(b"another release")}))

    def damaged_marker(staged, update_dir):
        (update_dir / G.MARKER_NAME).write_text("{ not json")

    def no_marker(staged, update_dir):
        (update_dir / G.MARKER_NAME).unlink()

    for damage in (flip, truncate, delete, add, add_user_data, wrong_marker, damaged_marker, no_marker):
        corrupted_stage(damage)


def test_cleanup_only_works_on_the_update_folder():
    with workspace() as ws:
        try:
            G.discard_staging(ws.app)
        except ValueError:
            assert (ws.app / "state" / "chest_state.json").exists()
            return
        raise AssertionError("discard_staging accepted the program folder")


def test_a_start_up_check_may_not_change_the_program_files():
    def plant(staged):
        (staged / "runtime" / "created_by_the_check.txt").write_bytes(b"x")

    def modify(staged):
        (staged / Z.VERSION_FILE).write_bytes(b"changed")

    for effect in (plant, modify):
        with workspace() as ws:
            expect("staging_corrupt", stage, ws, build_zip(), Checks(effect))
            assert not (ws.update_dir / G.STAGED_FOLDER).exists()


def test_files_a_check_creates_in_user_folders_are_removed():
    def write_user_files(staged):
        for relative in ("state/window.json", "state/chest_state.json", "obs_output/chest_counter.txt", "logs/diagnostics.txt", "config.toml"):
            path = staged / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"from the check")

    with workspace() as ws:
        before = snapshot(ws.app)
        staged = stage(ws, build_zip(), Checks(write_user_files))
        assert tree(staged.path) == sorted(program_files()) and snapshot(ws.app) == before


# ---- the real start-up check runner, with stand-in programs

FAKE_PROGRAM = """
import json, sys, time
report, spec = sys.argv[1], json.loads(sys.argv[2])
time.sleep(spec.get("sleep", 0))
if "raw" in spec:
    open(report, "w").write(spec["raw"])
elif "report" in spec:
    open(report, "w").write(json.dumps(spec["report"]))
sys.exit(spec.get("code", 0))
"""


def good_worker(staged):
    return {"report": {"version": VERSION, "app_dir": str(staged), "packaged": True, "missing_templates": [],
                       "ffmpeg": str(staged / "runtime" / "ffmpeg" / "ffmpeg.exe"), "update_keys": 2, "package_files": 4987}}


def good_window(staged):
    return {"report": {"ok": True, "version": VERSION, "packaged": True, "app_dir": str(staged), "update_health": True}}


@contextlib.contextmanager
def checks_folder():
    with workspace() as ws:
        staged = ws.update_dir / G.STAGED_FOLDER
        staged.mkdir(parents=True)
        yield SimpleNamespace(ws=ws, staged=staged, reports=ws.update_dir / G.REPORT_FOLDER)


def run_checks(folder, worker, window, cancel=None, **options):
    def command(spec):
        return lambda staged, report: [sys.executable, "-c", FAKE_PROGRAM, str(report), json.dumps(spec)]

    with patched(G, _worker_check_command=command(worker), _self_test_command=command(window)):
        G.run_staged_checks(folder.staged, folder.reports, VERSION, cancel or threading.Event(), **options)


def changed(spec, **changes):
    return {"report": {**spec["report"], **changes}}


def test_both_start_up_checks_passing():
    with checks_folder() as folder:
        run_checks(folder, good_worker(folder.staged), good_window(folder.staged))


def test_a_failing_program_check_fails_the_update():
    with checks_folder() as folder:
        good = good_worker(folder.staged)
        window = good_window(folder.staged)
        live = str(folder.ws.app)
        for bad in ({**good, "code": 1}, {"code": 0}, {"raw": "{ not json"}, {"raw": "[]"}, changed(good, version="0.2.2"),
                    changed(good, packaged=False), changed(good, missing_templates=["chest.npy"]), changed(good, app_dir=live),
                    changed(good, app_dir=None), changed(good, ffmpeg=live + "\\runtime\\ffmpeg\\ffmpeg.exe"), changed(good, ffmpeg=None),
                    changed(good, update_keys=0), changed(good, update_keys=None)):
            expect("self_test_failed", run_checks, folder, bad, window)


def test_a_failing_window_check_fails_the_update():
    with checks_folder() as folder:
        worker = good_worker(folder.staged)
        good = good_window(folder.staged)
        for bad in ({**good, "code": 1}, {"code": 0}, {"raw": "not json"}, changed(good, ok=False), changed(good, ok="yes"),
                    changed(good, version="0.2.2"), changed(good, packaged=False), changed(good, app_dir=str(folder.ws.app))):
            expect("self_test_failed", run_checks, folder, worker, bad)


def test_the_checks_must_have_run_against_staging_and_not_the_live_folder():
    with checks_folder() as folder:
        live = str(folder.ws.app)
        expect("self_test_failed", run_checks, folder, changed(good_worker(folder.staged), app_dir=live), good_window(folder.staged))
        expect("self_test_failed", run_checks, folder, good_worker(folder.staged), changed(good_window(folder.staged), app_dir=live))


def test_a_new_version_that_could_not_update_itself_is_refused():
    with checks_folder() as folder:
        worker, window = good_worker(folder.staged), good_window(folder.staged)
        for bad in (changed(worker, update_keys=0), changed(worker, package_files=0), changed(worker, package_files=None)):
            expect("self_test_failed", run_checks, folder, bad, window)
        for bad in (changed(window, update_health=False), changed(window, update_health=None)):
            expect("self_test_failed", run_checks, folder, worker, bad)
        run_checks(folder, changed(worker, update_keys=0, package_files=0), changed(window, update_health=False), require_updater=False)


def test_an_old_report_can_never_pass_a_check_that_wrote_nothing():
    with checks_folder() as folder:
        run_checks(folder, good_worker(folder.staged), good_window(folder.staged))
        expect("self_test_failed", run_checks, folder, {"code": 0}, good_window(folder.staged))
        run_checks(folder, good_worker(folder.staged), good_window(folder.staged))
        expect("self_test_failed", run_checks, folder, good_worker(folder.staged), {"code": 0})


def test_a_hanging_check_is_stopped():
    with checks_folder() as folder, patched(G, WORKER_CHECK_TIMEOUT=0.4):
        started = time.monotonic()
        expect("self_test_failed", run_checks, folder, {"sleep": 30}, good_window(folder.staged))
        assert time.monotonic() - started < 10


def test_a_running_check_can_be_cancelled():
    with checks_folder() as folder:
        cancel = threading.Event()
        threading.Timer(0.4, cancel.set).start()
        started = time.monotonic()
        expect("cancelled", run_checks, folder, {"sleep": 30}, good_window(folder.staged), cancel)
        assert time.monotonic() - started < 10


def test_a_check_program_that_cannot_start_fails_the_update():
    with checks_folder() as folder:
        python = folder.staged / "runtime" / "python"
        python.mkdir(parents=True)
        (python / "python.exe").write_bytes(b"this is not a program")
        expect("self_test_failed", G.run_staged_checks, folder.staged, folder.reports, VERSION, threading.Event())


def test_the_real_checks_use_the_staged_python_without_writing_bytecode():
    staged = Path("C:/app/.update/new")
    worker = G._worker_check_command(staged, "r.json")
    window = G._self_test_command(staged, "r.json")
    assert Path(worker[0]) == staged / "runtime/python/python.exe" and Path(window[0]) == staged / "runtime/python/pythonw.exe"
    assert worker[1] == "-B" and window[1] == "-B" and window[2:5] == ["-m", "fortnite_chest_counter.gui", "--self-test"]


# ---- the whole preparation

def preparation(server, ws, **options):
    return P.prepare_update(server.update(server.package), ws.app, server.source, **{"checks": Checks(), **options})


def test_a_full_preparation_leaves_the_live_installation_untouched():
    package = build_zip()
    with workspace() as ws, FileServer(package=package) as server:
        before = snapshot(ws.app)
        seen = []
        result = preparation(server, ws, on_status=lambda **changes: seen.append(changes))
        assert result.status == "ready" and result.staged.version == VERSION and snapshot(ws.app) == before
        assert [c["stage"] for c in seen if "stage" in c] == ["downloading", "verifying", "extracting", "validating", "checking"]


def test_an_update_found_by_the_real_check_can_be_prepared():
    import test_update as M1
    package = build_zip()
    with workspace() as ws, M1.MockGitHub() as github:
        github.add(VERSION, package=package)
        result = C.check_for_update(installed="0.2.2", source=github.source, public_keys=(M1.hex_of(M1.PRIMARY),))
        assert result.status == "available"
        prepared = P.prepare_update(result.update, ws.app, github.source, checks=Checks())
        assert prepared.status == "ready" and tree(prepared.staged.path) == sorted(program_files())


def test_a_rejected_package_is_deleted():
    package = build_zip(extra=[("../evil.txt", b"x")])
    with workspace() as ws, FileServer(package=package) as server:
        before = snapshot(ws.app)
        result = preparation(server, ws)
        assert result.status == "failed" and result.kind == "archive_unsafe" and snapshot(ws.app) == before
        assert list((ws.update_dir / D.DOWNLOAD_FOLDER).iterdir()) == []


def test_a_failed_start_up_check_keeps_the_verified_download_only():
    def fail(staged):
        raise R.UpdateError("self_test_failed", "did not start")

    package = build_zip()
    with workspace() as ws, FileServer(package=package) as server:
        before = snapshot(ws.app)
        result = preparation(server, ws, checks=Checks(fail))
        assert result.status == "failed" and result.kind == "self_test_failed" and snapshot(ws.app) == before
        assert not (ws.update_dir / G.STAGED_FOLDER).exists() and not (ws.update_dir / G.MARKER_NAME).exists()
        assert (ws.update_dir / D.DOWNLOAD_FOLDER / R.zip_name(VERSION)).read_bytes() == package


def test_a_network_failure_keeps_the_partial_download():
    with workspace() as ws, FileServer(package=build_zip()) as server:
        server.cut_after = [500, 0, 0, 0, 0]
        update = server.update(server.package)
        result = P.prepare_update(update, ws.app, server.source, checks=Checks())
        assert result.status == "failed" and result.kind == "network"
        assert part_of(ws.update_dir, update).stat().st_size == 500


def test_cancelling_a_preparation_reports_cancelled():
    with workspace() as ws, FileServer(package=build_zip()) as server:
        cancel = threading.Event()
        cancel.set()
        assert preparation(server, ws, cancel=cancel).status == "cancelled"


def wait_for(job, seconds=20):
    deadline = time.monotonic() + seconds
    while job.result() is None and time.monotonic() < deadline:
        time.sleep(0.005)
    return job.result()


def test_the_preparation_runs_in_the_background():
    package = build_zip()
    with workspace() as ws, FileServer(package=package) as server:
        job = P.Preparation(server.update(package), app_dir=ws.app, source=server.source, checks=Checks(lambda staged: time.sleep(0.3)))
        started = time.monotonic()
        job.start()
        assert time.monotonic() - started < 0.2 and job.result() is None
        result = wait_for(job)
        assert result.status == "ready" and job.status().stage == "finished" and job.status().received == len(package)


def test_a_background_preparation_can_be_cancelled():
    package = build_zip() + b""
    with workspace() as ws, FileServer(package=package) as server:
        job = P.Preparation(server.update(package), app_dir=ws.app, source=server.source, policy=D.BandwidthPolicy("custom", custom_limit=500),
                            checks=Checks())
        job.start()
        time.sleep(0.15)
        started = time.monotonic()
        job.cancel()
        assert wait_for(job).status == "cancelled" and time.monotonic() - started < 2.0


def test_a_bug_in_the_preparation_cannot_escape_the_thread():
    def broken(*args, **kwargs):
        raise RuntimeError("bug")

    with workspace() as ws, patched(P, prepare_update=broken):
        job = P.Preparation(make_update(BLOB), app_dir=ws.app).start()
        result = wait_for(job)
        assert result.status == "failed" and result.kind == "unexpected" and result.staged is None


def test_a_bug_during_staging_still_cleans_up():
    def broken(staged):
        raise RuntimeError("bug")

    with workspace() as ws:
        try:
            stage(ws, build_zip(), Checks(broken))
        except RuntimeError:
            assert not (ws.update_dir / G.STAGED_FOLDER).exists() and not (ws.update_dir / G.MARKER_NAME).exists()
            return
        raise AssertionError("the bug was swallowed")


# ---- the contract with the release build

def test_the_real_release_zip_passes_every_rule():
    zips = sorted(ROOT.glob("build_out/*/Fortnite-Visual-Chest-Counter-v*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        return                                                                 # no local build: nothing to compare with
    newest = zips[-1]
    version = newest.stem.rsplit("-v", 1)[1]
    manifest = A.Manifest(version, newest.name, A.file_sha256(newest), newest.stat().st_size)
    plan = Z.inspect(newest, manifest)
    assert len(plan.files) > 4000 and {f.path.split("/")[0] for f in plan.files} == {"runtime", *Z.ROOT_FILES}
    assert set(plan.placeholders) == {"state/README.txt", "logs/README.txt", "obs_output/certain_chests.txt", "obs_output/approximate_chests.txt",
                                      "obs_output/chest_status.txt", "obs_output/chest_counter.txt", "obs_output/last_chest.txt"}


def test_what_older_updaters_rely_on_still_exists():
    assert callable(app_paths.missing_templates) and callable(app_paths.ffmpeg_executable) and app_paths.PACKAGED in (True, False)
    gui = (ROOT / "src/fortnite_chest_counter/gui/app.py").read_text(encoding="utf-8")
    assert 'args[0] == "--self-test"' in gui and '"ok": False, "version": __version__' in gui and '"app_dir": str(paths.APP_DIR), "packaged"' in gui


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except Exception:
            failed += 1
            import traceback
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} update preparation checks passed")
    sys.exit(1 if failed else 0)
