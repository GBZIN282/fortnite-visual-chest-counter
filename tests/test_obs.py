"""
OBS integrations (v0.2.1): the WebSocket client and the overlay output link against a fake obs-websocket 5 server
(standard library, in-process), the password store, the new settings, and the projector-window helpers.
Run:   python tests/test_obs.py     (or pytest)
"""
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "src"))   # run without installing

import base64
import contextlib
import re
import hashlib
import json
import socket
import struct
import tempfile
import threading
import time
from pathlib import Path

from fortnite_chest_counter import settings
from fortnite_chest_counter.input import video_sources as sources
from fortnite_chest_counter.obs import client as obs
from fortnite_chest_counter.obs import credentials, link
from fortnite_chest_counter.obs.websocket import _mask, accept_key

PASSWORD = "s3cret-PW"


# ==================================================================
# a fake OBS WebSocket server
# ==================================================================

def _recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError
        data += chunk
    return data


def _read_frame(sock):
    b0, b1 = _recv_exact(sock, 2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", _recv_exact(sock, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", _recv_exact(sock, 8))[0]
    assert b1 & 0x80, "client frames must be masked"
    key = _recv_exact(sock, 4)
    return b0 & 0x0F, _mask(_recv_exact(sock, n), key)


def _write_frame(sock, opcode, payload):
    n = len(payload)
    head = bytes([0x80 | opcode]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536
                                     else bytes([127]) + struct.pack(">Q", n))
    sock.sendall(head + payload)


class FakeObs:
    """Speaks just enough obs-websocket 5. Inputs: name -> {"uuid", "kind", "settings"}."""

    def __init__(self, password=PASSWORD, port=0, greet=True):
        self.password, self.greet = password, greet
        self.inputs = {"Chest Counter": {"uuid": "uuid-1", "kind": "text_gdiplus_v3", "settings": {"text": "old"}},
                       "Game Capture": {"uuid": "uuid-2", "kind": "game_capture", "settings": {}}}
        self.requests, self.connections = [], 0
        self.conn = None
        self.lock = threading.Lock()
        self.server = socket.create_server(("127.0.0.1", port))
        self.port = self.server.getsockname()[1]
        self._open = True
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self._open = False
        try:
            self.server.close()
        except OSError:
            pass
        self.drop(1001)

    def _accept(self):
        while self._open:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def send(self, op, d):
        with self.lock:
            if self.conn is not None:
                _write_frame(self.conn, 0x1, json.dumps({"op": op, "d": d}).encode())

    def emit(self, event_type, data):
        self.send(5, {"eventType": event_type, "eventIntent": 8, "eventData": data})

    def drop(self, code):
        with self.lock:
            conn, self.conn = self.conn, None
        if conn is not None:
            try:
                _write_frame(conn, 0x8, struct.pack(">H", code))
                conn.close()
            except OSError:
                pass

    def _serve(self, conn):
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                head += conn.recv(4096)
            key = next(l.split(":", 1)[1].strip() for l in head.decode().split("\r\n") if l.lower().startswith("sec-websocket-key"))
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Accept: {accept_key(key)}\r\nSec-WebSocket-Protocol: obswebsocket.json\r\n\r\n").encode())
            with self.lock:
                self.conn = conn
            if not self.greet:
                time.sleep(30)
                return
            hello = {"obsWebSocketVersion": "5.6.2", "obsStudioVersion": "33.0.1", "rpcVersion": 1}
            salt, challenge = "c2FsdA==", "Y2hhbGxlbmdl"
            if self.password:
                hello["authentication"] = {"salt": salt, "challenge": challenge}
            self.send(0, hello)
            while True:
                opcode, payload = _read_frame(conn)
                if opcode == 0x8:
                    return
                if opcode != 0x1:
                    continue
                msg = json.loads(payload)
                d = msg["d"]
                if msg["op"] == 1:
                    if self.password and d.get("authentication") != obs.auth_string(self.password, salt, challenge):
                        self.drop(4009)
                        return
                    self.send(2, {"negotiatedRpcVersion": 1})
                elif msg["op"] == 6:
                    self.requests.append((d["requestType"], d.get("requestData")))
                    self.send(7, self._answer(d))
        except (OSError, ConnectionError, ValueError):
            pass

    def _find(self, data):
        for name, item in self.inputs.items():
            if (data.get("inputUuid") and item["uuid"] == data["inputUuid"]) or data.get("inputName") == name:
                return name, item
        return None, None

    def _answer(self, d):
        kind, data = d["requestType"], d.get("requestData") or {}
        ok = {"requestType": kind, "requestId": d["requestId"], "requestStatus": {"result": True, "code": 100}}
        if kind == "GetInputList":
            return {**ok, "responseData": {"inputs": [
                {"inputName": n, "inputUuid": i["uuid"], "inputKind": i["kind"],
                 "unversionedInputKind": i["kind"].rsplit("_v", 1)[0]} for n, i in self.inputs.items()]}}
        name, item = self._find(data)
        if item is None:
            return {**ok, "requestStatus": {"result": False, "code": 600, "comment": "No source was found"}}
        if kind == "GetInputSettings":
            return {**ok, "responseData": {"inputSettings": dict(item["settings"]), "inputKind": item["kind"]}}
        if kind == "SetInputSettings":
            item["settings"].update(data["inputSettings"])
            return ok
        return {**ok, "requestStatus": {"result": False, "code": 204, "comment": "unexpected"}}

    def sets(self):
        return [data for kind, data in self.requests if kind == "SetInputSettings"]


