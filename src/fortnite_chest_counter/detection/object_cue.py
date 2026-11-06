"""
Chest-object evidence around an interaction prompt, and a second independent
missed-chest search.

The interaction prompt (round button icon) appears for ANY container or pickup, so it
cannot say "chest". But a chest is highlighted with a GOLD outline and carries PURPLE
gems, while e.g. an ammo crate is an olive-green box with a white outline. Around the
located prompt we measure, in a fixed box on the object's side of the prompt:

    gold share     bright yellow-gold outline / glow pixels
    gem share      purple gem pixels
    olive share    olive-green crate pixels (background foliage also counts - weak)
    white share    near-white outline pixels

Raw values are always reported. "chest-like" below is only a PROVISIONAL flag taken from
the observed range (13 verified chests had gold >= 0.47% or gems >= 0.05%; the one ammo
crate had 0 of both). With a single negative example this is NOT calibrated.

Nothing here changes the popup detector, thresholds, base tiers or labels.

Usage
-----
    python -m fortnite_chest_counter.detection.object_cue --name Fortnite-PS5-Pro
"""

import argparse
import re
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from fortnite_chest_counter.detection import evidence
from fortnite_chest_counter.detection import fusion
from fortnite_chest_counter.detection import predict
from fortnite_chest_counter.detection import refine
from fortnite_chest_counter.detection import visual as V
from fortnite_chest_counter.detection.audio import OUTPUT_DIR

SAMPLES = Path("samples/video tests")

CANDIDATE_PROMPT_MIN = 0.60          # looser than refine.py's 0.70: the object cue now does the filtering
CHEST_GOLD_MIN = 0.004               # 0.4% of the object box (provisional, see module docstring)
CHEST_GEM_MIN = 0.0005               # 0.05%
OBJECT_BOX = (-250, -10, -110, 60)   # x0, x1, y0, y1 relative to the prompt centre


def object_features(frame, y, x):
    x0, x1, y0, y1 = OBJECT_BOX
    crop = frame[max(y + y0, 0):min(y + y1, 720), max(x + x0, 0):max(x + x1, 1)].astype(int)
    r, g, b = crop[..., 0], crop[..., 1], crop[..., 2]
    n = crop.shape[0] * crop.shape[1]
    return {
        "gold": float(((r > 200) & (g > 165) & (b < 130) & (r - b > 90)).sum() / n),
        "gem": float(((r > 150) & (b > 170) & (g < 130) & (b - g > 70)).sum() / n),
        "olive": float(((abs(r - g) < 30) & (g > b + 25) & (r < 150) & (g < 150) & (g > 70)).sum() / n),
        "white": float(((r > 225) & (g > 225) & (b > 225)).sum() / n),
    }


def best_prompt_frame(video, t):
    """Of the frames at t-0.5, t, t+0.5, the one with the strongest prompt -> (score, y, x, frame)."""
    best = None
    for dt in (-0.5, 0.0, 0.5):
        frame = V.read_single_frame(video, max(t + dt, 0), crop=False)
        score, y, x = evidence.locate_prompt(frame)
        if best is None or score > best[0]:
            best = (score, y, x, frame)
    return best


