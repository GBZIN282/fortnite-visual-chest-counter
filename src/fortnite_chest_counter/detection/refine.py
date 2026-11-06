"""
Second evidence layer: use shooting / interaction cues to re-rank AMBIGUOUS events,
and look for chests the popup detector never reported.

Additive and inspectable. It never changes the popup detector, its thresholds, the
base tier, or the verified labels: every row keeps `base_tier` next to `adjusted_tier`.

Adjustment rules (fixed in advance from what the cues physically mean; the verified
labels are only used afterwards to EVALUATE them, never to pick them):

  CERTAIN / HIGH     never changed (protected).
  MEDIUM + player shooting + no interaction cue      -> LOW     (ammo is changing: the local
                                                                 player is firing, and the
                                                                 popup is likely a combat popup)
  MEDIUM + interaction cue + not shooting            -> HIGH
  otherwise                                          -> unchanged

Usage
-----
    python -m fortnite_chest_counter.detection.refine --name Fortnite-PS5-Pro
"""

import argparse
import re
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from fortnite_chest_counter.detection import evidence
from fortnite_chest_counter.detection import fusion
from fortnite_chest_counter.detection.audio import OUTPUT_DIR

SAMPLES = Path("samples/video tests")

# "Interaction cue" = the grayscale ring-on-disc prompt patch scores at least this in the
# 2.5 s before the popup. A prior: roughly the 99th percentile of that score over the whole video.
PROMPT_GRAY_MIN = 0.70
TIER_ORDER = ["CERTAIN", "HIGH", "MEDIUM", "LOW", "REJECT"]


def parse_predictions(path):
    rows = []
    pattern = re.compile(r"^#(\d+)\s+(\d+):(\d+\.\d+)\s+(\w+)\s+(\w+)\s+([\d.]+)\s+([\d.\-]+)\s+(\S+)\s+(\S+)")
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        rows.append({"id": int(m[1]), "stamp": f"{int(m[2]):02d}:{m[3]}", "time": int(m[2]) * 60 + float(m[3]),
                     "decision": m[4], "base_tier": m[5], "popup": float(m[7]) if m[7] != "-" else None,
                     "template": m[8]})
    return rows


def adjust(row):
    """-> (adjusted_tier, reason). Only MEDIUM events can move."""
    if row["base_tier"] != "MEDIUM":
        return row["base_tier"], "protected (base tier CERTAIN/HIGH)"
    shooting, interaction = row["shooting"], row["interaction"]
    if shooting and not interaction:
        return "LOW", f"player shooting ({row['ammo_steps']} ammo steps), no interaction cue"
    if interaction and not shooting:
        return "HIGH", f"interaction prompt before popup ({row['prompt_gray']:.2f}), not shooting"
    if shooting and interaction:
        return "MEDIUM", "shooting AND interaction cue: conflicting, unchanged"
    return "MEDIUM", "no shooting or interaction evidence: unchanged"


def tier_table(rows, key):
    lines = []
    for tier in TIER_ORDER:
        sel = [r for r in rows if r[key] == tier]
        if not sel:
            continue
        yes = sum(r["verified"] for r in sel)
        lines.append(f"  {tier:8s} {yes}/{len(sel)} true  ({yes / len(sel):.0%})")
    return "\n".join(lines)


def base_rates(cues, gray_t, gray_s, rows, binary_level):
    """
    How often does each cue appear in an ARBITRARY stretch of the video (windows every second,
    excluding +/-4 s around predicted events)? A cue that is common everywhere cannot be
    strong evidence even if it appears at every real chest.
    """
    events = np.array([r["time"] for r in rows])
    duration = cues["t"][-1]
    times = [t for t in np.arange(4.0, duration - 4.0, 1.0) if np.min(np.abs(events - t)) > 4.0]
    gray = np.mean([evidence.prompt_gray(gray_t, gray_s, t) >= PROMPT_GRAY_MIN for t in times])
    binary = np.mean([evidence.prompt_binary(cues, t) >= binary_level for t in times])
    shooting = np.mean([evidence.ammo_steps(cues, t) >= evidence.SHOOTING_MIN_STEPS for t in times])
    flash = np.mean([evidence.flash_bursts(cues, t) >= 3 for t in times])
    return {"windows": len(times), "prompt_gray": gray, "prompt_binary": binary, "shooting_ammo": shooting,
            "flash>=3": flash}