def wait_for(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@contextlib.contextmanager
def raises(kind, match=None):
    try:
        yield
    except kind as error:
        assert match is None or re.search(match, str(error)), f"{error!r} does not match {match!r}"
    else:
        raise AssertionError(f"{kind.__name__} not raised")


@contextlib.contextmanager
def setup(with_server=True):
    """-> (fake OBS or None, a temporary overlay file); quick retries and file checks while it runs."""
    saved = link.BACKOFF_SECONDS, link.POLL_SECONDS
    link.BACKOFF_SECONDS, link.POLL_SECONDS = (0.2,), 0.05
    server = FakeObs() if with_server else None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            yield server, Path(tmp) / "chest_counter.txt"
    finally:
        link.BACKOFF_SECONDS, link.POLL_SECONDS = saved
        if server is not None:
            server.close()


def start_link(server_port, overlay, source="Chest Counter", uuid="", password=PASSWORD):
    l = link.TextOutputLink().start()
    l.configure(True, "127.0.0.1", server_port, password, source, uuid, overlay)
    return l


def state(l):
    return l.status()[1]["state"]


# ==================================================================
# protocol
# ==================================================================

def test_auth_string_is_the_protocol_formula():
    secret = base64.b64encode(hashlib.sha256(b"pw" + b"salt").digest())
    expected = base64.b64encode(hashlib.sha256(secret + b"challenge").digest()).decode()
    assert obs.auth_string("pw", "salt", "challenge") == expected


def test_mask_round_trip_any_size():
    for n in (0, 1, 3, 4, 125, 126, 65535, 65536, 200001):
        data = bytes(range(256)) * (n // 256) + bytes(range(n % 256))
        assert _mask(_mask(data, b"\x01\x02\x03\x04"), b"\x01\x02\x03\x04") == data


def test_client_logs_in_and_lists_only_text_sources():
    with setup() as (server, overlay):
        server.inputs["Big"] = {"uuid": "u-big", "kind": "text_ft2_source_v2", "settings": {}}
        server.inputs["x" * 70000] = {"uuid": "u-long", "kind": "text_gdiplus_v3", "settings": {}}   # > 64 KB answer
        c = obs.ObsClient("127.0.0.1", server.port, PASSWORD).connect()
        try:
            assert c.version_text == "OBS 33.0.1, WebSocket 5.6.2"
            names = [s["name"] for s in obs.list_text_sources(c)]
            assert names == ["Big", "Chest Counter", "x" * 70000]          # Game Capture is not a text source
            assert obs.find_source(obs.list_text_sources(c), "Chest Counter")["kind"] == "text_gdiplus"
        finally:
            c.close()


def test_only_allowed_requests_can_be_sent():
    with setup() as (server, overlay):
        c = obs.ObsClient("127.0.0.1", server.port, PASSWORD).connect()
        try:
            with raises(ValueError):
                c.request("StopStream")
            with raises(ValueError):
                c.request("GetSourceScreenshot")
        finally:
            c.close()
        assert all(kind in obs.ALLOWED_REQUESTS for kind, _ in server.requests)


def test_wrong_or_missing_password_is_a_plain_message():
    with setup() as (server, overlay):
        with raises(obs.ObsAuthFailed, match="did not accept the password"):
            obs.ObsClient("127.0.0.1", server.port, "wrong").connect()
        with raises(obs.ObsAuthFailed, match="asks for a password"):
            obs.ObsClient("127.0.0.1", server.port, "").connect()


def test_no_obs_running_is_unavailable_not_a_crash():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with raises(obs.ObsUnavailable, match="not reachable"):
        obs.ObsClient("127.0.0.1", port, timeout=1.0).connect()


# ==================================================================
# the overlay output link
# ==================================================================

def test_link_mirrors_the_overlay_file_exactly_and_only_the_text():
    with setup() as (server, overlay):
        overlay.write_text("CERTAIN OPENED CHESTS: 1\nAPPROX. OPENED CHESTS: 2\n", encoding="utf-8")
        l = start_link(server.port, overlay)
        try:
            assert wait_for(lambda: server.sets())
            assert server.sets()[0] == {"inputUuid": "uuid-1", "overlay": True,
                                        "inputSettings": {"text": "CERTAIN OPENED CHESTS: 1\nAPPROX. OPENED CHESTS: 2"}}
            assert state(l) == "live"
            overlay.write_text("Chests: 3 • 🎁\n", encoding="utf-8")
            assert wait_for(lambda: server.inputs["Chest Counter"]["settings"]["text"] == "Chests: 3 • 🎁")
            time.sleep(0.3)
            assert len(server.sets()) == 2                                  # unchanged file -> nothing sent again
        finally:
            l.stop()


def test_link_waits_for_obs_then_connects_and_sends_the_current_text():
    with setup(with_server=False) as (server, overlay):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        overlay.write_text("7\n", encoding="utf-8")
        l = start_link(port, overlay)
        try:
            assert wait_for(lambda: state(l) == "waiting")
            t0 = time.perf_counter()
            l.configure(True, "127.0.0.1", port, PASSWORD, "Chest Counter", "", overlay)   # never blocks the window
            l.status()
            assert time.perf_counter() - t0 < 0.05
            later = FakeObs(port=port)                                      # OBS starts
            try:
                assert wait_for(lambda: later.inputs["Chest Counter"]["settings"]["text"] == "7")
                assert state(l) == "live"
            finally:
                later.close()
        finally:
            l.stop()


def test_wrong_password_and_kick_are_not_retried():
    with setup() as (server, overlay):
        overlay.write_text("1\n", encoding="utf-8")
        l = start_link(server.port, overlay, password="wrong")
        try:
            assert wait_for(lambda: state(l) == "password")
            time.sleep(0.6)
            assert server.connections == 1                                  # no retry loop against a wrong password
            l.configure(True, "127.0.0.1", server.port, PASSWORD, "Chest Counter", "", overlay)
            assert wait_for(lambda: state(l) == "live") and wait_for(lambda: server.sets())
            time.sleep(0.2)                     # nothing in flight: a kick mid-request reads as a lost connection
            server.drop(4011)                                               # "Kick" in OBS
            assert wait_for(lambda: state(l) == "kicked")
            before = server.connections
            time.sleep(0.6)
            assert server.connections == before
            l.reconnect()                                                   # the Connect button
            assert wait_for(lambda: state(l) == "live")
        finally:
            l.stop()


def test_lost_connection_reconnects_and_sends_again():
    with setup() as (server, overlay):
        overlay.write_text("5\n", encoding="utf-8")
        l = start_link(server.port, overlay)
        try:
            assert wait_for(lambda: len(server.sets()) == 1)
            server.emit("ExitStarted", {})                                  # OBS is closing ...
            server.drop(1001)
            assert wait_for(lambda: len(server.sets()) == 2, timeout=10)    # ... and back: the text is sent again
            assert server.connections >= 2 and state(l) == "live"
        finally:
            l.stop()


def test_link_follows_a_rename_and_stops_on_a_deleted_source():
    with setup() as (server, overlay):
        overlay.write_text("1\n", encoding="utf-8")
        l = start_link(server.port, overlay)
        try:
            assert wait_for(lambda: state(l) == "live")
            server.inputs["Chest Total"] = server.inputs.pop("Chest Counter")
            server.emit("InputNameChanged", {"inputUuid": "uuid-1", "oldInputName": "Chest Counter", "inputName": "Chest Total"})
            assert wait_for(lambda: l.status()[1]["source"] == "Chest Total")
            overlay.write_text("2\n", encoding="utf-8")
            assert wait_for(lambda: server.inputs["Chest Total"]["settings"]["text"] == "2")
            del server.inputs["Chest Total"]
            server.emit("InputRemoved", {"inputUuid": "uuid-1", "inputName": "Chest Total"})
            assert wait_for(lambda: state(l) == "missing")
            sent = len(server.sets())
            overlay.write_text("3\n", encoding="utf-8")
            time.sleep(0.4)
            assert len(server.sets()) == sent
        finally:
            l.stop()


def test_read_from_file_source_is_only_switched_on_request():
    with setup() as (server, overlay):
        overlay.write_text("9\n", encoding="utf-8")
        server.inputs["Chest Counter"]["settings"] = {"read_from_file": True, "file": str(overlay).replace("\\", "/")}
        l = start_link(server.port, overlay)
        try:
            assert wait_for(lambda: state(l) == "reads_file")
            assert "already shows the counter" in l.status()[1]["message"]
            time.sleep(0.3)
            assert server.sets() == []                                      # never changes the user's source by itself
            l.use_direct_updates()
            assert wait_for(lambda: state(l) == "live")
            assert server.sets()[0]["inputSettings"] == {"read_from_file": False, "text": "9"}
        finally:
            l.stop()


def test_no_source_picked_and_unknown_source():
    with setup() as (server, overlay):
        overlay.write_text("1\n", encoding="utf-8")
        l = start_link(server.port, overlay, source="")
        try:
            assert wait_for(lambda: state(l) == "pick")
            assert [s["name"] for s in l.status()[1]["sources"]] == ["Chest Counter"]
            l.configure(True, "127.0.0.1", server.port, PASSWORD, "Nope", "", overlay)
            assert wait_for(lambda: state(l) == "missing")
            l.configure(True, "127.0.0.1", server.port, PASSWORD, "Chest Counter", "uuid-1", overlay)
            assert wait_for(lambda: state(l) == "live")
            assert server.connections == 1                                  # picking a source never reconnects
            l.configure(False, "127.0.0.1", server.port, PASSWORD, "Chest Counter", "uuid-1", overlay)
            assert wait_for(lambda: state(l) == "off")
        finally:
            l.stop()


def test_a_server_that_never_greets_is_reported_without_blocking():
    with setup(with_server=False) as (server, overlay):
        silent = FakeObs(greet=False)
        overlay.write_text("1\n", encoding="utf-8")
        l = start_link(silent.port, overlay)
        try:
            assert wait_for(lambda: state(l) == "unsupported", timeout=8)
            assert "28 or newer" in l.status()[1]["message"]
        finally:
            l.stop()
            silent.close()


# ==================================================================
# password store, settings, projector window helpers
# ==================================================================

def test_password_lives_in_credential_manager_not_in_files():
    if sys.platform != "win32":
        print("      (skipped: Windows Credential Manager)")
        return
    target = "Fortnite Visual Chest Counter/TEST-" + str(time.time_ns())
    try:
        assert credentials.load_password(target) == ""
        credentials.save_password("pä$$wörd 🎁", target)
        assert credentials.load_password(target) == "pä$$wörd 🎁"
        credentials.save_password("new", target)
        assert credentials.load_password(target) == "new"
    finally:
        credentials.forget_password(target)
    assert credentials.load_password(target) == ""
    credentials.forget_password(target)                                 # forgetting twice is fine


def test_obs_websocket_and_window_settings_are_validated():
    tmp_path = Path(tempfile.mkdtemp())
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[obs_websocket]\nenabled = true\nhost = "192.168.1.50"\nport = 4455\nsource = ""\n'
                        '[live]\nsource = "window"\nwindow = "Windowed Projector (Source) - Game"\n', encoding="utf-8")
    cfg, _, warnings = settings.load_config(cfg_file)
    assert not warnings
    assert cfg["obs_websocket"]["host"] == "192.168.1.50" and cfg["live"]["window"].endswith("- Game")
    cfg_file.write_text('[obs_websocket]\nport = 70000\nhost = "my pc"\n', encoding="utf-8")
    cfg, _, warnings = settings.load_config(cfg_file)
    assert len(warnings) == 2 and cfg["obs_websocket"]["port"] == 4455 and cfg["obs_websocket"]["host"] == "127.0.0.1"
    assert settings.DEFAULTS["obs_websocket"]["enabled"] is False       # off unless the user turns it on


def test_obs_windows_are_listed_projectors_first_without_the_main_window():
    windows = [(1, "OBS Studio 33.0.1 - Profile: Untitled - Scenes: Untitled", "obs64.exe", False),
               (6, "OBS 30.2.3 - Profile: x - Scenes: y", "obs64.exe", False),
               (2, "Settings", "obs64.exe", False),
               (3, "Windowed Projector (Source) - Capture Card", "obs64.exe", True),
               (4, "Windowed Projector (Source) - Capture Card", "notepad.exe", False),
               (5, "Projetor em janela (Fonte) - Jogo", "obs64.exe", False)]
    assert sources.list_obs_windows(windows) == [("Projetor em janela (Fonte) - Jogo", False),
                                                 ("Windowed Projector (Source) - Capture Card", True), ("Settings", False)]
    assert sources.find_window("Windowed Projector (Source) - Capture Card", windows) == 3   # OBS's own window first
    assert sources.find_window("nothing", windows) is None


def test_window_capture_cuts_letterbox_bars_and_hides_the_cursor():
    graph = sources.window_capture_args(123)[-1]
    assert graph.startswith("gfxcapture=hwnd=123:capture_cursor=0:")
    assert "crop=w='min(iw,ih*16/9)':h='min(ih,iw*9/16)'" in graph
    with raises(ValueError, match="window title"):
        sources.make_source("window", 15, window="")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok    {t.__name__}")
        except Exception as error:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL  {t.__name__}: {error!r}")
    print(f"{len(tests) - failed}/{len(tests)} OBS checks passed")
    raise SystemExit(1 if failed else 0)