def chest_like(f):
    return f["gold"] >= CHEST_GOLD_MIN or f["gem"] >= CHEST_GEM_MIN


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="Fortnite-PS5-Pro")
    args = parser.parse_args()
    video = SAMPLES / f"{args.name}-HD-No-Audio.mp4"

    rows = refine.parse_predictions(SAMPLES / f"{args.name}-predicted-chests.txt")
    labels = fusion.load_verified_labels(SAMPLES / f"{args.name}-verified-predictions.txt")
    missed = fusion.load_verified_labels(SAMPLES / f"{args.name}-verified-missed-candidates.txt")
    cues = evidence.extract_cues(video, OUTPUT_DIR / f"{args.name}_cues.npz")
    gray_t, gray_s = evidence.extract_prompt_gray(video, OUTPUT_DIR / f"{args.name}_prompt_gray.npz")

    # ---- known chests / containers (verified) ----
    # windows in which a prompt belongs to a known event: popup chests -3..+1 s around the popup;
    # missed chests -3..+4 s around the candidate (their popups came 1-3 s later); ammo crate +/-3 s.
    known = []
    for r in rows:
        if labels.get(r["stamp"]):
            known.append(("chest(popup)", r["time"], -3.0, 1.0))
    ammo_crates = []
    for stamp, real in missed.items():
        m, sec = stamp.split(":")
        t = int(m) * 60 + float(sec)
        if real:
            known.append(("chest(missed)", t, -3.0, 4.0))
        else:
            ammo_crates.append(t)
    print(f"Known: {sum(k[0] == 'chest(popup)' for k in known)} popup-detected chests + "
          f"{sum(k[0] == 'chest(missed)' for k in known)} verified missed chests = {len(known)} real chests; "
          f"{len(ammo_crates)} verified non-chest container(s)")

    # ---- table: object features at the verified moments ----
    print("\nObject features at the prompt (raw values; gold/gem/olive/white = % of the object box):")
    print(f"  {'what':14s} {'time':>8s} {'prompt':>6s} {'gold%':>6s} {'gem%':>5s} {'olive%':>6s} {'white%':>6s}  chest-like")
    for kind, t, a, b in [(k[0], k[1], k[2], k[3]) for k in known] + [("AMMO CRATE", t, -3.0, 3.0) for t in ammo_crates]:
        # prompt time = strongest 2 fps prompt score inside the event's window
        window = (gray_t >= t + a) & (gray_t <= t + b)
        tp = float(gray_t[window][np.argmax(gray_s[window])]) if window.any() else t
        score, y, x, frame = best_prompt_frame(video, tp)
        f = object_features(frame, y, x)
        print(f"  {kind:14s} {fusion.mmss(t):>8s} {score:6.2f} {f['gold'] * 100:6.2f} {f['gem'] * 100:5.2f} "
              f"{f['olive'] * 100:6.2f} {f['white'] * 100:6.2f}  {'YES' if chest_like(f) else 'no'}")

    # ---- sensitivity of the prompt generator on the known chests ----
    hit = 0
    for kind, t, a, b in known:
        window = (gray_t >= t + a) & (gray_t <= t + b)
        hit += bool(window.any() and gray_s[window].max() >= CANDIDATE_PROMPT_MIN)
    print(f"\nPrompt generator (>= {CANDIDATE_PROMPT_MIN}) has a prompt near {hit}/{len(known)} known chests")

    # ---- second independent candidate search ----
    peaks, _ = find_peaks(gray_s, height=CANDIDATE_PROMPT_MIN, distance=int(6 * evidence.PROMPT_GRAY_FPS))
    cands = []
    for i in peaks:
        tp = float(gray_t[i])
        if any(t + a <= tp <= t + b for _, t, a, b in known) or any(abs(tp - t) <= 3.0 for t in ammo_crates):
            continue
        score, y, x, frame = best_prompt_frame(video, tp)
        f = object_features(frame, y, x)
        steps = evidence.ammo_steps(cues, tp, (-1.0, 1.0))
        post = evidence.gold_mean(cues, tp, (0.0, 2.0)) - evidence.gold_mean(cues, tp, (-1.0, 0.0))
        clues = ["prompt"]
        if chest_like(f):
            clues.append("chest-object")
        if f["gold"] >= 0.02:
            clues.append("gold-glow")
        if post >= 0.05:
            clues.append("loot-burst?")
        if steps >= evidence.SHOOTING_MIN_STEPS:
            clues.append("SHOOTING(neg)")
        cands.append({"time": tp, "prompt": float(gray_s[i]), "obj": f, "steps": steps, "post": post,
                      "chest_like": chest_like(f), "clues": ",".join(clues)})

    print(f"\nSecond independent search: {len(cands)} new moments (prompt >= {CANDIDATE_PROMPT_MIN}, "
          f"not near any verified chest or the ammo crate)")
    out = ["# AUTO-GENERATED — UNVERIFIED",
           "# Second independent search for chests missed by BOTH the popup path and the first candidate search.",
           "# Moments with an interaction prompt (>= %.2f) that are not near a verified chest or the verified ammo crate." % CANDIDATE_PROMPT_MIN,
           "# 'chest-object' = gold outline / purple gems around the prompt target (provisional, uncalibrated).",
           "# These are NOT chests until verified. To review: edit VERIFIED= to VERIFIED=YES or VERIFIED=NO.",
           "#",
           "# Format:",
           "# #id  timestamp    prompt    gold%    gem%    clues    verified    # note",
           ""]
    # Never wipe a reviewer's work: labels already typed into the output file (or a reviewed copy
    # named <name>-verified-new-candidates.txt) are carried over by timestamp.
    carried = {}
    out_path = SAMPLES / f"{args.name}-new-chest-candidates.txt"
    for source in (out_path, SAMPLES / f"{args.name}-verified-new-candidates.txt"):
        if source.exists():
            carried.update(fusion.load_verified_labels(source))
    for k, c in enumerate(cands, 1):
        c["id"] = k
        stamp = fusion.mmss(c["time"])
        verdict = {True: "YES", False: "NO"}.get(carried.get(stamp), "")
        note = "chest-like object near prompt" if c["chest_like"] else "no chest-like object near prompt (generic container / pickup?)"
        line = (f"#N{k:03d}  {stamp}    {c['prompt']:.2f}    {c['obj']['gold'] * 100:.2f}    {c['obj']['gem'] * 100:.2f}    "
                f"{c['clues']}    VERIFIED={verdict}    # {note}")
        out.append(line)
        print("  " + line)
    path = SAMPLES / f"{args.name}-new-chest-candidates.txt"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {path}")

    review_dir = OUTPUT_DIR / f"{args.name}_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    for old in review_dir.glob("new_*.png"):
        old.unlink()
    for c in cands:
        predict.make_contact_sheet(video, c["time"], review_dir / f"new_N{c['id']:03d}_{fusion.mmss(c['time']).replace(':', '-')}.png")
    print(f"Wrote {len(cands)} review sheets (new_Nxxx_*.png) to {review_dir}")


if __name__ == "__main__":
    main()
