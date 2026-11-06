"""
Research: score the popup under several candidate matching schemes in ONE decoding pass, for clean and degraded videos.

All schemes use the same ROI and the same templates as the live estimator. `ncc` is a general zero-mean normalized
cross-correlation that is exactly equal to the shipped `best_template_correlation` for 0/1 inputs, but is also valid for
graded / blurred inputs (the shipped formula assumes sum(x^2) == sum(x), i.e. binary pixels).

  base      shipped detector: binary lavender mask x binary template
  blur04    mask and template both Gaussian-blurred, sigma 0.4 px
  blur06    mask and template both Gaussian-blurred, sigma 0.6 px   (tolerates sub-pixel smear from compression/resampling)
  blur08    same, sigma 0.8 px
  soft      graded lavender-ness mask x binary template                (no hard colour cut to flip under chroma bleed)
  softb06   graded mask + blur 0.6, blurred template

    python research/score_variants.py --video X.mp4 --out analysis_output/traces/v_en.npz
"""
import argparse

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.signal import fftconvolve

from fortnite_chest_counter.counter import Mp4FrameSource
from fortnite_chest_counter.detection import visual as V

NAMES = ["base", "blur04", "blur06", "blur08", "soft", "softb06"]


def ncc(img, tpl):
    img = img.astype(np.float64); tpl = tpl.astype(np.float64)
    """General zero-mean NCC, best value over all valid positions."""
    n = tpl.size
    ts = tpl.sum()
    tvar = (tpl * tpl).sum() - ts * ts / n
    ones = np.ones_like(tpl)
    ws = fftconvolve(img, ones, mode="valid")
    ws2 = fftconvolve(img * img, ones, mode="valid")
    num = fftconvolve(img, tpl[::-1, ::-1], mode="valid") - ws * ts / n
    wvar = ws2 - ws * ws / n
    ok = wvar > 1e-2 * n * 0.05                         # windows with (almost) no variation cannot match a glyph
    corr = np.where(ok, num / np.sqrt(np.maximum(tvar * wvar, 1e-9)), 0.0)
    return float(min(corr.max(), 1.0))


def soft_mask(roi):
    r = roi[..., 0].astype(np.float32); g = roi[..., 1].astype(np.float32); b = roi[..., 2].astype(np.float32)
    m = np.minimum(r, b)
    bright = np.clip((m - (V.MASK_MIN_RED_BLUE - 25)) / 50.0, 0, 1)          # ramps in around the 170 cut
    tint = np.clip((m - g - (V.MASK_GREEN_BELOW - 6)) / 12.0, 0, 1)           # ramps in around the 8 cut
    return bright * tint


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--video", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tpls = [t["array"].astype(np.float32) for t in V.load_templates()]
    pad = lambda t: np.pad(t, 2)                       # room for the blur to spread
    tb = {sg: [gaussian_filter(pad(t), sg) for t in tpls] for sg in (0.4, 0.6, 0.8)}
    out, ts = [], []
    for t, frame in Mp4FrameSource(a.video, 15).frames():
        roi = frame[V.ROI_Y:V.ROI_Y + V.ROI_H, V.ROI_X:V.ROI_X + V.ROI_W]
        mb = V.lavender_mask(roi)
        row = np.zeros((len(NAMES), len(tpls)), np.float32)
        if mb.sum() >= 20:
            ms = soft_mask(roi)
            mbs = {sg: gaussian_filter(mb, sg) for sg in (0.4, 0.6, 0.8)}
            ms06 = gaussian_filter(ms, 0.6)
            for k in range(len(tpls)):
                row[0, k] = V.best_template_correlation(mb, tpls[k])[0]
                row[1, k] = ncc(mbs[0.4], tb[0.4][k])
                row[2, k] = ncc(mbs[0.6], tb[0.6][k])
                row[3, k] = ncc(mbs[0.8], tb[0.8][k])
                row[4, k] = ncc(ms, tpls[k])
                row[5, k] = ncc(ms06, tb[0.6][k])
        out.append(row); ts.append(t)
    np.savez_compressed(a.out, t=np.array(ts), s=np.array(out), names=np.array(NAMES))
    print(a.out, len(ts))


if __name__ == "__main__":
    main()
