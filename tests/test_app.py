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


# ------------------------------------------------------------------ language choice (Settings dropdown)

def test_language_choices_map_to_the_detector_setting_and_back():
    names = [name for name, _ in settings.LANGUAGE_CHOICES]
    assert names == ["English", "Portuguese (Brazil)", "Both (English + Portuguese (Brazil))"]
    for i, (_, langs) in enumerate(settings.LANGUAGE_CHOICES):
        assert settings.language_choice(langs) == i
    assert settings.language_choice(["pt", "en"]) == 2                 # order does not matter
    assert settings.language_choice(settings.DEFAULTS["detector"]["languages"]) == 2   # default unchanged: both


def test_language_choice_is_saved_and_existing_configs_keep_their_language():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        # a v0.1.x config that chose Portuguese only, with comments and other settings
        path.write_text('# my settings\n[detector]\nlanguages = ["pt"]\nprocess_fps = 15\n\n[display]\nshow = "approx"\n',
                        encoding="utf-8")
        cfg, _, warnings = settings.load_config(path)
        assert not warnings and settings.language_choice(cfg["detector"]["languages"]) == 1
        for _, langs in settings.LANGUAGE_CHOICES:                       # what the dropdown writes, read back
            C.update_config_file(path, "detector", {"languages": langs})
            cfg, _, warnings = settings.load_config(path)
            assert not warnings and cfg["detector"]["languages"] == langs
        text = path.read_text(encoding="utf-8")
        assert "# my settings" in text and 'show = "approx"' in text and "process_fps = 15" in text


# ------------------------------------------------------------------ diagnostic capture

def _feed(cap, seconds, fps=15, start_t=100.0):
    """Synthetic frames (a moving bar, cheap to encode) at recording speed, never overrunning the queue."""
    for i in range(int(seconds * fps)):
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[:, (i * 7) % 1280] = 255
        while cap._queue.full():
            time.sleep(0.002)
        cap.offer(start_t + i / fps, frame)


