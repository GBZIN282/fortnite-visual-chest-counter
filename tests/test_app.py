"""
Desktop-app (v0.2.0) checks that need no Qt: the worker protocol, the stop channel, the preview block, the app's count
editing, finding the program folder from the release runtime, and - with the sample recordings present - proof that the
app's worker counts exactly what the command line counts.        Run:   python tests/test_app.py     (or pytest)
"""

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "src"))   # run without installing

import contextlib
import io
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from fortnite_chest_counter import counter as C
from fortnite_chest_counter import paths, settings
from fortnite_chest_counter.console import CONSOLE

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "video tests" / "Fortnite-PS5-Pro-HD-No-Audio.mp4"


def tmp_cfg(tmp):
    tmp = Path(tmp)
    cfg, _, _ = settings.load_config(None, {("state", "path"): str(tmp / "state" / "chest_state.json"),
                                            ("state", "obs_dir"): str(tmp / "obs_output"), ("logging", "dir"): str(tmp / "logs")})
    return cfg


@contextlib.contextmanager
def machine_mode():
    buf = io.StringIO()
    CONSOLE.machine = True
    try:
        with contextlib.redirect_stdout(buf):
            yield buf
    finally:
        CONSOLE.machine = False


def messages(buf):
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


# ------------------------------------------------------------------ worker protocol

def test_machine_mode_turns_every_message_into_one_json_line():
    ev = {"time": 1.0, "source": "fused", "adjusted_tier": "HIGH", "certain_counted": True, "approx_counted": True,
          "popup_score": 0.93, "reason": "popup 0.93 en:CHEST -> HIGH", "event_id": "E0001", "stamp": "00:01.00"}
    with machine_mode() as buf:
        CONSOLE.info("hello")
        CONSOLE.warn("careful")
        CONSOLE.error("broken\nsecond line")
        CONSOLE.line("plain", "bold")
        CONSOLE.status("15 fps", fps=15.0, kind="x")
        CONSOLE.event(ev, "1", "1", 1, 1)
        CONSOLE.emit("counts", certain=1, approx=1, kind="kind is an ordinary field")
    out = messages(buf)
    assert [m["type"] for m in out] == ["info", "warn", "error", "line", "status", "event", "counts"]
    assert out[2]["text"] == "broken\nsecond line"
    assert out[4]["fps"] == 15.0 and out[4]["kind"] == "x"
    assert out[5]["verdict"] == "certain" and out[5]["certain"] == 1 and out[5]["evidence"].startswith("match 0.93")
    assert "\x1b[" not in buf.getvalue()                      # never colour codes in machine mode


def test_machine_mode_sends_rejected_and_generic_events_whatever_the_verbosity():
    CONSOLE.verbosity = "minimal"
    try:
        with machine_mode() as buf:
            CONSOLE.event({"source": "interaction_object", "certain_counted": False, "approx_counted": False}, "0", "0")
            CONSOLE.event({"source": "popup", "popup_score": 0.7, "adjusted_tier": "LOW", "certain_counted": False,
                           "approx_counted": False}, "0", "0")
    finally:
        CONSOLE.verbosity = "normal"
    out = messages(buf)
    assert [(m["verdict"], m["generic"]) for m in out] == [("rejected", True), ("rejected", False)]


def test_text_console_is_unchanged_by_machine_mode_code():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        CONSOLE.emit("counts", certain=1)                       # no-op outside machine mode
        CONSOLE.info("hello")
    assert buf.getvalue() == "hello\n"


def test_session_announces_counts_and_overlay():
    with tempfile.TemporaryDirectory() as tmp, machine_mode() as buf:
        session = C.CounterSession(tmp_cfg(tmp))
        session.apply([{"time": 1.0, "source": "popup", "adjusted_tier": "HIGH", "certain_counted": True,
                        "approx_counted": True, "reason": "t"}], 2.0)
        session.announce()
    out = messages(buf)
    assert out[0]["type"] == "event" and out[0]["certain"] == 1 and out[0]["approx"] == 1
    assert out[-1] == {"type": "counts", "certain": 1, "approx": 1, "certain_text": "1", "approx_text": "1",
                       "overlay": "CERTAIN OPENED CHESTS: 1\nAPPROX. OPENED CHESTS: 1"}