def missed_candidates(cues, gray_t, gray_s, rows):
    """
    Moments with an interaction-prompt peak that are NOT near any predicted popup event.
    Independent of the CHEST/BAU popup. Candidates only, never called chests.
    """
    events = np.array([r["time"] for r in rows])
    peaks, _ = find_peaks(gray_s, height=PROMPT_GRAY_MIN, distance=int(6 * evidence.PROMPT_GRAY_FPS))
    out = []
    for i in peaks:
        tp = float(gray_t[i])
        if np.any((tp >= events - 3.0) & (tp <= events + 1.0)):
            continue       # a prompt this close before a predicted event belongs to that event
        steps = evidence.ammo_steps(cues, tp, (-1.0, 1.0))
        gold = evidence.gold_mean(cues, tp, (-0.5, 2.0))
        clues = ["prompt"] + (["gold-glow"] if gold >= 0.10 else []) + (["SHOOTING(neg)"] if steps >= evidence.SHOOTING_MIN_STEPS else [])
        reason = f"interaction prompt {gray_s[i]:.2f}, gold share {gold:.2f}, ammo steps {steps}; no popup detected within -3 s..+1 s"
        out.append({"time": tp, "score": float(gray_s[i]), "clues": ",".join(clues), "reason": reason,
                    "shooting": steps >= evidence.SHOOTING_MIN_STEPS})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="Fortnite-PS5-Pro")
    parser.add_argument("--rescan", action="store_true")
    args = parser.parse_args()

    video = SAMPLES / f"{args.name}-HD-No-Audio.mp4"
    rows = parse_predictions(SAMPLES / f"{args.name}-predicted-chests.txt")
    labels = fusion.load_verified_labels(SAMPLES / f"{args.name}-verified-predictions.txt")
    for r in rows:
        r["verified"] = labels[r["stamp"]]
    print(f"{len(rows)} predicted events, {sum(r['verified'] for r in rows)} verified YES, "
          f"{sum(not r['verified'] for r in rows)} verified NO")

    cues = evidence.extract_cues(video, OUTPUT_DIR / f"{args.name}_cues.npz", args.rescan)
    gray_t, gray_s = evidence.extract_prompt_gray(video, OUTPUT_DIR / f"{args.name}_prompt_gray.npz", args.rescan)
    print(f"Grayscale prompt score over the whole video, percentiles 50/90/99/99.9: "
          + " / ".join(f"{p:.2f}" for p in np.percentile(gray_s, [50, 90, 99, 99.9])))

    for r in rows:
        t = r["time"]
        r["ammo_steps"] = evidence.ammo_steps(cues, t)
        r["ammo_steps_narrow"] = evidence.ammo_steps(cues, t, (-0.5, 0.5))
        r["flash"] = evidence.flash_bursts(cues, t)
        r["prompt_bin"] = evidence.prompt_binary(cues, t)
        r["prompt_gray"] = evidence.prompt_gray(gray_t, gray_s, t)
        r["gold"] = evidence.gold_mean(cues, t)
        r["shooting"] = r["ammo_steps"] >= evidence.SHOOTING_MIN_STEPS
        r["interaction"] = r["prompt_gray"] >= PROMPT_GRAY_MIN
        r["adjusted_tier"], r["reason"] = adjust(r)

    header = (f"{'id':>4} {'time':>8} {'real':>4} {'base':>8} {'popup':>5} | {'ammoSteps':>9} {'(narrow)':>8} {'flash':>5} "
              f"{'promptBin':>9} {'promptGray':>10} {'gold':>5} | {'adjusted':>8}  reason")
    print("\n" + header)
    out_lines = [header]
    for r in rows:
        line = (f"#{r['id']:03d} {r['stamp']:>8} {'YES' if r['verified'] else 'NO':>4} {r['base_tier']:>8} "
                f"{r['popup']:5.2f} | {r['ammo_steps']:9d} {r['ammo_steps_narrow']:8d} {r['flash']:5d} "
                f"{r['prompt_bin']:9.2f} {r['prompt_gray']:10.2f} {r['gold']:5.2f} | {r['adjusted_tier']:>8}  {r['reason']}")
        print(line)
        out_lines.append(line)

    # ---- cue separation among MEDIUM events (the only ones that can move) ----
    med = [r for r in rows if r["base_tier"] == "MEDIUM"]
    print("\nCue values among the 9 MEDIUM events (true = verified chest):")
    for key in ("ammo_steps", "ammo_steps_narrow", "flash", "prompt_bin", "prompt_gray", "gold"):
        t_vals = [round(r[key], 2) for r in med if r["verified"]]
        f_vals = [round(r[key], 2) for r in med if not r["verified"]]
        print(f"  {key:18s} true {t_vals}   false {f_vals}")
    print("\nCue values among the 10 CERTAIN/HIGH events (all true):")
    for key in ("ammo_steps", "prompt_gray", "gold"):
        print(f"  {key:18s} {[round(r[key], 2) for r in rows if r['base_tier'] != 'MEDIUM']}")

    # ---- tier quality before / after ----
    print("\nPrecision by tier BEFORE added evidence (base tier):")
    print(tier_table(rows, "base_tier"))
    print("Precision by tier AFTER added evidence (adjusted tier):")
    print(tier_table(rows, "adjusted_tier"))
    protected = [r for r in rows if r["base_tier"] in ("CERTAIN", "HIGH")]
    print(f"\nProtected CERTAIN/HIGH events unchanged: "
          f"{sum(r['adjusted_tier'] == r['base_tier'] for r in protected)}/{len(protected)}")
    moved = [r for r in med if r["adjusted_tier"] != "MEDIUM"]
    print("MEDIUM events that moved: " + (", ".join(
        f"#{r['id']:03d} {r['base_tier']}->{r['adjusted_tier']} ({'real' if r['verified'] else 'false'})" for r in moved) or "none"))

    # ---- is the added evidence just common everywhere? (base rates) ----
    true_rows = [r for r in rows if r["verified"]]
    false_rows = [r for r in rows if not r["verified"]]
    binary_level = min(r["prompt_bin"] for r in true_rows)       # level every verified chest reaches
    rates = base_rates(cues, gray_t, gray_s, rows, binary_level)
    print(f"\nBase rates over {rates['windows']} arbitrary windows of the video vs the 12 real / 7 false events:")
    print(f"  grayscale prompt >= {PROMPT_GRAY_MIN}:   arbitrary {rates['prompt_gray']:.0%}   "
          f"real {sum(r['prompt_gray'] >= PROMPT_GRAY_MIN for r in true_rows)}/12   "
          f"false {sum(r['prompt_gray'] >= PROMPT_GRAY_MIN for r in false_rows)}/7")
    print(f"  binary ring >= {binary_level:.2f} (lowest real): arbitrary {rates['prompt_binary']:.0%}   real 12/12   "
          f"false {sum(r['prompt_bin'] >= binary_level for r in false_rows)}/7")
    print(f"  player shooting (ammo steps >= {evidence.SHOOTING_MIN_STEPS}): arbitrary {rates['shooting_ammo']:.0%}   "
          f"real {sum(r['shooting'] for r in true_rows)}/12   false {sum(r['shooting'] for r in false_rows)}/7")
    print(f"  muzzle-flash bursts >= 3:   arbitrary {rates['flash>=3']:.0%}   "
          f"real {sum(r['flash'] >= 3 for r in true_rows)}/12   false {sum(r['flash'] >= 3 for r in false_rows)}/7")

    # ---- post-hoc variant: ammo OR flash as the shooting cue (NOT adopted; exploratory) ----
    variant = []
    for r in med:
        shooting_b = r["shooting"] or r["flash"] >= 3
        variant.append((r["id"], r["verified"], shooting_b))
    print("\nExploratory (not adopted): shooting = ammo steps >= 2 OR flash bursts >= 3 -> MEDIUM events flagged: "
          + ", ".join(f"#{i:03d}({'real' if v else 'false'})" for i, v, sh in variant if sh))

    # ---- missed-chest candidate search ----
    cands = missed_candidates(cues, gray_t, gray_s, rows)
    known = [r for r in rows if r["verified"]]
    found = sum(r["prompt_gray"] >= PROMPT_GRAY_MIN for r in known)
    print(f"\nMissed-chest candidate search (prompt-based, independent of the popup): {len(cands)} candidates")
    print(f"  generator sensitivity on the 12 verified chests: {found}/12 have the prompt cue "
          f"(so chests without a detectable prompt cannot be found this way)")
    out = ["# AUTO-GENERATED — UNVERIFIED",
           "# Candidate moments that were NOT among the popup predictions. These are NOT chests until verified.",
           "# Source: interaction-prompt peaks (grayscale ring-on-disc patch >= %.2f), no popup within -3 s..+1 s." % PROMPT_GRAY_MIN,
           "# To review: edit VERIFIED= to VERIFIED=YES or VERIFIED=NO.",
           "#",
           "# Format:",
           "# #id  timestamp    candidate-score    clues    verified    # reason",
           ""]
    # reviewer labels are carried over by timestamp from the permanent reviewed copy (never written here)
    reviewed = SAMPLES / f"{args.name}-verified-missed-candidates.txt"
    carried = fusion.load_verified_labels(reviewed) if reviewed.exists() else {}
    for k, c in enumerate(cands, 1):
        c["id"] = k
        stamp = fusion.mmss(c["time"])
        verdict = {True: "YES", False: "NO"}.get(carried.get(stamp), "")
        line = f"#M{k:03d}  {stamp}    {c['score']:.2f}    {c['clues']}    VERIFIED={verdict}    # {c['reason']}"
        out.append(line)
        print("  " + line)
    (SAMPLES / f"{args.name}-missed-chest-candidates.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {SAMPLES / (args.name + '-missed-chest-candidates.txt')}")

    from fortnite_chest_counter.detection import predict
    review_dir = OUTPUT_DIR / f"{args.name}_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    for old in review_dir.glob("missed_*.png"):
        old.unlink()
    for c in cands:
        predict.make_contact_sheet(video, c["time"], review_dir / f"missed_M{c['id']:03d}_{fusion.mmss(c['time']).replace(':', '-')}.png")
    print(f"Wrote {len(cands)} review sheets (missed_Mxxx_*.png) to {review_dir}")

    (OUTPUT_DIR / f"{args.name}_event_evidence.txt").write_text("\n".join(out_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
