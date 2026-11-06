"""
Release checks: counting semantics, persistence, reset, OBS files, config, friendly failures.
No video or OBS needed.   Run:   python tests/test_release.py     (also works under pytest)
"""

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "src"))   # run without installing

import contextlib
import io
import json
import os
import random
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fortnite_chest_counter import counter as chest_counter
from fortnite_chest_counter import estimator
from fortnite_chest_counter import paths
from fortnite_chest_counter import settings
from fortnite_chest_counter.settings import DEFAULTS


# ------------------------------------------------------------------ helpers

def tmp_config(tmp, **display):
    """Defaults, but with every user-data path inside `tmp`."""
    tmp = Path(tmp)
    cfg, _, _ = settings.load_config(None, {("state", "path"): str(tmp / "state" / "chest_state.json"),
                                            ("state", "obs_dir"): str(tmp / "obs_output"),
                                            ("logging", "dir"): str(tmp / "logs")})
    cfg["display"].update(display)
    return cfg


def event(certain, approx, t=1.0, source="popup", tier="HIGH"):
    return {"time": t, "source": source, "adjusted_tier": tier, "certain_counted": certain, "approx_counted": approx,
            "reason": "test"}


def run_main(argv):
    """-> (exit code, printed text). Never lets SystemExit escape."""
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = chest_counter.main(argv)
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


def args_for(tmp):
    tmp = Path(tmp)
    return ["--state", str(tmp / "state" / "chest_state.json"), "--obs-dir", str(tmp / "obs_output"),
            "--log-dir", str(tmp / "logs")]


# ------------------------------------------------------------------ 1. counting semantics

def test_certain_implies_approx_sequence():
    with tempfile.TemporaryDirectory() as tmp:
        s = chest_counter.CounterSession(tmp_config(tmp))
        s.apply([event(True, True)], 2.0, quiet=True)
        assert (s.state["certain"], s.state["approximate"]) == (1, 1)
        s.apply([event(False, True)], 4.0, quiet=True)                        # approx-only chest
        assert (s.state["certain"], s.state["approximate"]) == (1, 2)
        s.apply([event(True, True)], 6.0, quiet=True)
        assert (s.state["certain"], s.state["approximate"]) == (2, 3)
        s.apply([event(False, False)], 8.0, quiet=True)                       # not counted at all
        assert (s.state["certain"], s.state["approximate"]) == (2, 3)


def test_certain_always_adds_to_approx_exactly_once_even_if_flag_missing():
    with tempfile.TemporaryDirectory() as tmp:
        s = chest_counter.CounterSession(tmp_config(tmp))
        s.apply([event(True, False)], 2.0, quiet=True)                        # a (buggy) event that forgot approx
        assert (s.state["certain"], s.state["approximate"]) == (1, 1)


def test_approx_never_below_certain_random_sequences():
    rng = random.Random(7)
    with tempfile.TemporaryDirectory() as tmp:
        s = chest_counter.CounterSession(tmp_config(tmp))
        certain = approx_only = 0
        for i in range(500):
            kind = rng.choice(["certain", "approx", "none", "certain_noflag"])
            ev = {"certain": event(True, True), "approx": event(False, True), "none": event(False, False),
                  "certain_noflag": event(True, False)}[kind]
            s.apply([ev], float(i), quiet=True)
            certain += kind in ("certain", "certain_noflag")
            approx_only += kind == "approx"
            assert s.state["approximate"] >= s.state["certain"]
        assert s.state["certain"] == certain and s.state["approximate"] == certain + approx_only


def test_one_chest_merges_into_one_event_and_one_increment():
    """A popup and a prompt for the same chest must merge into ONE event (so approx goes up by exactly 1)."""
    estimator.configure(DEFAULTS["detector"])
    est = estimator.ChestEstimator()
    est.pending_popups.append({"onset": 10.0, "score": 0.95, "y": 0, "x": 0, "template": "en:CHEST"})
    est.pending_interactions.append({"t": 9.0, "score": 0.9, "merged": False})
    events = est._finish(100.0, final=True)
    assert len(events) == 1 and events[0]["source"] == "fused"
    assert events[0]["certain_counted"] and events[0]["approx_counted"]
    with tempfile.TemporaryDirectory() as tmp:
        s = chest_counter.CounterSession(tmp_config(tmp))
        s.apply(events, 100.0, quiet=True)
        assert (s.state["certain"], s.state["approximate"]) == (1, 1)


def test_estimator_flags_respect_the_invariant():
    estimator.configure(DEFAULTS["detector"])
    for score, template in [(0.95, "en:CHEST"), (0.85, "en:CHEST"), (0.77, "en:CHEST"), (0.77, "pt:BAÚ"), (0.60, "en:CHEST")]:
        est = estimator.ChestEstimator()
        est.pending_popups.append({"onset": 10.0, "score": score, "y": 0, "x": 0, "template": template})
        (ev,) = est._finish(100.0, final=True)
        assert ev["approx_counted"] or not ev["certain_counted"], (score, template, ev["reason"])
    est = estimator.ChestEstimator()                                          # MEDIUM English popup: approx only
    est.pending_popups.append({"onset": 10.0, "score": 0.77, "y": 0, "x": 0, "template": "en:CHEST"})
    (ev,) = est._finish(100.0, final=True)
    assert ev["adjusted_tier"] == "MEDIUM" and ev["approx_counted"] and not ev["certain_counted"]


def _medium_popup_with_shooting(template):
    estimator.configure(DEFAULTS["detector"])
    est = estimator.ChestEstimator()
    est.pending_popups.append({"onset": 10.0, "score": 0.78, "y": 0, "x": 0, "template": template})
    est.ammo_steps.extend([9.4, 9.9])                                        # 2 ammo steps around the popup = shooting
    (ev,) = est._finish(100.0, final=True)
    return ev


def test_shooting_does_not_veto_a_specific_english_chest_word():
    ev = _medium_popup_with_shooting("en:CHEST")
    assert ev["shooting_negative"] and ev["adjusted_tier"] == "MEDIUM" and ev["approx_counted"] and not ev["certain_counted"]
    assert "shooting ignored" in ev["reason"]


def test_shooting_still_demotes_the_short_portuguese_word():
    ev = _medium_popup_with_shooting("pt:BAÚ")
    assert ev["shooting_negative"] and ev["adjusted_tier"] == "LOW" and not ev["approx_counted"]