# ------------------------------------------------------------------ stop channel

def test_app_control_stops_on_the_stop_line_and_on_end_of_input():
    stopped = []
    control = C.AppControl(io.StringIO("hello\nstop\n"))
    control.attach(lambda: stopped.append(1))
    assert control.requested.wait(2) and control.reason == "stopped in the app"
    control = C.AppControl(io.StringIO(""))                      # the app vanished: Windows closes the pipe
    assert control.requested.wait(2) and control.reason == "the app closed"
    late = []
    control.attach(lambda: late.append(1))                       # a source created after the request still stops
    assert late == [1]


class _FakeSource:
    """Frames forever until request_stop - like a camera."""
    label = "fake"
    frames_processed = frames_dropped = 0

    def __init__(self):
        self._stop = threading.Event()

    def open(self, timeout=15.0):
        return {"input_resolution": (1280, 720), "input_fps": 30.0}

    def request_stop(self):
        self._stop.set()

    def frames(self):
        t = 0.0
        while not self._stop.is_set():
            t += 1 / 15
            self.frames_processed += 1
            yield t, np.zeros((720, 1280, 3), np.uint8)
            time.sleep(0.005)

    def elapsed(self):
        return 1.0

    def close(self, wait=True):
        pass


def test_gui_worker_runs_live_and_stops_cleanly_on_request():
    from fortnite_chest_counter.input import video_sources as sources
    real_make, real_ff = sources.make_source, paths.ffmpeg_executable
    sources.make_source = lambda *a, **k: _FakeSource()
    paths.ffmpeg_executable = lambda: "ffmpeg"
    read, write = os.pipe()
    stdin = sys.stdin
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sys.stdin = os.fdopen(read, "r")
            threading.Timer(1.5, lambda: os.write(write, b"stop\n")).start()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = C.main(["live", "--gui", "--state", str(Path(tmp) / "s.json"), "--obs-dir", str(Path(tmp) / "o"),
                               "--log-dir", str(Path(tmp) / "l")])
            log = [json.loads(l) for l in next((Path(tmp) / "l").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
    finally:
        sources.make_source, paths.ffmpeg_executable, sys.stdin = real_make, real_ff, stdin
        CONSOLE.machine, paths.HIDE_CHILD_CONSOLES = False, False
        os.close(write)
    out = messages(buf)
    kinds = [m["type"] for m in out]
    assert code == 0 and "connected" in kinds and kinds[-1] == "stopped"
    assert out[-1]["stop_reason"] == "stopped in the app" and out[-1]["frames_processed"] > 10
    assert log[-1]["event"] == "session_end" and log[-1]["stop_reason"] == "stopped in the app"
    assert next(r for r in log if r.get("event") == "session_start")["ui"] == "app"


# ------------------------------------------------------------------ live preview

def test_preview_block_round_trip_and_only_when_wanted():
    from fortnite_chest_counter.preview import PreviewReader, PreviewWriter, block_name
    name = block_name(uuid.uuid4().hex[:12])
    reader = PreviewReader(name)
    writer = PreviewWriter(name, fps=1000)
    frame = np.random.default_rng(1).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    try:
        assert writer.offer(1.0, frame) is False and reader.read() is None          # hidden preview: nothing copied
        reader.set_wanted(True)
        time.sleep(0.002)
        assert writer.offer(2.5, frame) is True
        t, w, h, data = reader.read()
        assert (t, w, h) == (2.5, 640, 360)
        assert np.array_equal(np.frombuffer(data, np.uint8).reshape(360, 640, 3), frame[::2, ::2])
        assert reader.read() is None                                                # the same picture is not returned twice
    finally:
        writer.close()
        reader.close()


# ------------------------------------------------------------------ the app's count editing

def test_set_counts_and_reset_from_the_app():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = tmp_cfg(tmp)
        session = C.set_counts(cfg, 3, 150)
        assert (session.state["certain"], session.state["approximate"]) == (3, 150)
        assert C.load_state(cfg["state"]["path"])["approximate"] == 150
        assert (Path(tmp) / "obs_output" / "chest_counter.txt").read_text(encoding="utf-8") == \
            "CERTAIN OPENED CHESTS: 3\nAPPROX. OPENED CHESTS: 150\n"
        for bad in ((5, 4), (-1, 3), (0, C.MAX_STARTING_COUNT + 1)):
            try:
                C.set_counts(cfg, *bad)
                raise AssertionError(f"accepted {bad}")
            except C.UserError:
                pass
        assert C.load_state(cfg["state"]["path"])["approximate"] == 150             # refused values change nothing
        C.set_counts(cfg, 0, 0, "reset")
        state = C.load_state(cfg["state"]["path"])
        assert (state["certain"], state["approximate"]) == (0, 0)
        actions = [json.loads(l).get("action") for l in next((Path(tmp) / "logs").glob("*.jsonl")).read_text(
            encoding="utf-8").splitlines()]
        assert "set_count" in actions and "reset" in actions


def test_a_running_counter_adopts_the_apps_change():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = tmp_cfg(tmp)
        live = C.CounterSession(cfg)
        live.save()
        time.sleep(0.02)
        C.set_counts(cfg, 0, 40)
        assert live.sync_external_changes() is True and live.state["approximate"] == 40


# ------------------------------------------------------------------ program folder

def test_release_folder_is_found_from_the_runtime_python():
    with tempfile.TemporaryDirectory() as tmp:
        app = Path(tmp) / "My Counter"
        (app / "runtime" / "lib" / "fortnite_chest_counter").mkdir(parents=True)
        (app / "runtime" / "python").mkdir(parents=True)
        assert paths._release_root(app / "runtime" / "python") == app
        assert paths._release_root(Path(tmp) / ".venv" / "Scripts") is None
        assert paths._release_root(app / "runtime") is None


def test_child_process_flags_hide_consoles_only_when_asked_or_windowless():
    before = paths.HIDE_CHILD_CONSOLES
    try:
        paths.HIDE_CHILD_CONSOLES = True
        assert paths.child_process_flags() == (0x08000000 if os.name == "nt" else 0)
    finally:
        paths.HIDE_CHILD_CONSOLES = before


# ------------------------------------------------------------------ same counts as the command line (needs samples/)

def _run_video(args, tmp):
    cmd = [sys.executable, "-m", "fortnite_chest_counter", "video", str(SAMPLE), "--start", "55", "--until", "200",
           "--state", str(tmp / "s.json"), "--obs-dir", str(tmp / "o"), "--log-dir", str(tmp / "l"), *args]
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
    # Like the app: stdin stays OPEN while the worker runs (its end means "the app closed - stop").
    process = subprocess.Popen(cmd, cwd=tmp, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8")
    streams = {}
    readers = [threading.Thread(target=lambda n=n: streams.__setitem__(n, getattr(process, n).read())) for n in ("stdout", "stderr")]
    for r in readers:
        r.start()
    process.wait(timeout=600)
    process.stdin.close()
    for r in readers:
        r.join()
    result = subprocess.CompletedProcess(cmd, process.returncode, streams["stdout"], streams["stderr"])
    rows = [json.loads(l) for l in next((tmp / "l").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
    events = [{k: e.get(k) for k in ("time", "source", "adjusted_tier", "popup_score", "certain_counted", "approx_counted")}
              for e in rows if "time" in e]
    return result, events


def test_app_worker_counts_exactly_what_the_command_line_counts():
    if not SAMPLE.exists():
        print("      (skipped: samples/ not present)")
        return
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        cli, cli_events = _run_video([], Path(a))
        app, app_events = _run_video(["--gui"], Path(b))
    assert cli.returncode == 0 and app.returncode == 0, (cli.stderr, app.stderr)
    assert cli_events and cli_events == app_events
    finished = [json.loads(l) for l in app.stdout.splitlines() if l.startswith("{")][-1]
    assert finished["type"] == "finished"
    assert (finished["certain"], finished["approx"]) == (sum(e["certain_counted"] for e in cli_events),
                                                         sum(e["approx_counted"] for e in cli_events))
    assert "\x1b[" not in app.stdout and all(l.startswith("{") for l in app.stdout.splitlines() if l.strip())


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
    print(f"{len(tests) - failed}/{len(tests)} app checks passed")
    raise SystemExit(1 if failed else 0)