def test_capture_events_mode_keeps_only_the_video_around_decisions_and_marks():
    from fortnite_chest_counter.capture import Capture, read_labels
    from fortnite_chest_counter import review
    with tempfile.TemporaryDirectory() as tmp:
        cap = Capture(tmp, "events", 15, 1280, 720, before=10, after=10, mark_before=30, mark_after=10)
        _feed(cap, 35)                                                  # live t 100 .. 135
        cap.add_events([{"event_id": "E0001", "time": 135.0, "stamp": "02:15.00", "source": "popup",
                         "adjusted_tier": "HIGH", "popup_score": 0.9, "popup_template": "en:CHEST",
                         "certain_counted": True, "approx_counted": True, "reason": "t"}])
        _feed(cap, 35, start_t=135.0)                                   # live t 135 .. 170
        cap.add_mark(160.0, "missed")
        summary = cap.close()
        video = Path(summary["folder"]) / "video"
        kept = sorted(p.name for p in video.glob("seg_*.mkv"))
        # keep windows (recording s): event 35 -> 25..45, mark 60 -> 30..70  =>  segments 20-30 .. 60-70 only
        assert kept == [f"seg_{i:05d}.mkv" for i in range(2, 7)], kept
        clips = json.loads((video / "clips.json").read_text(encoding="utf-8"))
        assert len(clips) == 1 and clips[0]["start"] == 20.0 and clips[0]["end"] == 70.0
        assert summary["frames_not_recorded"] == 0 and summary["events"] == 1 and summary["marks"] == 1
        events = [json.loads(l) for l in (Path(summary["folder"]) / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        assert events[0]["recording_time"] == 35.0 and events[0]["clip_time"] == 15.0
        n = sum(1 for _ in review.frames(Path(summary["folder"]) / clips[0]["file"], 15))
        assert n == 750                                                 # 50 s of the clip, every frame
        labels = (Path(summary["folder"]) / "labels.csv").read_text(encoding="utf-8-sig").splitlines()
        assert labels[0].startswith("kind,id,live_time") and len(labels) == 3 and read_labels(summary["folder"]) == []


def test_capture_session_mode_keeps_everything_and_off_starts_nothing():
    from fortnite_chest_counter.capture import Capture
    with tempfile.TemporaryDirectory() as tmp:
        cap = Capture(tmp, "session", 15, 1280, 720)
        _feed(cap, 22)
        summary = cap.close()
        clips = json.loads((Path(summary["folder"]) / "video" / "clips.json").read_text(encoding="utf-8"))
        assert [c["file"] for c in clips] == ["video/session.ffconcat"] and clips[0]["end"] > 21.9
        cfg = tmp_cfg(tmp)
        assert cfg["capture"]["mode"] == "off" and C._open_capture(cfg, "file", "x", None, None, 15) is None


def test_lossless_capture_replays_the_exact_frames_and_generic_prompts_keep_no_video():
    from fortnite_chest_counter.capture import Capture
    from fortnite_chest_counter import review
    rng = np.random.default_rng(7)
    frames_in = [rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8) for _ in range(3)]
    with tempfile.TemporaryDirectory() as tmp:
        cap = Capture(tmp, "events", 15, 1280, 720, quality="lossless")
        for i in range(45):                                             # 3 s of noise frames
            while cap._queue.full():
                time.sleep(0.002)
            cap.offer(i / 15, frames_in[i % 3])
        cap.add_events([{"event_id": "E0001", "time": 1.0, "source": "interaction_object", "adjusted_tier": "-",
                         "certain_counted": False, "approx_counted": False}])     # generic prompt: no video kept
        assert cap.keep == []
        cap.add_mark(2.0)
        summary = cap.close()
        info = json.loads((Path(summary["folder"]) / "capture.json").read_text(encoding="utf-8"))
        clips = json.loads((Path(summary["folder"]) / "video" / "clips.json").read_text(encoding="utf-8"))
        assert info["codec"] == "FFV1 lossless RGB" and len(clips) == 1
        out = [f for _, f in review.frames(Path(summary["folder"]) / clips[0]["file"], 15)]
        assert len(out) == 45 and all(np.array_equal(out[i], frames_in[i % 3]) for i in range(45))   # bit-exact


def test_capture_never_blocks_counting_even_if_the_encoder_dies():
    from fortnite_chest_counter.capture import Capture
    with tempfile.TemporaryDirectory() as tmp:
        cap = Capture(tmp, "events", 15, 1280, 720)
        cap._encoder.kill()                                             # the encoder vanishes mid-session
        frame = np.zeros((720, 1280, 3), np.uint8)
        t0 = time.monotonic()
        for i in range(200):                                            # far more than the queue holds
            cap.offer(i / 15, frame)
        assert time.monotonic() - t0 < 1.0                              # offer() never waits
        summary = cap.close(timeout=3)
        assert time.monotonic() - t0 < 15 and summary["stopped_early"]


def test_review_scores_live_and_replay_against_the_labels():
    from fortnite_chest_counter import review
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        live = [{"event_id": "E0001", "time": 10.0, "adjusted_tier": "HIGH", "certain_counted": True, "approx_counted": True},
                {"event_id": "E0002", "time": 30.0, "adjusted_tier": "LOW", "certain_counted": False, "approx_counted": False},
                {"event_id": "E0003", "time": 70.0, "adjusted_tier": "MEDIUM", "certain_counted": False, "approx_counted": True}]
        (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in live), encoding="utf-8")
        (folder / "labels.csv").write_text(
            "kind,id,live_time,clip,clip_time,decision,tier,evidence,truth,note\n"
            "event,E0001,00:10.00,,,certain,HIGH,,chest,\n"
            "event,E0002,00:30.00,,,not counted,LOW,,chest,blurry\n"
            "missed,,00:50.00,,,,,,missed_chest,nobody saw it\n"
            "event,E0003,01:10.00,,,approx,MEDIUM,,not_chest,a supply drop\n"
            "missed,,soon,,,,,,chest,bad time is skipped\n", encoding="utf-8-sig")
        replayed = [{"live_time": 10.1, "adjusted_tier": "HIGH", "certain_counted": True, "approx_counted": True},
                    {"live_time": 30.0, "adjusted_tier": "MEDIUM", "certain_counted": False, "approx_counted": True}]
        result = review.compare(folder, replayed)
        assert result["same"] == 1 and len(result["labels"]) == 4
        assert review.score(result["labels"], "live") == {"real": 3, "found_certain": 1, "found_approx": 1,
                                                         "wrongly_counted": 1, "labelled_not_chest": 1}
        assert review.score(result["labels"], "replay") == {"real": 3, "found_certain": 1, "found_approx": 2,
                                                           "wrongly_counted": 0, "labelled_not_chest": 1}
        text = review.report(folder, result, settings.DEFAULTS["detector"])
        assert "<- different" in text and "real chests 3" in text


def test_marks_arrive_through_the_app_control_channel():
    control = C.AppControl(io.StringIO("mark\nmark missed chest\nstop\n"))
    assert control.requested.wait(2)
    assert control.take_marks() == ["mark", "missed chest"] and control.take_marks() == []


def test_live_capture_replays_to_the_same_decisions():
    """End to end on a real recording: live worker with capture -> review replays the clips -> same decisions."""
    if not SAMPLE.exists():
        print("      (skipped: samples/ not present)")
        return
    from fortnite_chest_counter import review
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "config.toml").write_text('[capture]\nmode = "events"\ndir = "captures"\n', encoding="utf-8")
        cmd = [sys.executable, "-m", "fortnite_chest_counter", "live", "--gui", "--source", "file", "--video", str(SAMPLE),
               "--start", "55", "--duration", "28", "--config", str(tmp / "config.toml"),
               "--state", str(tmp / "s.json"), "--obs-dir", str(tmp / "o"), "--log-dir", str(tmp / "l")]
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
        process = subprocess.Popen(cmd, cwd=tmp, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        threading.Timer(12, lambda: (process.stdin.write(b"mark\n"), process.stdin.flush())).start()
        out = process.stdout.read().decode("utf-8", "replace")
        process.wait(timeout=120)
        msgs = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
        saved = next(m for m in msgs if m["type"] == "capture" and m["state"] == "saved")
        assert saved["events"] >= 2 and saved["marks"] == 1 and saved["frames_not_recorded"] == 0, saved
        folder = Path(saved["folder"])
        live = [json.loads(l) for l in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        replayed = review.replay(folder, tmp_cfg(tmp)["detector"])
        result = review.compare(folder, replayed)
        assert result["same"] == len(live), review.report(folder, result, tmp_cfg(tmp)["detector"])


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
