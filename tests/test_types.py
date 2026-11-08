"""
Chest-type statistics (v0.2.2): which kind of chest each COUNTED chest was - per profile, a label that never changes
CERTAIN / APPROX (detection/chest_types.py, counter.type_breakdown).        Run:   python tests/test_types.py   (or pytest)
"""

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "src"))   # run without installing
sys.path.insert(0, str(_P(__file__).resolve().parent))

import contextlib
import io
import json
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

from fortnite_chest_counter import counter as C
from fortnite_chest_counter import profiles, settings
from fortnite_chest_counter.detection import chest_types as CT
from fortnite_chest_counter.detection import visual as V

import test_cases


def _cfg(tmp):
    cfg, _, _ = settings.load_config(None, {("state", "path"): str(Path(tmp) / "state" / "chest_state.json"),
                                            ("state", "obs_dir"): str(Path(tmp) / "obs_output"),
                                            ("logging", "dir"): str(Path(tmp) / "logs")})
    return cfg


def _ev(t, certain, kind=None):
    ev = {"time": t, "source": "popup", "adjusted_tier": "HIGH" if certain else "MEDIUM", "certain_counted": certain,
          "approx_counted": True, "popup_score": 0.9, "reason": "test"}
    if kind:
        ev["chest_type"] = kind
    return ev


def _quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


def _sums_match(state):
    rows = C.type_breakdown(state)
    return (sum(r["certain"] for r in rows.values()) == state["certain"]
            and sum(r["approx"] for r in rows.values()) == state["approximate"])


def test_counts_saved_before_v022_stay_unclassified_and_nothing_is_invented():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chest_state.json"
        path.write_text(json.dumps({"certain": 12, "approximate": 30, "events_logged": 30}), encoding="utf-8")
        state = C.load_state(path)
        rows = C.type_breakdown(state)
        assert all(rows[k] == {"certain": 0, "approx": 0} for k in (*CT.KNOWN, CT.UNKNOWN))
        assert rows["unclassified"] == {"certain": 12, "approx": 30} and _sums_match(state)
        assert state["types_since"]


def test_each_counted_chest_adds_to_its_type_and_the_totals_once():
    with tempfile.TemporaryDirectory() as tmp:
        session = C.CounterSession(_cfg(tmp))
        _quiet(session.apply, [_ev(1.0, True, CT.RARE), _ev(5.0, False, CT.SPRITE), _ev(9.0, True, CT.NORMAL),
                               _ev(13.0, False)], 14.0, quiet=True)
        st = session.state
        assert (st["certain"], st["approximate"]) == (2, 4)                           # classification adds no count
        t = st["types"]
        assert t[CT.RARE] == {"certain": 1, "approx": 1} and t[CT.SPRITE] == {"certain": 0, "approx": 1}
        assert t[CT.NORMAL] == {"certain": 1, "approx": 1} and t[CT.UNKNOWN] == {"certain": 0, "approx": 1}
        assert C.type_breakdown(st)["unclassified"] == {"certain": 0, "approx": 0} and _sums_match(st)
        saved = json.loads(session.state_path.read_text(encoding="utf-8"))
        assert saved["types"][CT.RARE]["approx"] == 1                                 # persisted with the counts


def test_a_later_type_reading_moves_the_chest_without_changing_any_total():
    with tempfile.TemporaryDirectory() as tmp:
        session = C.CounterSession(_cfg(tmp))
        _quiet(session.apply, [_ev(3.0, True, CT.UNKNOWN)], 4.0, quiet=True)
        assert session.apply_type_updates([{"time": 3.0, "chest_type": CT.RARE, "type_confidence": 0.9}])
        st = session.state
        assert (st["certain"], st["approximate"]) == (1, 1)
        assert st["types"][CT.RARE] == {"certain": 1, "approx": 1} and st["types"][CT.UNKNOWN] == {"certain": 0, "approx": 0}
        assert not session.apply_type_updates([{"time": 99.0, "chest_type": CT.SPRITE}])   # unknown event: ignored
        log = [json.loads(line) for line in session.log.path.read_text(encoding="utf-8").splitlines()]
        assert any(r.get("event") == "type_update" and r["from"] == CT.UNKNOWN and r["to"] == CT.RARE for r in log)


def test_manual_edits_go_to_unclassified_and_reset_clears_the_types():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        session = C.CounterSession(cfg)
        _quiet(session.apply, [_ev(1.0, True, CT.RARE), _ev(2.0, False, CT.NORMAL)], 3.0, quiet=True)
        st = _quiet(C.set_counts, cfg, 1, 100).state                                 # "I opened 100 chests"
        assert C.type_breakdown(st)["unclassified"] == {"certain": 0, "approx": 98} and _sums_match(st)
        st = _quiet(C.set_counts, cfg, 0, 1).state                                   # corrected downwards
        assert C.type_breakdown(st)["unclassified"]["approx"] == -1 and _sums_match(st)   # stays consistent
        st = _quiet(C.set_counts, cfg, 0, 0, "reset").state
        assert all(v == {"certain": 0, "approx": 0} for v in st["types"].values()) and _sums_match(st)


