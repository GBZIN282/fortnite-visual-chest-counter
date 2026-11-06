"""
Sprite-UI cue: the "+75 CONTAINER OPENED" tag next to the sprite badge.

This season, opening a container makes the equipped sprite gain XP, and the HUD
briefly shows a tag beside the sprite badge on the right edge of the screen:

        +75
        CONTAINER OPENED   [sprite badge: Lv. 4]

Two properties matter for how this clue should be used (both measured on the
test clip, see README):

  * It only exists while the sprite is NOT at max level. Once the badge reads
    MAX the tag no longer appears, so it is a CONDITIONAL clue.
  * The text says CONTAINER, not CHEST. It is expected to fire for other
    containers as well, so it is supporting evidence, not proof of a chest.

Detection reuses the visual detector's machinery: a white-text mask, a bitmap
template of the words CONTAINER OPENED, Pearson correlation, hysteresis events.

Usage
-----
    python -m fortnite_chest_counter.detection.sprite            # score video (cached), evaluate
    python -m fortnite_chest_counter.detection.sprite --rescan
"""

import argparse
import subprocess
from pathlib import Path

import numpy as np

from fortnite_chest_counter import paths
from fortnite_chest_counter.detection import visual as V
from fortnite_chest_counter.detection.audio import GROUND_TRUTH_FILE, OUTPUT_DIR, load_ground_truth, match_events, report


# ==================================================================
# PARAMETERS
# ==================================================================

TEMPLATE_FILE = paths.TEMPLATES_DIR / "container_opened.npy"
SCORE_CACHE = OUTPUT_DIR / "sprite_scores.npz"

# ROI in the normalized 1280x720 frame (even values!), left of the sprite badge.
ROI_X, ROI_Y, ROI_W, ROI_H = 1000, 360, 200, 50

# White text mask: every channel bright.
WHITE_MIN = 215

# Template cut from the first chest's tag (51.3 s label + 1.0 s).
TEMPLATE_SOURCE_TIME = 52.3
TEMPLATE_SEARCH_BOX = (1020, 372, 1180, 400)   # x0, y0, x1, y1 where the words sit

EVENT_HIGH_THRESHOLD = 0.75
EVENT_LOW_THRESHOLD = 0.50
SCORE_EVERY_N_FRAMES = 2


def white_mask(frame_rgb):
    return (frame_rgb.min(axis=2) > WHITE_MIN).astype(np.float32)


def load_or_build_template():
    if TEMPLATE_FILE.exists():
        return np.load(TEMPLATE_FILE)
    print(f"Building template from {V.VIDEO_FILE.name} at {TEMPLATE_SOURCE_TIME}s ...")
    frame = V.read_single_frame(V.VIDEO_FILE, TEMPLATE_SOURCE_TIME, crop=False)
    x0, y0, x1, y1 = TEMPLATE_SEARCH_BOX
    mask = white_mask(frame)[y0:y1, x0:x1]
    ys, xs = np.where(mask > 0)
    template = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    TEMPLATE_FILE.parent.mkdir(exist_ok=True)
    np.save(TEMPLATE_FILE, template)
    return template


def score_video(template, rescan=False):
    signature = repr((ROI_X, ROI_Y, ROI_W, ROI_H, WHITE_MIN, SCORE_EVERY_N_FRAMES, template.shape,
                      V.VIDEO_FILE.stat().st_size))
    if SCORE_CACHE.exists() and not rescan:
        cached = np.load(SCORE_CACHE, allow_pickle=False)
        if str(cached["signature"]) == signature:
            print(f"Using cached sprite scores ({SCORE_CACHE}); --rescan to recompute.")
            return cached["times"], cached["scores"]
    fps = V.probe_fps(V.VIDEO_FILE)
    print("Scoring sprite-tag ROI (fast: tiny crop)...")
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(V.VIDEO_FILE), "-vf",
         f"{V.scale_filter()},crop={ROI_W}:{ROI_H}:{ROI_X}:{ROI_Y}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=10 ** 8)
    frame_bytes = ROI_W * ROI_H * 3
    scores, index = [], 0
    while True:
        raw = process.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break
        if index % SCORE_EVERY_N_FRAMES == 0:
            mask = white_mask(np.frombuffer(raw, np.uint8).reshape(ROI_H, ROI_W, 3))
            scores.append(V.best_template_correlation(mask, template)[0] if mask.sum() >= 40 else 0.0)
        index += 1
    times = np.arange(len(scores)) * SCORE_EVERY_N_FRAMES / fps
    scores = np.array(scores, dtype=np.float32)
    OUTPUT_DIR.mkdir(exist_ok=True)
    np.savez(SCORE_CACHE, times=times, scores=scores, signature=signature)
    return times, scores


def event_details(times, scores, events):
    """Raw evidence for each sprite-tag event: peak score within 1 s of the onset."""
    return [{"time": float(t), "score": float(scores[(times >= t) & (times <= t + 1.0)].max())} for t in events]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rescan", action="store_true")
    parser.add_argument("--tolerance", type=float, default=1.5,
                        help="seconds; the tag appears up to ~1 s after the chest label (default 1.5)")
    args = parser.parse_args()

    truth = load_ground_truth(GROUND_TRUTH_FILE)
    template = load_or_build_template()
    print(f"Ground truth ({len(truth)} chests): " + ", ".join(f"{t:.1f}" for t in truth))
    print(f"Template 'CONTAINER OPENED': {template.shape[1]}x{template.shape[0]} px")
    times, scores = score_video(template, args.rescan)
    zeros = np.zeros(len(times), dtype=int)       # no position-jump logic for this cue
    events = V.detect_events(times, scores, zeros, zeros, EVENT_HIGH_THRESHOLD, EVENT_LOW_THRESHOLD)

    print("\nSprite tag events (every one of them):")
    for t in events:
        near = truth[np.argmin(np.abs(truth - t))]
        print(f"  {t:7.2f}s   nearest labelled chest {near:6.1f}s ({t - near:+.2f}s)")
    report(f"SPRITE TAG 'CONTAINER OPENED' (tolerance +/-{args.tolerance}s)", truth, events, args.tolerance)

    print("\nThreshold sweep:")
    for high in (0.5, 0.6, 0.7, 0.8, 0.9):
        ev = V.detect_events(times, scores, zeros, zeros, high, high - 0.25)
        m, _, fp = match_events(truth, ev, args.tolerance)
        print(f"  fire {high:.2f}: events {len(ev):2d}  TP {len(m)}  FP {len(fp)}")


if __name__ == "__main__":
    main()
