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
    assert code == 0 and "v0.1.0" in text


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