def test_every_profile_keeps_its_own_type_statistics():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "state" / "chest_state.json"
        cfg = _cfg(tmp)
        profiles.apply(cfg)
        _quiet(C.CounterSession(cfg).apply, [_ev(1.0, True, CT.RARE)], 2.0, quiet=True)
        profiles.create(base, "Thiefs")
        cfg = _cfg(tmp)
        profiles.apply(cfg)
        _quiet(C.CounterSession(cfg).apply, [_ev(1.0, False, CT.SPRITE)], 2.0, quiet=True)
        thiefs = C.load_state(cfg["state"]["path"])["types"]
        default = C.load_state(base)["types"]
        assert thiefs[CT.SPRITE]["approx"] == 1 and thiefs[CT.RARE]["approx"] == 0
        assert default[CT.RARE]["approx"] == 1 and default[CT.SPRITE]["approx"] == 0


def test_damaged_or_future_type_entries_are_handled_safely():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chest_state.json"
        path.write_text(json.dumps({"certain": 2, "approximate": 3, "types": {"rare": {"certain": 1, "approx": 1},
                                    "dark": {"certain": 0, "approx": 1}, "sprite": {"certain": -4, "approx": "x"}}}),
                        encoding="utf-8")
        state = C.load_state(path)
        assert state["types"]["dark"] == {"certain": 0, "approx": 1}                 # a future type survives
        assert state["types"][CT.SPRITE] == {"certain": 0, "approx": 0}              # a bad row is dropped, not guessed
        assert _sums_match(state)


def test_line_classifier_reads_normal_rare_and_sprite_and_never_guesses_normal():
    assert CT.classify_line(np.zeros((40, 120), np.float32), 10, 60, 7, 27, CT.load_prefixes("normal"))[0] == CT.NORMAL
    noisy = np.zeros((40, 120), np.float32)
    noisy[9:18, 30:58] = (np.random.default_rng(0).random((9, 28)) > 0.5)           # ink of the right length, no word
    kind, evidence = CT.classify_line(noisy, 10, 60, 7, 27, CT.load_prefixes("normal"))
    assert kind in (CT.UNKNOWN,) and evidence["prefix_length"] > 0.25
    assert CT.decide(Counter({CT.RARE: 2})) == (CT.UNKNOWN, 0.0)                    # too few readings yet
    assert CT.decide(Counter({CT.RARE: 4, CT.SPRITE: 1}))[0] == CT.RARE
    assert CT.decide(Counter({CT.RARE: 3, CT.SPRITE: 3}))[0] == CT.UNKNOWN          # no clear majority
    assert CT.decide(Counter({CT.UNKNOWN: 9, CT.NORMAL: 1}))[0] == CT.UNKNOWN


def test_counted_chests_of_every_case_get_the_right_type_or_unknown():
    """Every chest of the real cases: the type read from its line must equal the labelled type - a wrong type is a
    failure; 'unknown' is allowed but counted."""
    wrong, unknown, total = [], 0, 0
    for name, case in test_cases.CASES.items():
        if case.get("known_limitation"):
            continue
        counted = test_cases.replay(name)
        truths = [r for r in case["truth"] if r["what"] != "not_chest"]
        for r in truths:
            near = [e for e in counted if r["t"] - test_cases.BEFORE <= e["time"] <= r["t"] + test_cases.AFTER]
            if not near:
                continue
            e = min(near, key=lambda e: abs(e["time"] - r["t"]))
            total += 1
            if e.get("chest_type") == CT.UNKNOWN:
                unknown += 1
            elif e.get("chest_type") != r["type"]:
                wrong.append((name, r["t"], r["type"], e.get("chest_type")))
    assert not wrong, wrong
    assert total >= 28 and unknown <= 3, (total, unknown)


def test_app_shows_the_type_split_of_the_selected_profile():
    import os
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("      (skipped: PySide6 not installed)")
        return
    from fortnite_chest_counter import paths
    from fortnite_chest_counter.gui import app as A
    qt = QApplication.instance() or QApplication([])
    here, app_dir = os.getcwd(), paths.APP_DIR
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        paths.APP_DIR = Path(tmp)
        win = None
        try:
            base = Path(tmp) / "state" / "chest_state.json"
            base.parent.mkdir(parents=True)
            base.write_text(json.dumps({"certain": 3, "approximate": 7}), encoding="utf-8")     # saved by v0.2.1
            win = A.MainWindow()
            win.timer.stop()
            win.slow.stop()
            assert win.dashboard.types.text() == "not classified 7"                       # nothing invented
            cfg = A.load_cfg()[0]
            session = C.CounterSession(cfg)
            _quiet(session.apply, [_ev(1.0, True, CT.RARE), _ev(2.0, False, CT.SPRITE)], 3.0, quiet=True)
            win.read_state(force=True)
            text = win.dashboard.types.text()
            assert "Rare chest 1" in text and "Sprite chest 1" in text and "not classified 7" in text, text
            win.handle({"type": "types", "breakdown": C.type_breakdown(session.state)})     # live worker message
            assert win.dashboard.types.text() == text
            profiles.create(base, "Thiefs", activate=False)
            win.fill_profiles()
            win.dashboard.profile.setCurrentIndex(1)
            win.switch_profile(1)
            assert win.dashboard.types.text() == "no chests yet"                          # the new profile's own split
        finally:
            if win is not None:
                if win._source_scan is not None:
                    win._source_scan.join(30)
                win.preview_reader and win.preview_reader.close()
                win.deleteLater()
            qt.processEvents()
            os.chdir(here)
            paths.APP_DIR = app_dir


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
    print(f"{len(tests) - failed}/{len(tests)} type checks passed")
    sys.exit(1 if failed else 0)
