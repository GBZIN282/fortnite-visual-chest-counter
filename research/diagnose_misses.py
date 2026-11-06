"""
Why did the popup detector miss a chest? Per-frame diagnosis around chosen moments.

For every moment it scores EVERY chest-word template on every frame of the window
(-2 s .. +4 s) and reports the best score, where it was, how long it stayed above the
fire threshold, and which events the real detector emitted nearby. It also writes a
strip of the popup region so the on-screen text can be looked at directly.
Detector settings are only READ; nothing is tuned.

Usage
-----
    python research/diagnose_misses.py --name Fortnite-PS5-Pro --times 11.5 22.0 36.0 78.5 --compare 62.4 182.45 370.57 752.02
"""

import argparse
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from fortnite_chest_counter.detection import visual as V
from fortnite_chest_counter.detection.audio import OUTPUT_DIR

SAMPLES = Path("samples/video tests")
WINDOW = (-2.0, 4.0)


def window_scores(video, start, length, templates):
    """Per-frame (time, {template: (score, y, x)}, mask_lit, roi_frame) for the window."""
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-ss", f"{max(start, 0):.3f}", "-t", f"{length:.3f}", "-i", str(video), "-vf",
         f"{V.scale_filter()},crop={V.ROI_W}:{V.ROI_H}:{V.ROI_X}:{V.ROI_Y}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=10 ** 8)
    fb = V.ROI_W * V.ROI_H * 3
    fps = V.probe_fps(video)
    out, i = [], 0
    while True:
        raw = process.stdout.read(fb)
        if len(raw) < fb:
            break
        frame = np.frombuffer(raw, np.uint8).reshape(V.ROI_H, V.ROI_W, 3)
        mask = V.lavender_mask(frame)
        per = {}
        for t in templates:
            per[t["id"]] = V.best_template_correlation(mask, t["array"]) if mask.sum() >= 20 else (0.0, 0, 0)
        out.append((max(start, 0) + i / fps, per, int(mask.sum()), frame))
        i += 1
    return out


def diagnose(label, video, center, templates, events, high, strip_path):
    rows = window_scores(video, center + WINDOW[0], WINDOW[1] - WINDOW[0], templates)
    ids = [t["id"] for t in templates]
    print(f"\n=== {label}  @ {center:.2f}s  (window {center + WINDOW[0]:.1f}..{center + WINDOW[1]:.1f}s) ===")
    for tid in ids:
        sc = np.array([r[1][tid][0] for r in rows])
        k = int(np.argmax(sc))
        above = int((sc >= high).sum())
        print(f"  {tid:9s} peak {sc[k]:.2f} at {rows[k][0]:.2f}s (rel {rows[k][0] - center:+.2f}s) "
              f"pos(y={rows[k][1][tid][1]}, x={rows[k][1][tid][2]})  frames >= {high}: {above}  frames >= 0.60: {int((sc >= 0.60).sum())}")
    # mask quality at the best Portuguese match: does the mask keep the word's pixels, and do
    # other lit pixels (neighbouring text lines, glow) contaminate the match window?
    pt = next(t for t in templates if t["id"].startswith("pt"))
    sc_pt = np.array([r[1][pt["id"]][0] for r in rows])
    kb = int(np.argmax(sc_pt))
    _, y, x = rows[kb][1][pt["id"]]
    frame = rows[kb][3]
    mask = V.lavender_mask(frame)
    th, tw = pt["array"].shape
    window = mask[y:y + th, x:x + tw]
    kept = float((window * pt["array"]).sum() / pt["array"].sum())
    extra = int((window * (1 - pt["array"])).sum())
    above = int(mask[max(y - 8, 0):y, x - 6:x + tw + 30].sum())          # neighbouring line above
    r_, g_, b_ = frame[y:y + th, x:x + tw][pt["array"] > 0].reshape(-1, 3).mean(axis=0)
    relaxed = ((np.minimum(frame[..., 0], frame[..., 2]).astype(int) > V.MASK_MIN_RED_BLUE)
               & (frame[..., 1].astype(int) < np.minimum(frame[..., 0], frame[..., 2]).astype(int) - 0))[y:y + th, x:x + tw]
    kept_relaxed = float((relaxed * pt["array"]).sum() / pt["array"].sum())
    print(f"  mask at best pt frame ({rows[kb][0] - center:+.2f}s): template pixels kept {kept:.0%} "
          f"(with G-margin 0 instead of {V.MASK_GREEN_BELOW}: {kept_relaxed:.0%}), extra lit pixels in window {extra}, "
          f"lit pixels in the line above {above}, mean RGB at word pixels ({r_:.0f},{g_:.0f},{b_:.0f})")
    lit = np.array([r[2] for r in rows])
    print(f"  lavender text pixels in popup ROI: median {int(np.median(lit))}, max {int(lit.max())}")
    near = [e for e in events if center + WINDOW[0] <= e <= center + WINDOW[1]]
    print("  popup-detector events inside the window: " + (", ".join(f"{e:.2f}s" for e in near) or "none"))

    # strip: popup ROI every 0.5 s with the best template score
    picks = list(range(0, len(rows), max(int(0.5 * V.probe_fps(video)), 1)))[:12]
    fig, axes = plt.subplots(2, 6, figsize=(24, 6))
    for ax, i in zip(axes.ravel(), picks):
        best = max(ids, key=lambda tid: rows[i][1][tid][0])
        ax.imshow(rows[i][3]); ax.axis("off")
        ax.set_title(f"{rows[i][0] - center:+.1f}s  {best} {rows[i][1][best][0]:.2f}", fontsize=10)
    for ax in axes.ravel()[len(picks):]:
        ax.axis("off")
    fig.suptitle(f"{label} @ {center:.2f}s: popup region (x 716..1076, y 158..360)", fontsize=12)
    plt.tight_layout()
    plt.savefig(strip_path, dpi=50)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="Fortnite-PS5-Pro")
    parser.add_argument("--times", type=float, nargs="+", required=True, help="moments to diagnose (seconds)")
    parser.add_argument("--compare", type=float, nargs="*", default=[], help="popup-detected chests for comparison")
    args = parser.parse_args()

    video = SAMPLES / f"{args.name}-HD-No-Audio.mp4"
    V.VIDEO_FILE = video
    V.SCORE_CACHE = OUTPUT_DIR / f"{args.name}_visual_scores.npz"
    templates = V.load_templates()
    cached = np.load(V.SCORE_CACHE, allow_pickle=False)
    events = V.detect_events(cached["times"], cached["scores"], cached["ys"], cached["xs"])
    print(f"Detector: fire >= {V.EVENT_HIGH_THRESHOLD}, re-arm < {V.EVENT_LOW_THRESHOLD}; {len(events)} events in the whole video")
    out = OUTPUT_DIR / f"{args.name}_diagnosis"
    out.mkdir(exist_ok=True)
    for t in args.times:
        diagnose("MISSED", video, t, templates, events, V.EVENT_HIGH_THRESHOLD, out / f"missed_{t:07.2f}.png")
    for t in args.compare:
        diagnose("DETECTED (comparison)", video, t, templates, events, V.EVENT_HIGH_THRESHOLD, out / f"detected_{t:07.2f}.png")


if __name__ == "__main__":
    main()
