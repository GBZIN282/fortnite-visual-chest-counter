"""
Per-frame popup traces for detector research (NOT used at runtime).

Replays the estimator's popup stage over a recording at the live cadence and stores, for every analysed frame:
  t, lit-pixel count, best correlation + position for EACH chest-word template, the ammo-region diff
and, for frames where any template scores >= --keep, the packed popup-colour mask (so template / scale experiments can be
re-scored offline without decoding the video again).

    python research/popup_traces.py --video "samples/video tests/Fortnites-NEW-HD-No-Audio.mp4" --out analysis_output/traces/en.npz
"""

import argparse
from pathlib import Path

import numpy as np

from fortnite_chest_counter.detection import evidence
from fortnite_chest_counter.detection import visual as V
from fortnite_chest_counter.counter import Mp4FrameSource


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--keep", type=float, default=0.40)
    a = ap.parse_args()
    templates = V.load_templates()
    ts, lit, scores, ys, xs, diffs = [], [], [], [], [], []
    kept_idx, kept_masks = [], []
    prev = None
    for i, (t, frame) in enumerate(Mp4FrameSource(a.video, a.fps).frames()):
        roi = frame[V.ROI_Y:V.ROI_Y + V.ROI_H, V.ROI_X:V.ROI_X + V.ROI_W]
        mask = V.lavender_mask(roi)
        n = int(mask.sum())
        sc, yy, xx = [0.0] * len(templates), [0] * len(templates), [0] * len(templates)
        if n >= 20:
            for k, tpl in enumerate(templates):
                s, y, x = V.best_template_correlation(mask, tpl["array"])
                sc[k], yy[k], xx[k] = s, y, x
        x0, y0, x1, y1 = evidence.AMMO_BOX
        am = evidence.white_mask(frame[y0:y1, x0:x1], 200)
        diffs.append(0 if prev is None else int((am ^ prev).sum()))
        prev = am
        ts.append(t); lit.append(n); scores.append(sc); ys.append(yy); xs.append(xx)
        if max(sc) >= a.keep:
            kept_idx.append(i); kept_masks.append(np.packbits(mask.astype(bool)))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, t=np.array(ts), lit=np.array(lit), scores=np.array(scores), ys=np.array(ys), xs=np.array(xs),
                        ammo_diff=np.array(diffs), kept_idx=np.array(kept_idx), kept_masks=np.array(kept_masks),
                        mask_shape=np.array([V.ROI_H, V.ROI_W]), templates=np.array([t["id"] for t in templates]))
    print(f"{a.out}: {len(ts)} frames, {len(kept_idx)} masks kept")


if __name__ == "__main__":
    main()