def _medium_popup_with_robust(template, robust):
    estimator.configure(DEFAULTS["detector"])
    est = estimator.ChestEstimator()
    est.pending_popups.append({"onset": 10.0, "score": 0.78, "y": 0, "x": 0, "template": template, "robust": {template: robust}})
    (ev,) = est._finish(100.0, final=True)
    return ev


def test_robust_glyph_match_promotes_medium_to_certain():
    ev = _medium_popup_with_robust("en:CHEST", 0.93)
    assert ev["base_tier"] == "MEDIUM" and ev["adjusted_tier"] == "HIGH" and ev["certain_counted"] and ev["approx_counted"]
    assert "compression-robust" in ev["reason"] and ev["robust_score"] == 0.93


def test_weak_robust_match_does_not_promote():
    ev = _medium_popup_with_robust("en:CHEST", 0.80)
    assert ev["adjusted_tier"] == "MEDIUM" and not ev["certain_counted"] and ev["approx_counted"]
    pt = _medium_popup_with_robust("pt:BAÚ", 0.80)
    assert pt["adjusted_tier"] == "MEDIUM" and not pt["approx_counted"]                  # unchanged v0.1.0 behaviour


def test_robust_score_never_rescues_a_shooting_demoted_short_word():
    estimator.configure(DEFAULTS["detector"])
    est = estimator.ChestEstimator()
    est.pending_popups.append({"onset": 10.0, "score": 0.78, "y": 0, "x": 0, "template": "pt:BAÚ", "robust": {"pt:BAÚ": 0.95}})
    est.ammo_steps.extend([9.4, 9.9])
    (ev,) = est._finish(100.0, final=True)
    assert ev["adjusted_tier"] == "LOW" and not ev["approx_counted"]


def test_robust_correlation_matches_shipped_score_on_binary_input_when_unblurred():
    import numpy as np
    from fortnite_chest_counter.detection import visual as V
    tpl = V.load_templates()[0]["array"]
    rng = np.random.default_rng(1)
    mask = (rng.random((60, 120)) > 0.97).astype(np.float32)                              # 3% random lit pixels
    mask[20:20 + tpl.shape[0], 40:40 + tpl.shape[1]] = tpl                                   # the exact glyph
    padded = np.pad(tpl.astype(np.float64), 2)
    assert abs(V.robust_correlation(mask, padded, 1e-9) - V.best_template_correlation(mask, np.pad(tpl, 2))[0]) < 1e-3
    assert V.robust_correlation(mask, V.blur_template(tpl, 0.6), 0.6) > 0.95


def test_events_carry_temporal_popup_diagnostics():
    ev = _medium_popup_with_shooting("en:CHEST")
    assert set(ev["popup_trace"]) >= {"frames_ge_075", "frames_ge_065", "span_ge_060_s", "top5_mean", "y_std", "x_std"}


