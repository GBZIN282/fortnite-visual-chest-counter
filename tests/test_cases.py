"""
Real-world detection cases (tests/cases/cases.json, docs/INVESTIGATION_2026-11-08.md) as permanent regression tests.

Each case's pop-up box masks (tests/fixtures/popups/<case>.npz, made by research/cases.py fixtures from the user's
diagnostic captures) are replayed through the real ChestEstimator. The pop-up channels work on that mask only, so the
pop-up decisions are the ones the full footage gives (research/cases.py run checks the full frames when the footage is
present). The other clues (prompt, sprite tag, ammo) see an empty picture here.

Every confirmed failure becomes a case: add it to cases.json, run `research/cases.py fetch` + `fixtures`, add a check.
Run:   python tests/test_cases.py     (or pytest)
"""

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "src"))   # run without installing

import json
from pathlib import Path

import numpy as np

from fortnite_chest_counter import estimator as E
from fortnite_chest_counter import settings
from fortnite_chest_counter.detection import visual as V

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "cases" / "cases.json").read_text(encoding="utf-8"))["cases"]
BEFORE, AFTER = 0.5, 2.5


def frames(name):
    d = np.load(HERE / "fixtures" / "popups" / f"{name}.npz")
    h, w = (int(v) for v in d["shape"])
    frame = np.zeros((V.NORMALIZED_HEIGHT, V.NORMALIZED_WIDTH, 3), np.uint8)
    for t, packed in zip(d["times"], d["masks"]):
        mask = np.unpackbits(packed)[:h * w].reshape(h, w).astype(bool)
        roi = np.where(mask[..., None], np.array([232, 196, 250], np.uint8), np.array([40, 36, 60], np.uint8))
        frame[V.ROI_Y:V.ROI_Y + h, V.ROI_X:V.ROI_X + w] = roi
        yield float(t), frame


def replay(name, **channels):
    E.configure(settings.DEFAULTS["detector"])
    est = E.ChestEstimator(**channels)
    events = []
    for t, f in frames(name):
        events += est.process_frame(t, f)
    events += est.flush()
    return [e for e in events if e["approx_counted"]]


def score(name, counted):
    """-> (found, missed, duplicates, false) against the case's truth."""
    chests = [dict(r, hits=0) for r in CASES[name]["truth"] if r["what"] != "not_chest"]
    dup = false = 0
    for e in sorted(counted, key=lambda e: e["time"]):
        near = [c for c in chests if c["t"] - BEFORE <= e["time"] <= c["t"] + AFTER]
        free = [c for c in near if not c["hits"]]
        if free:
            min(free, key=lambda c: abs(c["t"] - e["time"]))["hits"] += 1
        elif near:
            dup += 1
        else:
            false += 1
    found = sum(1 for c in chests if c["hits"])
    return found, len(chests) - found, dup, false


def check(name, expect_found=None, **channels):
    counted = replay(name, **channels)
    found, missed, dup, false = score(name, counted)
    real = len([r for r in CASES[name]["truth"] if r["what"] != "not_chest"])
    want = real if expect_found is None else expect_found
    assert (found, dup, false) == (want, 0, 0), f"{name}: found {found}/{real}, missed {missed}, duplicates {dup}, false {false}"
    return counted


def test_fixtures_and_truth_exist_for_every_case():
    for name, case in CASES.items():
        if case.get("known_limitation"):
            continue
        assert (HERE / "fixtures" / "popups" / f"{name}.npz").exists(), name
        assert case["truth"] and all(r["what"] in ("new_popup", "new_line", "multiplier", "not_chest") for r in case["truth"])


def test_thiefs_small_hud_all_five_chests_approx_only():
    counted = check("thiefs_small_hud")
    assert len(counted) == 5 and not any(e["certain_counted"] for e in counted)          # small HUD: APPROX only
    assert [e.get("increment", {}).get("kind") for e in counted] == [None, None, "new_line", "multiplier", "multiplier"]
    assert all(e["scaled_popup"]["scale"] == E.SMALL_SCALE for e in counted)
    assert not replay("thiefs_small_hud", small_hud=False, stacked=False)                # v0.2.1: nothing at all


def test_small_hud_channel_alone_finds_the_two_new_pop_ups():
    counted = replay("thiefs_small_hud", stacked=False)
    assert len(counted) == 2 and score("thiefs_small_hud", counted)[2:] == (0, 0)       # stacked steps need the tracker