def test_snapshots_are_saved_only_when_enabled_and_never_logged_as_pixels():
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        cfg = tmp_config(tmp)
        cfg["logging"]["save_snapshots"] = True
        s = chest_counter.CounterSession(cfg)
        ev = dict(event(False, True), _snapshot=np.full((6, 9, 3), 200, np.uint8))
        s.apply([ev], 2.0, quiet=True)
        pngs = list((Path(tmp) / "logs" / "snapshots").rglob("*.png"))
        assert len(pngs) == 1 and pngs[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        line = s.log.path.read_text(encoding="utf-8")
        assert "_snapshot" not in line and pngs[0].name in line
        off = chest_counter.CounterSession(tmp_config(tmp))                    # default: off
        off.apply([dict(event(False, True), _snapshot=np.zeros((2, 2, 3), np.uint8))], 3.0, quiet=True)
        assert len(list((Path(tmp) / "logs" / "snapshots").rglob("*.png"))) == 1


def test_manual_adjust_keeps_invariant():
    with tempfile.TemporaryDirectory() as tmp:
        base = args_for(tmp)
        code, _ = run_main(["adjust", "--certain", "5"] + base)
        assert code == 0
        state = json.loads((Path(tmp) / "state" / "chest_state.json").read_text(encoding="utf-8"))
        assert state["certain"] == 5 and state["approximate"] >= 5


# ------------------------------------------------------------------ 2. persistence, reset, OBS files

def test_first_run_creates_folders_and_zero_files():
    with tempfile.TemporaryDirectory() as tmp:
        code, text = run_main(["show"] + args_for(tmp))
        assert code == 0, text
        assert (Path(tmp) / "state").is_dir() and (Path(tmp) / "logs").is_dir()
        assert (Path(tmp) / "obs_output" / "certain_chests.txt").read_text(encoding="utf-8") == "CERTAIN OPENED CHESTS: 0\n"
        assert (Path(tmp) / "obs_output" / "approximate_chests.txt").read_text(encoding="utf-8") == "APPROX. OPENED CHESTS: 0\n"
        assert (Path(tmp) / "obs_output" / "chest_status.txt").exists() and (Path(tmp) / "obs_output" / "last_chest.txt").exists()


def test_persistence_across_restart_and_no_reset_on_startup():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = tmp_config(tmp)
        a = chest_counter.CounterSession(cfg)
        a.apply([event(True, True), event(False, True, t=3.0), event(False, True, t=5.0)], 10.0, quiet=True)
        b = chest_counter.CounterSession(cfg)                                  # "restart"
        assert (b.state["certain"], b.state["approximate"]) == (1, 3) and b.loaded_existing
        assert b.state["events_logged"] == 3


def test_reset_command_and_message():
    with tempfile.TemporaryDirectory() as tmp:
        a = chest_counter.CounterSession(tmp_config(tmp))
        a.apply([event(True, True), event(False, True, t=3.0)], 10.0, quiet=True)
        code, text = run_main(["reset"] + args_for(tmp))
        assert code == 0 and "Counter reset:" in text and "CERTAIN: 0" in text and "APPROX: 0" in text
        b = chest_counter.CounterSession(tmp_config(tmp))
        assert (b.state["certain"], b.state["approximate"]) == (0, 0)
        assert (Path(tmp) / "obs_output" / "approximate_chests.txt").read_text(encoding="utf-8") == "APPROX. OPENED CHESTS: 0\n"


def test_live_session_adopts_an_external_reset():
    """`Reset Counter` is a separate program; a running counter must not overwrite it on its next save."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = tmp_config(tmp)
        live = chest_counter.CounterSession(cfg)
        live.apply([event(True, True), event(True, True, t=3.0)], 10.0, quiet=True)
        os.utime(live.state_path, None)
        run_main(["reset"] + args_for(tmp))
        assert live.sync_external_changes() is True
        assert (live.state["certain"], live.state["approximate"]) == (0, 0)
        live.apply([event(False, True)], 20.0, quiet=True)
        assert (live.state["certain"], live.state["approximate"]) == (0, 1)


def test_thousands_separators_in_obs_files():
    with tempfile.TemporaryDirectory() as tmp:
        state = chest_counter.fresh_state()
        state.update(certain=1232, approximate=12500)
        chest_counter.write_obs_files(state, tmp, DEFAULTS["display"])
        assert (Path(tmp) / "certain_chests.txt").read_text(encoding="utf-8") == "CERTAIN OPENED CHESTS: 1,232\n"
        assert (Path(tmp) / "approximate_chests.txt").read_text(encoding="utf-8") == "APPROX. OPENED CHESTS: 12,500\n"


def test_atomic_write_leaves_no_temp_file():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "x.txt"
        chest_counter.atomic_write(target, "hello\n")
        chest_counter.atomic_write(target, "again\n")
        assert target.read_text(encoding="utf-8") == "again\n"
        assert [p.name for p in Path(tmp).iterdir()] == ["x.txt"]


def test_damaged_state_file_is_set_aside_not_fatal():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state" / "chest_state.json"
        state_path.parent.mkdir()
        for bad in ("{not json", '{"certain": "many", "approximate": 3}', "[]", '{"certain": -2, "approximate": 1}'):
            state_path.write_text(bad, encoding="utf-8")
            messages = []
            state = chest_counter.load_state(state_path, warn=messages.append)
            assert (state["certain"], state["approximate"]) == (0, 0) and messages and "damaged" in messages[0]
            assert not state_path.exists()                                     # moved aside, not deleted
            assert list(state_path.parent.glob("chest_state.damaged-*.json"))
            for leftover in state_path.parent.glob("chest_state.damaged-*.json"):
                leftover.unlink()


def test_state_with_approx_below_certain_is_repaired():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.json"
        path.write_text(json.dumps({"certain": 7, "approximate": 3}), encoding="utf-8")
        messages = []
        state = chest_counter.load_state(path, warn=messages.append)
        assert (state["certain"], state["approximate"]) == (7, 7) and messages


# ------------------------------------------------------------------ 3. configuration

def test_default_config_is_valid_and_complete():
    cfg, origin, warnings = settings.load_config(Path(tempfile.gettempdir()) / "nope-not-here" / "x.toml")
    assert cfg == DEFAULTS and origin == "built-in defaults"
    assert cfg["detector"]["languages"] == ["en", "pt"] and cfg["detector"]["process_fps"] == 15


def test_example_config_loads_without_warnings_and_equals_defaults():
    example = Path(__file__).resolve().parent.parent / "config.example.toml"
    cfg, origin, warnings = settings.load_config(example)
    assert warnings == [] and cfg == DEFAULTS


def test_invalid_config_does_not_stop_the_app():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "config.toml"
        bad.write_text("this is [not toml", encoding="utf-8")
        code, text = run_main(["show", "--config", str(bad)] + args_for(tmp))
        assert code == 0 and "WARNING" in text and "Traceback" not in text


# ------------------------------------------------------------------ 4. friendly failures

class _NoCameraSource:
    label = "obs-camera: OBS Virtual Camera"
    info = {"input_resolution": None, "input_fps": None}

    def open(self, timeout=20.0):
        raise RuntimeError("no frames arrived from 'obs-camera: OBS Virtual Camera' (Could not run graph)")

    def close(self):
        pass


def test_missing_obs_camera_gives_friendly_message_not_a_traceback():
    from fortnite_chest_counter.input import video_sources as sources
    real_make, real_list, real_ff = sources.make_source, sources.list_video_devices, paths.ffmpeg_executable
    sources.make_source = lambda *a, **k: _NoCameraSource()
    sources.list_video_devices = lambda: [("Some Webcam", "video")]
    paths.ffmpeg_executable = lambda: "ffmpeg"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run_main(["live"] + args_for(tmp))
    finally:
        sources.make_source, sources.list_video_devices, paths.ffmpeg_executable = real_make, real_list, real_ff
    assert code == 1
    assert "OBS Virtual Camera was not found." in text and "Start Virtual Camera" in text
    assert "Traceback" not in text and "RuntimeError" not in text


def test_camera_present_but_not_started_gives_different_message():
    from fortnite_chest_counter.input import video_sources as sources
    real_make, real_list, real_ff = sources.make_source, sources.list_video_devices, paths.ffmpeg_executable
    sources.make_source = lambda *a, **k: _NoCameraSource()
    sources.list_video_devices = lambda: [("OBS Virtual Camera", "video")]
    paths.ffmpeg_executable = lambda: "ffmpeg"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run_main(["live"] + args_for(tmp))
    finally:
        sources.make_source, sources.list_video_devices, paths.ffmpeg_executable = real_make, real_list, real_ff
    assert code == 1 and "not sending video" in text and "Traceback" not in text


def test_missing_ffmpeg_and_templates_are_explained():
    real_ff, real_missing = paths.ffmpeg_executable, paths.missing_templates
    try:
        paths.ffmpeg_executable = lambda: None
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run_main(["live"] + args_for(tmp))
        assert code == 1 and "ffmpeg" in text and "Traceback" not in text
        paths.ffmpeg_executable = real_ff
        paths.missing_templates = lambda: [Path("chest.npy")]
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run_main(["live"] + args_for(tmp))
        assert code == 1 and "incomplete" in text and "Traceback" not in text
    finally:
        paths.ffmpeg_executable, paths.missing_templates = real_ff, real_missing


def test_unexpected_bug_writes_crash_file_and_reassures():
    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                chest_counter.report_crash(ValueError("boom"))
            assert "counter is safe" in buf.getvalue()
            assert list((Path(tmp) / "logs").glob("crash_*.txt"))
        finally:
            os.chdir(here)


def test_video_command_missing_file_is_friendly():
    with tempfile.TemporaryDirectory() as tmp:
        code, text = run_main(["video", str(Path(tmp) / "nope.mp4")] + args_for(tmp))
    assert code == 1 and "Video file not found" in text and "Traceback" not in text


def test_version_flag():
    code, text = run_main(["--version"])
    from fortnite_chest_counter.version import __version__
    assert code == 0 and f"v{__version__}" in text


def _hold_lock_in_child(state):
    """Start a separate process that takes the counter lock and keeps it; returns the process once it holds it."""
    import subprocess
    import time as _time
    src = str(Path(__file__).resolve().parent.parent / "src")
    code = ("import sys, time; sys.path.insert(0, %r)\n"
            "from fortnite_chest_counter import counter as c\n"
            "c.SingleInstance(%r).__enter__(); print('held', flush=True); time.sleep(60)") % (src, str(state))
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
    assert child.stdout.readline().strip() == b"held"
    _time.sleep(0.2)
    return child


def _hard_kill(proc):
    """TerminateProcess on the whole tree (a venv python.exe is a launcher with the real interpreter as its child)."""
    import subprocess
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    proc.wait()


def test_single_instance_lock_is_released_on_exit_and_cleans_v010_leftovers():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "chest_state.json"
        state.with_name("live.lock").write_text("6096")                      # a stale v0.1.0 lock file
        state.with_name("chest_state.json.tmp").write_text("{half")          # a save Windows killed half-way
        with chest_counter.SingleInstance(state):
            assert chest_counter.counter_is_running(state)
            assert not state.with_name("live.lock").exists() and not state.with_name("chest_state.json.tmp").exists()
        assert not chest_counter.counter_is_running(state)
        with chest_counter.SingleInstance(state):                            # can be taken again
            pass


def test_lock_held_by_a_running_counter_is_respected():
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "chest_state.json"
        twin = _hold_lock_in_child(state)
        try:
            try:
                with chest_counter.SingleInstance(state):
                    raise AssertionError("a second counter was allowed to start")
            except chest_counter.UserError as error:
                assert "already running" in str(error)
        finally:
            _hard_kill(twin)


def test_hard_killed_counter_never_blocks_the_next_start():
    """No cleanup at all (TerminateProcess, like Task Manager or Windows giving up): the kernel frees the lock."""
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "chest_state.json"
        twin = _hold_lock_in_child(state)
        assert chest_counter.counter_is_running(state)
        _hard_kill(twin)
        assert not chest_counter.counter_is_running(state)
        with chest_counter.SingleInstance(state):
            pass


def test_a_different_counter_file_is_a_different_lock():
    with tempfile.TemporaryDirectory() as tmp:
        with chest_counter.SingleInstance(Path(tmp) / "a" / "chest_state.json"):
            with chest_counter.SingleInstance(Path(tmp) / "b" / "chest_state.json"):
                pass


def test_console_close_is_a_clean_stop():
    """Windows sends CTRL_CLOSE when the window's X is clicked; CTRL_BREAK goes through the same handler and can be sent
    from a test. Expect: session_end logged, lock removed, no half-written save left behind."""
    import shutil
    import signal
    import subprocess
    import time as _time
    ffmpeg = paths.ffmpeg_executable()
    if not ffmpeg:
        print("      (skipped: ffmpeg not available)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        video = tmp / "black.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30", "-t", "40",
                        "-c:v", "mpeg4", str(video)], check=True)
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent / "src"))
        child = subprocess.Popen([sys.executable, "-m", "fortnite_chest_counter", "live", "--source", "file", "--video", str(video),
                                  *args_for(tmp)], cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            state_file = tmp / "state" / "chest_state.json"
            deadline = _time.time() + 40
            while _time.time() < deadline and not (chest_counter.counter_is_running(state_file) and list((tmp / "logs").glob("session_*.jsonl"))):
                _time.sleep(0.3)
            _time.sleep(4)                                                      # let it count for a moment
            assert chest_counter.counter_is_running(state_file), "counter did not start"
            child.send_signal(signal.CTRL_BREAK_EVENT)
            child.wait(timeout=20)
        finally:
            if child.poll() is None:
                child.kill()
        log = next((tmp / "logs").glob("session_*.jsonl")).read_text(encoding="utf-8")
        end = [json.loads(l) for l in log.splitlines() if '"session_end"' in l]
        assert end and end[0]["stop_reason"] == "Ctrl+Break", log[-400:]          # same handler as the X
        assert not chest_counter.counter_is_running(tmp / "state" / "chest_state.json"), "lock left behind"
        assert not list((tmp / "state").glob("*.tmp")), "half-written save left behind"
        assert json.loads((tmp / "state" / "chest_state.json").read_text(encoding="utf-8"))["certain"] == 0


# ------------------------------------------------------------------ 5. customisable overlay text (v0.1.1)

def _obs_files(tmp, display_overrides, certain=20, approx=231):
    display = dict(DEFAULTS["display"], **display_overrides)
    state = chest_counter.fresh_state()
    state.update(certain=certain, approximate=approx)
    chest_counter.write_obs_files(state, tmp, display)
    return {p.name: p.read_text(encoding="utf-8") for p in Path(tmp).glob("*.txt")}


def test_default_overlay_files_are_unchanged_from_v010_plus_one_new_file():
    with tempfile.TemporaryDirectory() as tmp:
        files = _obs_files(tmp, {}, 1232, 1247)
    assert files["certain_chests.txt"] == "CERTAIN OPENED CHESTS: 1,232\n"
    assert files["approximate_chests.txt"] == "APPROX. OPENED CHESTS: 1,247\n"
    assert files["chest_status.txt"] == "1,232 certain • ~1,247 estimated\n"
    assert files["chest_counter.txt"] == "CERTAIN OPENED CHESTS: 1,232\nAPPROX. OPENED CHESTS: 1,247\n"
    assert set(files) == {"certain_chests.txt", "approximate_chests.txt", "chest_status.txt", "chest_counter.txt", "last_chest.txt"}


def test_show_modes_for_the_single_overlay_file():
    with tempfile.TemporaryDirectory() as tmp:
        assert _obs_files(tmp, {"show": "approx"})["chest_counter.txt"] == "APPROX. OPENED CHESTS: 231\n"
        assert _obs_files(tmp, {"show": "certain"})["chest_counter.txt"] == "CERTAIN OPENED CHESTS: 20\n"
        assert _obs_files(tmp, {"show": "both"})["chest_counter.txt"].count("\n") == 2


def test_custom_wording_placeholders_unicode_braces_and_new_lines():
    custom = {"approx_text": "Chest Hunt: {count}/500 🏆", "certain_text": "Confirmed {count} of ~{approx} ({certain})",
              "combined_status_format": "{{chests}} {approx}", "show": "both"}
    with tempfile.TemporaryDirectory() as tmp:
        files = _obs_files(tmp, custom, 20, 1231)
        assert files["approximate_chests.txt"] == "Chest Hunt: 1,231/500 🏆\n"
        assert files["certain_chests.txt"] == "Confirmed 20 of ~1,231 (20)\n"
        assert files["chest_status.txt"] == "{chests} 1,231\n"
        two_lines = _obs_files(tmp, {"approx_text": "Chests\n{count}", "show": "approx"})["chest_counter.txt"]
        assert two_lines == "Chests\n231\n"


def test_bad_wording_in_config_warns_and_falls_back():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.toml"
        p.write_text('[display]\napprox_text = "Total {chests}"\ncertain_text = "Oops {"\nshow = "everything"\n'
                     '[console]\nverbosity = "loud"\ncolors = "yes"\n', encoding="utf-8")
        cfg, _, warnings = settings.load_config(p)
    text = "\n".join(warnings)
    for key in ("approx_text", "certain_text", "show", "verbosity", "colors"):
        assert key in text, key
    assert cfg["display"] == DEFAULTS["display"] and cfg["console"] == DEFAULTS["console"]


def test_config_saved_with_a_utf8_bom_still_works():
    """Notepad ("UTF-8 with BOM") and PowerShell's Set-Content -Encoding utf8 put an invisible BOM at the start."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.toml"
        p.write_bytes(b"\xef\xbb\xbf" + '[display]\nshow = "approx"\napprox_text = "Chest Hunt: {count}/500 🏆"\n'.encode("utf-8"))
        cfg, origin, warnings = settings.load_config(p)
    assert warnings == [] and cfg["display"]["show"] == "approx" and cfg["display"]["approx_text"].startswith("Chest Hunt")


def test_a_broken_template_at_runtime_never_crashes_the_counter():
    with tempfile.TemporaryDirectory() as tmp:
        files = _obs_files(tmp, {"approx_text": "{nope}", "certain_text": "{", "combined_status_format": "{0}"})
    assert files["approximate_chests.txt"] == "APPROX. OPENED CHESTS: 231\n"            # defaults used instead
    assert files["certain_chests.txt"] == "CERTAIN OPENED CHESTS: 20\n"


def test_v010_config_labels_still_change_the_overlay():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "config.toml"
        p.write_text('[display]\ncertain_label = "CONFIRMED {wow}"\n', encoding="utf-8")
        cfg, _, warnings = settings.load_config(p)
        assert warnings == [] and cfg["display"]["certain_text"] == "CONFIRMED {{wow}}: {count}"
        assert _obs_files(tmp, cfg["display"], 5, 9)["certain_chests.txt"] == "CONFIRMED {wow}: 5\n"
        p.write_text('[display]\ncertain_label = "OLD"\ncertain_text = "NEW {count}"\n', encoding="utf-8")
        cfg, _, _ = settings.load_config(p)
        assert cfg["display"]["certain_text"] == "NEW {count}"                         # the new key wins


def test_show_command_uses_the_custom_wording():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.toml"
        cfg.write_text('[display]\napprox_text = "My Chest Hunt: {count}"\n', encoding="utf-8")
        code, text = run_main(["show", "--config", str(cfg)] + args_for(tmp))
    assert code == 0 and "My Chest Hunt: 0" in text


# ------------------------------------------------------------------ 6. readable console (v0.1.1)

def _console(verbosity, colors=False):
    from fortnite_chest_counter.console import Console
    c = Console()
    c.verbosity, c.colors = verbosity, colors
    return c


def _printed(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


EV_CERTAIN = {"certain_counted": True, "approx_counted": True, "source": "popup", "popup_score": 0.94,
              "adjusted_tier": "HIGH", "reason": "popup 0.94 en:CHEST -> HIGH", "event_id": "E0001", "stamp": "01:02.00"}
EV_APPROX = dict(EV_CERTAIN, certain_counted=False, popup_score=0.78, adjusted_tier="MEDIUM",
                 reason="popup 0.78 en:CHEST -> MEDIUM; MEDIUM counted approx: en:CHEST word is reliable")
EV_REJECT = dict(EV_CERTAIN, certain_counted=False, approx_counted=False, popup_score=0.77, adjusted_tier="LOW",
                 shooting_negative=True, reason="popup 0.77 pt -> MEDIUM; adjusted to LOW (shooting=True, interaction=False)")
EV_PROMPT_REJECT = {"certain_counted": False, "approx_counted": False, "source": "interaction_object",
                    "interaction_score": 0.75, "adjusted_tier": "-", "reason": "prompt 0.75 but no chest-like object"}


def test_console_lines_are_readable_without_colours():
    out = _printed(lambda: [_console("normal").event(e, "20", "231") for e in (EV_CERTAIN, EV_APPROX, EV_REJECT)])
    lines = out.splitlines()
    assert "\x1b[" not in out and len(lines) == 3
    assert "[CERTAIN]" in lines[0] and "chest +1" in lines[0] and "match 0.94 (HIGH)" in lines[0]
    assert "[APPROX ]" in lines[1] and "chest ~+1" in lines[1]
    assert "[REJECT ]" in lines[2] and "not counted" in lines[2] and "shooting" in lines[2]
    assert "CERTAIN   20 | APPROX  231" in lines[0]
    assert max(len(l) for l in lines) < 120                                       # never wraps in a 120-column window
    assert "%" not in out and "confidence" not in out.lower()                      # scores are not probabilities


def test_console_colours_use_one_meaning_per_colour():
    c = _console("normal", colors=True)
    green, yellow, red = (_printed(lambda e=e: c.event(e, "1", "2")) for e in (EV_CERTAIN, EV_APPROX, EV_REJECT))
    assert "\x1b[92m" in green and "\x1b[93m" in yellow and "\x1b[91m" in red
    err = _printed(lambda: c.error("Could not open the video device\nhint"))
    assert "\x1b[97;41m" in err and "hint" in err                                    # errors look different from rejections


def test_console_verbosity_levels():
    events = (EV_CERTAIN, EV_APPROX, EV_REJECT, EV_PROMPT_REJECT)
    minimal = _printed(lambda: [_console("minimal").event(e, "1", "2") for e in events])
    normal = _printed(lambda: [_console("normal").event(e, "1", "2") for e in events])
    debug = _printed(lambda: [_console("debug").event(e, "1", "2") for e in events])
    assert "[REJECT ]" not in minimal and minimal.count("\n") == 2
    assert normal.count("[REJECT ]") == 1                                            # generic button prompts: debug only
    assert debug.count("[REJECT ]") == 2 and "E0001" in debug and "adjusted to LOW" in debug
    assert _printed(lambda: _console("minimal").status("15 fps")) == ""


def test_console_never_breaks_when_the_window_is_gone():
    import builtins
    c, real = _console("normal"), builtins.print
    builtins.print = lambda *a, **k: (_ for _ in ()).throw(OSError("console closed"))
    try:
        c.event(EV_CERTAIN, "1", "1"); c.error("x"); c.status("y")                  # must not raise
    finally:
        builtins.print = real


def test_colours_are_off_when_output_is_redirected():
    from fortnite_chest_counter.console import Console
    c = Console()
    c.configure("normal", True, stream=io.StringIO())
    assert c.colors is False


# ------------------------------------------------------------------ 7. Set Starting Count (v0.1.1)

def _state_of(tmp):
    return json.loads((Path(tmp) / "state" / "chest_state.json").read_text(encoding="utf-8"))


def _run_with_answers(argv, answers):
    """Run main() with input() answering from a list (what a user types in Set Starting Count.bat)."""
    import builtins
    real, queue = builtins.input, list(answers)
    builtins.input = lambda prompt="": queue.pop(0) if queue else (_ for _ in ()).throw(EOFError())
    try:
        return run_main(argv)
    finally:
        builtins.input = real


def test_set_count_sets_approx_and_certain_zero_and_updates_obs():
    with tempfile.TemporaryDirectory() as tmp:
        code, text = run_main(["set-count", "150"] + args_for(tmp))
        assert code == 0 and "Starting count set" in text
        st = _state_of(tmp)
        assert (st["certain"], st["approximate"]) == (0, 150)
        assert (Path(tmp) / "obs_output" / "approximate_chests.txt").read_text(encoding="utf-8") == "APPROX. OPENED CHESTS: 150\n"
        assert (Path(tmp) / "obs_output" / "certain_chests.txt").read_text(encoding="utf-8") == "CERTAIN OPENED CHESTS: 0\n"
        log = next((Path(tmp) / "logs").glob("session_*.jsonl")).read_text(encoding="utf-8")
        assert '"set_starting_count"' in log


def test_set_count_interactive_rejects_bad_input_without_touching_the_counter():
    with tempfile.TemporaryDirectory() as tmp:
        run_main(["set-count", "9", "--certain", "3"] + args_for(tmp))
        code, text = _run_with_answers(["set-count"] + args_for(tmp), ["-5", "1.5", "abc", "2000000", " 1,200 "])
        assert code == 0
        for why in ("cannot be negative", "no decimals", "type a number", "more than"):
            assert why in text, why
        assert (_state_of(tmp)["certain"], _state_of(tmp)["approximate"]) == (0, 1200)


def test_set_count_cancel_or_invalid_argument_changes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        run_main(["set-count", "9", "--certain", "3"] + args_for(tmp))
        code, text = _run_with_answers(["set-count"] + args_for(tmp), [""])          # just Enter
        assert code == 0 and "Nothing was changed" in text
        code, _ = _run_with_answers(["set-count"] + args_for(tmp), [])                # window closed / EOF
        assert code == 0
        for bad in ("-1", "12.5", "lots", "99999999"):
            code, text = run_main(["set-count", bad] + args_for(tmp))
            assert code == 1 and "Nothing was changed" in text and "Traceback" not in text
        code, text = run_main(["set-count", "10", "--certain", "11"] + args_for(tmp))  # CERTAIN may not exceed APPROX
        assert code == 1
        assert (_state_of(tmp)["certain"], _state_of(tmp)["approximate"]) == (3, 9)


def test_set_count_persists_across_restart_and_reset_goes_to_zero():
    with tempfile.TemporaryDirectory() as tmp:
        run_main(["set-count", "150"] + args_for(tmp))
        restarted = chest_counter.CounterSession(tmp_config(tmp))
        assert (restarted.state["certain"], restarted.state["approximate"]) == (0, 150) and restarted.loaded_existing
        run_main(["reset"] + args_for(tmp))
        assert (_state_of(tmp)["certain"], _state_of(tmp)["approximate"]) == (0, 0)


def test_running_counter_adopts_a_starting_count_and_counts_on_top():
    with tempfile.TemporaryDirectory() as tmp:
        live = chest_counter.CounterSession(tmp_config(tmp))
        live.apply([event(True, True)], 1.0, quiet=True)                              # 1 / 1 before
        os.utime(live.state_path, None)
        run_main(["set-count", "150"] + args_for(tmp))
        live.apply([event(False, True, t=2.0)], 2.0, quiet=True)                      # in the SAME second, no sync tick
        assert (live.state["certain"], live.state["approximate"]) == (0, 151)          # added on top, not overwritten
        assert (_state_of(tmp)["certain"], _state_of(tmp)["approximate"]) == (0, 151)
        live.apply([event(True, True, t=3.0)], 3.0, quiet=True)
        assert (live.state["certain"], live.state["approximate"]) == (1, 152)


def test_reset_is_not_lost_when_a_chest_is_counted_in_the_same_second():
    with tempfile.TemporaryDirectory() as tmp:
        live = chest_counter.CounterSession(tmp_config(tmp))
        live.apply([event(True, True), event(True, True, t=2.0)], 2.0, quiet=True)
        os.utime(live.state_path, None)
        run_main(["reset"] + args_for(tmp))
        live.apply([event(False, True, t=3.0)], 3.0, quiet=True)
        assert (live.state["certain"], live.state["approximate"]) == (0, 1)


def test_parse_count_accepts_only_plain_whole_numbers():
    ok = {"150": 150, " 0 ": 0, "1,200": 1200, "1 000": 1000, "1_000_000": 1_000_000}
    for text, value in ok.items():
        assert chest_counter.parse_count(text)[0] == value, text
    for text in ("", "-3", "2.5", "1e3", "abc", "١٢", "1000001", "+5"):
        assert chest_counter.parse_count(text)[0] is None, text


# ------------------------------------------------------------------ 8. Configure Counter.bat / one obvious overlay (v0.1.1)

def _cfg_args(tmp):
    return ["--config", str(Path(tmp) / "config.toml")] + args_for(tmp)


def _obs(tmp, name):
    return (Path(tmp) / "obs_output" / name).read_text(encoding="utf-8")


def test_show_controls_both_all_in_one_files():
    with tempfile.TemporaryDirectory() as tmp:
        files = _obs_files(tmp, {"show": "approx", "approx_text": "Chests: {count}"}, 20, 231)
        assert files["chest_counter.txt"] == "Chests: 231\n" and files["chest_status.txt"] == "Chests: 231\n"
        files = _obs_files(tmp, {"show": "certain"}, 20, 231)
        assert files["chest_counter.txt"] == files["chest_status.txt"] == "CERTAIN OPENED CHESTS: 20\n"
        files = _obs_files(tmp, {"show": "both"}, 20, 231)                          # unchanged v0.1.0 behaviour
        assert files["chest_status.txt"] == "20 certain • ~231 estimated\n"
        assert files["certain_chests.txt"] == "CERTAIN OPENED CHESTS: 20\n" and files["approximate_chests.txt"] == "APPROX. OPENED CHESTS: 231\n"


def test_hash_wording_converts_both_ways():
    t = chest_counter.text_from_hash
    assert t("Chests opened: #") == "Chests opened: {count}"
    assert t("Chest Hunt: #/500") == "Chest Hunt: {count}/500"
    assert t("Chests opened:") == "Chests opened: {count}"                         # no # -> number at the end
    assert t("{weird} #") == "{{weird}} {count}"
    assert chest_counter.hash_from_text("Chest Hunt: {count}/500 {{x}}") == "Chest Hunt: #/500 {x}"


def test_config_writer_keeps_comments_and_other_settings():
    with tempfile.TemporaryDirectory() as tmp:
        example = Path(__file__).resolve().parent.parent / "config.example.toml"
        shutil_copy = Path(tmp) / "config.example.toml"
        shutil_copy.write_bytes(example.read_bytes())
        path = Path(tmp) / "config.toml"
        chest_counter.update_config_file(path, "display", {"show": "approx", "approx_text": 'He said "hi" \\ {count} 🏆'})
        text = path.read_text(encoding="utf-8")
        assert "OPTIONAL settings" in text and "[console]" in text and "verbosity = " in text   # created from the example
        cfg, _, warnings = settings.load_config(path)
        assert warnings == [] and cfg["display"]["show"] == "approx" and cfg["display"]["approx_text"] == 'He said "hi" \\ {count} 🏆'
        # a user's own file: other settings and comments survive, BOM accepted, missing section/key added
        path.write_bytes(b"\xef\xbb\xbf# my notes\n[detector]\nlanguages = [\"en\"]\n\n[live]\nsource = \"desktop\"\nmonitor = 2\n")
        chest_counter.update_config_file(path, "display", {"show": "certain", "certain_text": "Confirmed: {count}"})
        cfg, _, warnings = settings.load_config(path)
        assert warnings == [] and cfg["detector"]["languages"] == ["en"] and cfg["live"]["source"] == "desktop"
        assert cfg["display"]["show"] == "certain" and "# my notes" in path.read_text(encoding="utf-8")


def test_config_writer_restores_the_file_if_a_value_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        path.write_text('[display]\nshow = "approx"\n', encoding="utf-8")
        before = path.read_bytes()
        try:
            chest_counter.update_config_file(path, "display", {"show": "everything"})
            raise AssertionError("an invalid value was saved")
        except chest_counter.UserError as error:
            assert "Nothing was changed" in str(error)
        assert path.read_bytes() == before


def test_configure_menu_sets_what_viewers_see():
    with tempfile.TemporaryDirectory() as tmp:
        run_main(["set-count", "150"] + args_for(tmp))
        code, text = _run_with_answers(["configure"] + _cfg_args(tmp), ["7", "1", "Chests opened: #", ""])
        assert code == 0 and "is not one of" in text and "Preview" in text and "Saved in" in text
        assert "Viewers see (estimated total only): Chests opened: 150" in text
        assert "chest_counter.txt" in text and "Read from file" in text
        assert _obs(tmp, "chest_counter.txt") == _obs(tmp, "chest_status.txt") == "Chests opened: 150\n"
        cfg, _, warnings = settings.load_config(Path(tmp) / "config.toml")
        assert warnings == [] and cfg["display"]["show"] == "approx" and cfg["display"]["approx_text"] == "Chests opened: {count}"


def test_configure_enter_keeps_everything_and_default_restores_text():
    with tempfile.TemporaryDirectory() as tmp:
        run_main(["configure", "--show", "approx", "--approx-text", "Hunt: #/500"] + _cfg_args(tmp))
        code, text = _run_with_answers(["configure"] + _cfg_args(tmp), ["", ""])
        assert code == 0 and "Nothing changed" in text and _obs(tmp, "chest_counter.txt") == "Hunt: 0/500\n"
        code, text = _run_with_answers(["configure"] + _cfg_args(tmp), ["4", "default", "default", ""])
        assert code == 0 and _obs(tmp, "chest_counter.txt") == "CERTAIN OPENED CHESTS: 0\nAPPROX. OPENED CHESTS: 0\n"


def test_configure_command_line_for_ai_assistants():
    with tempfile.TemporaryDirectory() as tmp:
        code, text = run_main(["configure", "--show", "certain", "--certain-text", "Confirmed: #"] + _cfg_args(tmp))
        assert code == 0 and _obs(tmp, "chest_counter.txt") == "Confirmed: 0\n"


def test_running_counter_picks_up_overlay_changes():
    with tempfile.TemporaryDirectory() as tmp:
        args = SimpleNamespace(config=str(Path(tmp) / "config.toml"), process_fps=None, state=None, obs_dir=None,
                               log_dir=None, source=None, device=None, monitor=None)
        cfg = tmp_config(tmp)
        live = chest_counter.CounterSession(cfg)
        live.state.update(certain=2, approximate=9)
        watcher = chest_counter.DisplayConfigWatcher(args)
        assert watcher.check(live) is False                                         # nothing changed yet
        Path(args.config).write_text('[display]\nshow = "approx"\napprox_text = "Live: {count}"\n', encoding="utf-8")
        live.obs_dir = Path(tmp) / "obs_output"
        assert watcher.check(live) is True and live.display["show"] == "approx"
        assert _obs(tmp, "chest_counter.txt") == "Live: 9\n"
        assert watcher.check(live) is False


def test_show_command_says_what_viewers_see_and_which_file():
    with tempfile.TemporaryDirectory() as tmp:
        code, text = run_main(["show"] + args_for(tmp))
        assert code == 0 and "Viewers see (both numbers on two lines)" in text and "chest_counter.txt" in text


# ------------------------------------------------------------------ 9. four display modes, one OBS file (v0.1.1 refresh)

def test_four_display_modes_all_render_to_chest_counter_txt():
    cases = {("approx", "stacked"): "APPROX. OPENED CHESTS: 231\n",
             ("certain", "stacked"): "CERTAIN OPENED CHESTS: 20\n",
             ("both", "inline"): "20 certain • ~231 estimated\n",
             ("both", "stacked"): "CERTAIN OPENED CHESTS: 20\nAPPROX. OPENED CHESTS: 231\n"}
    with tempfile.TemporaryDirectory() as tmp:
        for (show, layout), expected in cases.items():
            files = _obs_files(tmp, {"show": show, "both_layout": layout}, 20, 231)
            assert files["chest_counter.txt"] == expected, (show, layout)
            # legacy files keep their meaning for advanced setups
            assert files["certain_chests.txt"] == "CERTAIN OPENED CHESTS: 20\n" and files["approximate_chests.txt"] == "APPROX. OPENED CHESTS: 231\n"


def test_existing_configs_keep_their_look():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.toml"
        for text, expected in (('[display]\nshow = "both"\n', "CERTAIN OPENED CHESTS: 20\nAPPROX. OPENED CHESTS: 231\n"),
                               ('[display]\ncertain_label = "CONFIRMED"\n', "CONFIRMED: 20\nAPPROX. OPENED CHESTS: 231\n"),
                               ('[display]\nshow = "approx"\napprox_text = "Hunt: {count}"\n', "Hunt: 231\n")):
            path.write_text(text, encoding="utf-8")
            cfg, _, warnings = settings.load_config(path)
            assert warnings == [] and _obs_files(tmp, cfg["display"], 20, 231)["chest_counter.txt"] == expected, text


def test_one_line_wording_markers():
    assert chest_counter.line_from_markers("#C found • #A total") == "{certain} found • {approx} total"
    assert chest_counter.line_from_markers("#a chests (#c sure)") == "{approx} chests ({certain} sure)"
    assert chest_counter.line_from_markers("{x} #A") == "{{x}} {approx}"
    assert chest_counter.line_from_markers("Chests") == "{certain} / {approx} Chests"
    assert chest_counter.markers_from_line(DEFAULTS["display"]["combined_status_format"]) == "#C certain • ~#A estimated"


def test_configure_one_line_mode_with_preview_and_cancel():
    with tempfile.TemporaryDirectory() as tmp:
        run_main(["set-count", "150"] + args_for(tmp))
        code, text = _run_with_answers(["configure"] + _cfg_args(tmp), ["3", "#C found • #A total", "n"])
        assert code == 0 and "Preview" in text and "0 found • 150 total" in text and "Cancelled" in text
        assert not (Path(tmp) / "config.toml").exists()                              # cancel saved nothing
        code, text = _run_with_answers(["configure"] + _cfg_args(tmp), ["3", "#C found • #A total", ""])
        assert code == 0 and _obs(tmp, "chest_counter.txt") == "0 found • 150 total\n"
        assert "Viewers see (both numbers on one line)" in text
        cfg, _, warnings = settings.load_config(Path(tmp) / "config.toml")
        assert warnings == [] and (cfg["display"]["show"], cfg["display"]["both_layout"]) == ("both", "inline")


def test_configure_command_line_layouts():
    with tempfile.TemporaryDirectory() as tmp:
        run_main(["configure", "--show", "both", "--layout", "inline", "--line-text", "#A chests (#C sure)"] + _cfg_args(tmp))
        assert _obs(tmp, "chest_counter.txt") == "0 chests (0 sure)\n"
        run_main(["configure", "--layout", "stacked"] + _cfg_args(tmp))
        assert _obs(tmp, "chest_counter.txt").count("\n") == 2
        run_main(["configure", "--show", "approx"] + _cfg_args(tmp))
        assert _obs(tmp, "chest_counter.txt") == "APPROX. OPENED CHESTS: 0\n"


def test_switching_modes_while_running_updates_the_same_file():
    with tempfile.TemporaryDirectory() as tmp:
        args = SimpleNamespace(config=str(Path(tmp) / "config.toml"), process_fps=None, state=None, obs_dir=None,
                               log_dir=None, source=None, device=None, monitor=None)
        live = chest_counter.CounterSession(tmp_config(tmp))
        live.state.update(certain=3, approximate=12)
        watcher = chest_counter.DisplayConfigWatcher(args)
        seen = []
        for i, block in enumerate(('show = "approx"', 'show = "certain"', 'show = "both"\nboth_layout = "inline"',
                                   'show = "both"\nboth_layout = "stacked"')):
            Path(args.config).write_text(f"[display]\n{block}\n", encoding="utf-8")
            os.utime(args.config, ns=(10**9 * (i + 1), 10**9 * (i + 1)))             # a distinct mtime per edit
            assert watcher.check(live) is True
            seen.append(_obs(tmp, "chest_counter.txt"))
        assert seen == ["APPROX. OPENED CHESTS: 12\n", "CERTAIN OPENED CHESTS: 3\n", "3 certain • ~12 estimated\n",
                        "CERTAIN OPENED CHESTS: 3\nAPPROX. OPENED CHESTS: 12\n"]




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
    print(f"{len(tests) - failed}/{len(tests)} release checks passed")
    raise SystemExit(1 if failed else 0)