def test_normal_hud_x2_and_x3_steps_are_counted_once_each():
    counted = check("replays_stack_x2_x3")
    steps = [e for e in counted if e.get("increment")]
    assert [s["increment"]["kind"] for s in steps] == ["multiplier", "multiplier"]
    assert not any(s["certain_counted"] for s in steps)                                  # multiplier steps: APPROX only
    assert len(replay("replays_stack_x2_x3", stacked=False)) == 1                       # v0.2.1: the first chest only


def test_a_new_chest_line_keeps_the_normal_rules():
    counted = check("replays_new_chest_line")
    line = [e for e in counted if e.get("increment")]
    assert len(line) == 1 and line[0]["increment"]["kind"] == "new_line"
    assert line[0]["certain_counted"] == counted[0]["certain_counted"]                   # tiers as for a new pop-up


def test_a_non_chest_line_added_to_the_pop_up_does_not_count_again():
    check("replays_sprite_level_line")
    old = replay("replays_sprite_level_line", stacked=False)                             # v0.2.1's position re-fire
    assert score("replays_sprite_level_line", old)[2] == 1                               # counted the same chest twice


def test_e0015_case_and_storm_phase_and_weakpoint_lines_do_not_count():
    check("replays_e0015_duplicate")
    check("replays_six_chests")


def test_old_position_re_fire_double_counts_the_e0015_pop_up_under_noise_and_the_tracker_does_not():
    """Live E0015 (not reproducible from the MJPEG recording): the same pop-up counted twice when the score hovered at
    0.75 and the scale-in animation had moved the word by 8 px. Same trace + small noise, both rules."""
    d = np.load(HERE / "fixtures" / "popups" / "replays_e0015_duplicate.npz")
    h, w = (int(v) for v in d["shape"])
    tpl = V.load_templates()[0]["array"]
    trace = []
    for t, packed in zip(d["times"], d["masks"]):
        m = np.unpackbits(packed)[:h * w].reshape(h, w).astype(np.float32)
        s, y, x = V.best_template_correlation(m, tpl) if m.sum() >= 20 else (0.0, 0, 0)
        trace.append((float(t), s, y, x))
    rng = np.random.default_rng(7)
    twice = {True: 0, False: 0}
    for _ in range(600):
        noise = rng.normal(0, 0.015, len(trace))
        for jump in (True, False):
            od = E.OnsetDetector(V.EVENT_HIGH_THRESHOLD, V.EVENT_LOW_THRESHOLD, True)
            fires = [t for (t, s, y, x), n in zip(trace, noise) if od.update(t, s + n, y, x, allow_jump=jump)]
            twice[jump] += sum(1 for f in fires if 185.9 <= f <= 188.3) > 1
    assert twice[True] > 0 and twice[False] == 0, twice


def test_every_case_finds_every_chest_once_and_nothing_else():
    for name, case in CASES.items():
        if not case.get("known_limitation"):
            check(name)


def test_five_chest_vault_counts_every_step_including_the_third_lines_x2():
    counted = check("replays_vault_five_chests")
    assert sorted((e.get("increment") or {}).get("kind") or "new" for e in counted) == \
        ["multiplier", "multiplier", "new", "new_line", "new_line"]


def test_a_late_exact_match_on_a_pop_up_already_counted_is_the_same_pop_up():
    counted = check("replays_chest_x2_late_exact")                     # scale-aware onset + X2, no third count
    assert len(counted) == 2
    old = replay("replays_chest_x2_late_exact", stacked=False)
    assert len(old) == 2 and not any(e.get("increment") for e in old)  # v0.2.1: right total, for the wrong reason


def test_non_chest_lines_and_an_unchanged_pop_up_are_not_counted_again():
    for name in ("replays_weakpoint_line", "replays_static_popup_refire"):
        assert len(check(name)) == 1
        _, _, dup, false = score(name, replay(name, stacked=False))
        assert dup + false == 1, name                                    # v0.2.1 counted the same chest twice


def test_portuguese_only_settings_keep_the_position_re_fire_and_no_new_channels():
    E.configure(dict(settings.DEFAULTS["detector"], languages=["pt"], medium_counts_alone_languages=[]))
    try:
        est = E.ChestEstimator()
        assert est.small is None and not est.stacked and est.popup.use_position
    finally:
        E.configure(settings.DEFAULTS["detector"])


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
    print(f"{len(tests) - failed}/{len(tests)} case checks passed")
    sys.exit(1 if failed else 0)
