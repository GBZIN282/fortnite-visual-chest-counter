"""
EXPERIMENT - not used by the app or the counter. Adaptive, scale-aware pop-up recognition (docs/INVESTIGATION_2026-11-07.md).

Production finds a chest pop-up only when the EXACT binary match of a word template reaches 0.75 at one fixed size. On
streams whose HUD is drawn ~1.2x larger that never happens, although a blurred match at the right scale clearly does.
This variant keeps the production path untouched and adds a second channel beside it:

  stage 1  prefilter: lavender pixels in the pop-up box >= PREFILTER_MIN_PX (production computes this mask anyway)
  stage 2  only then: blurred match (sigma 0.6, as the production compression check) of the RELIABLE word templates
           (en:CHEST) at shrinking scales (the picture made smaller = HUD drawn larger); once two strong matches agree on
           a scale, only that scale and its neighbours are searched
  owner    a blurred onset becomes a pop-up only if the exact path does not fire for the same pop-up within
           SCALED_WAIT seconds - so every exact-path event (incl. back-to-back chests) is exactly as in production
  count    a blurred-only pop-up is merged/finished like any pop-up (prompt merge, shooting, sprite) and then counts
           APPROX ONLY - never CERTAIN - so the meaning of CERTAIN is unchanged

    python research/adaptive_popup.py SOURCE OUT_DIR       (one source per process; see SOURCES)
    python research/adaptive_popup.py --summary OUT_DIR

Every frame is also scored by brute force (all scales, no prefilter) OUTSIDE the timed path, to measure how many
qualifying frames the prefilter would have thrown away.
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))
from fortnite_chest_counter import estimator as E  # noqa: E402
from fortnite_chest_counter import review, settings  # noqa: E402
from fortnite_chest_counter.counter import Mp4FrameSource  # noqa: E402
from fortnite_chest_counter.detection import visual as V  # noqa: E402

BLUR_SCALES = (1.0, 0.9, 0.85, 0.8, 0.75)
TRIGGER, REARM = 0.80, 0.55
PREFILTER_MIN_PX = 60
SCALED_WAIT = 2.0                 # seconds a blurred onset waits for the exact path to claim the same pop-up
LOCK_MIN = 0.84                   # blurred score that counts as a vote for the session's HUD scale
SIGMA = 0.6


def scaled_mask(roi, s, cache):
    if s not in cache:
        r = roi if s == 1.0 else np.asarray(Image.fromarray(roi).resize((round(roi.shape[1] * s), round(roi.shape[0] * s)),
                                                                         Image.BOX))
        cache[s] = V.lavender_mask(r)
    return cache[s]


def blurred_best(roi, scales, templates, cache):
    """-> (score, centre_y, centre_x in 1.0 coordinates, scale, template id)."""
    best = (0.0, 0, 0, 1.0, None)
    for s in scales:
        m = scaled_mask(roi, s, cache)
        if m.sum() < 20:
            continue
        for tid, blur in templates.items():
            score, y, x = V.robust_location(m, blur, SIGMA) if hasattr(V, "robust_location") else _robust_loc(m, blur)
            if score > best[0]:
                h, w = blur.shape
                best = (score, int((y + h // 2) / s), int((x + w // 2) / s), s, tid)
    return best


def _robust_loc(mask, blurred_template):
    """visual.robust_correlation line for line (same score), plus where the best window is."""
    from scipy.ndimage import gaussian_filter
    from scipy.signal import fftconvolve
    img = gaussian_filter(mask.astype(np.float64), SIGMA)
    tpl = blurred_template
    n = tpl.size
    ts = tpl.sum()
    tvar = (tpl * tpl).sum() - ts * ts / n
    ones = np.ones_like(tpl)
    ws = fftconvolve(img, ones, mode="valid")
    ws2 = fftconvolve(img * img, ones, mode="valid")
    num = fftconvolve(img, tpl[::-1, ::-1], mode="valid") - ws * ts / n
    wvar = ws2 - ws * ws / n
    ok = wvar > 5e-4 * n
    corr = np.where(ok, num / np.sqrt(np.maximum(tvar * wvar, 1e-9)), 0.0)
    if not corr.size:
        return 0.0, 0, 0
    y, x = np.unravel_index(np.argmax(corr), corr.shape)
    return float(min(corr[y, x], 1.0)), int(y), int(x)


class AdaptiveEstimator(E.ChestEstimator):
    def __init__(self):
        super().__init__()
        self.reliable = {t["id"]: V.blur_template(t["array"], SIGMA) for t in self.templates
                         if E.APPROX_COUNTS_MEDIUM_ALONE.get(t["id"])}
        self.blur_onset = E.OnsetDetector(TRIGGER, REARM, True)
        self.pending_scaled, self.exact_onsets = [], []
        self.votes, self.locked = Counter(), None
        self.stats = {"frames": 0, "prefilter_pass": 0, "stage2_ms": [], "scaled_onsets": 0, "scaled_dropped_for_exact": 0}
        self.last_best = None

    def active_scales(self):
        if self.locked is None:
            return BLUR_SCALES
        i = BLUR_SCALES.index(self.locked)
        near = {BLUR_SCALES[j] for j in (i - 1, i, i + 1) if 0 <= j < len(BLUR_SCALES)}
        return tuple(s for s in BLUR_SCALES if s in near)

    def _popup(self, t, frame):
        before = len(self.pending_popups)
        super()._popup(t, frame)                                        # production, unchanged
        if len(self.pending_popups) > before:
            self.exact_onsets.append(t)
            dropped = [p for p in self.pending_scaled if p["onset"] >= t - SCALED_WAIT]
            self.stats["scaled_dropped_for_exact"] += len(dropped)
            self.pending_scaled = [p for p in self.pending_scaled if p not in dropped]
        self.stats["frames"] += 1
        if not self.reliable:
            return
        roi = frame[V.ROI_Y:V.ROI_Y + V.ROI_H, V.ROI_X:V.ROI_X + V.ROI_W]
        a = time.perf_counter()
        cache = {}
        best = (0.0, 0, 0, 1.0, None)
        if scaled_mask(roi, 1.0, cache).sum() >= PREFILTER_MIN_PX:     # stage 1 (in production this mask already exists)
            self.stats["prefilter_pass"] += 1
            best = blurred_best(roi, self.active_scales(), self.reliable, cache)
            self.stats["stage2_ms"].append(1000 * (time.perf_counter() - a))
        self.last_best = best
        score, cy, cx, s, tid = best
        for p in self.pending_scaled:                                   # peak over the pop-up's first second
            if t <= p["onset"] + E.POPUP_FINISH_DELAY and score > p["blur"]:
                p.update(blur=score, scale=s, y=cy, x=cx)
        if self.blur_onset.update(t, score, cy, cx):
            if not any(abs(o - t) <= SCALED_WAIT for o in self.exact_onsets) and \
                    not any(abs(p["onset"] - t) <= E.POPUP_FINISH_DELAY for p in self.pending_popups):
                self.pending_scaled.append({"onset": t, "blur": score, "scale": s, "y": cy, "x": cx, "template": tid})
                self.stats["scaled_onsets"] += 1
        for p in list(self.pending_scaled):                             # unclaimed by the exact path -> a real pop-up
            if t >= p["onset"] + SCALED_WAIT:
                self.pending_scaled.remove(p)
                exact_peak = max((h[1] for h in self.popup_hist if p["onset"] <= h[0] <= p["onset"] + E.POPUP_FINISH_DELAY),
                                 default=0.0)
                self.pending_popups.append({"onset": p["onset"], "score": exact_peak, "y": p["y"], "x": p["x"],
                                            "template": p["template"], "scaled": dict(p)})

    def flush(self):
        for p in self.pending_scaled:
            self.pending_popups.append({"onset": p["onset"], "score": 0.0, "y": p["y"], "x": p["x"], "template": p["template"],
                                        "scaled": dict(p)})
        self.pending_scaled = []
        return super().flush()

    def _popup_event(self, p):
        ev = super()._popup_event(p)
        s = p.get("scaled")
        if s:
            ev["scaled_popup"] = {"blur": round(s["blur"], 3), "scale": s["scale"]}
            ev["certain_counted"] = False                               # CERTAIN keeps its meaning
            if not ev["approx_counted"]:
                ev["adjusted_tier"], ev["approx_counted"] = "MEDIUM", True
            ev["reason"] += f"; scale-aware blurred match {s['blur']:.2f} at x{s['scale']}: APPROX only"
            if s["blur"] >= LOCK_MIN:
                self.votes[s["scale"]] += 1
        elif ev.get("popup_score") is not None and ev["popup_score"] >= E.ROBUST_HIGH_MIN:
            self.votes[1.0] += 1                                        # strong exact pop-up = normal HUD size
        if self.votes and self.locked is None:
            (scale, n), *rest = self.votes.most_common()
            if n >= 2 and (not rest or n >= 2 * rest[0][1]):
                self.locked = scale
        return ev


# ---------------------------------------------------------------- runner

CAP = Path(r"C:\Users\gzgab\Downloads\Fortnite-Visual-Chest-Counter\Fortnite-Visual-Chest-Counter-v0.2.0\captures")
SOURCES = {
    "ref_en": ("mp4", ROOT / "samples/video tests/Fortnites-NEW-HD-No-Audio.mp4", "Fortnites-NEW"),
    "ref_en_tw6000": ("mp4", ROOT / "analysis_output/variants/en_tw6000.mp4", "Fortnites-NEW"),
    "ref_en_tw2500": ("mp4", ROOT / "analysis_output/variants/en_tw2500.mp4", "Fortnites-NEW"),
    "ref_ps5": ("mp4", ROOT / "samples/video tests/Fortnite-PS5-Pro-HD-No-Audio.mp4", "Fortnite-PS5-Pro"),
    "ref_ps5_tw6000": ("mp4", ROOT / "analysis_output/variants/ps5_tw6000.mp4", "Fortnite-PS5-Pro"),
    "ref_ps5_tw2500": ("mp4", ROOT / "analysis_output/variants/ps5_tw2500.mp4", "Fortnite-PS5-Pro"),
    "s032230": ("capture", CAP / "20261107_032230", None),
    "s033211": ("capture", CAP / "20261107_033211", None),
    "s034505": ("capture", CAP / "20261107_034505", None),
}
# Pop-ups verified by eye from crops (docs/INVESTIGATION_2026-11-07.md); recording seconds. 033211: completeness unknown.
SESSION_TRUTH = {"s032230": [0.3, 53.5, 58.8, 94.7], "s033211": [188.7, 507.8, 619.0, 689.7], "s034505": [30.5, 115.3, 132.9]}


def segments(kind, path):
    """-> [(offset seconds, frame iterator)]: one segment per clip (a fresh estimator each, as review does)."""
    if kind == "mp4":
        return [(0.0, Mp4FrameSource(path, 15).frames())]
    clips = json.loads((path / "video" / "clips.json").read_text(encoding="utf-8"))
    return [(c["start"], review.frames(path / c["file"], 15)) for c in clips]


def run(name, out):
    kind, path, label_name = SOURCES[name]
    E.configure(settings.DEFAULTS["detector"])
    rows = {"production": [], "adaptive": []}
    timing = {"production": [], "adaptive": []}
    audit = {"qualifying_frames": 0, "rejected_by_prefilter": 0, "rejected_px": []}
    stats = Counter()
    stage2 = []
    locks = []
    for offset, frames in segments(kind, path):
        prod, adap = E.ChestEstimator(), AdaptiveEstimator()
        for t, frame in frames:
            a = time.perf_counter()
            rows["production"] += [dict(e, time=e["time"] + offset) for e in prod.process_frame(t, frame)]
            timing["production"].append(time.perf_counter() - a)
            a = time.perf_counter()
            rows["adaptive"] += [dict(e, time=e["time"] + offset) for e in adap.process_frame(t, frame)]
            timing["adaptive"].append(time.perf_counter() - a)
            # audit (not timed): would the full search, without the prefilter, have reached the trigger here?
            roi = frame[V.ROI_Y:V.ROI_Y + V.ROI_H, V.ROI_X:V.ROI_X + V.ROI_W]
            cache = {}
            full = blurred_best(roi, BLUR_SCALES, adap.reliable, cache)
            if full[0] >= TRIGGER:
                audit["qualifying_frames"] += 1
                px = int(scaled_mask(roi, 1.0, cache).sum())
                if px < PREFILTER_MIN_PX:
                    audit["rejected_by_prefilter"] += 1
                    audit["rejected_px"].append(px)
        rows["production"] += [dict(e, time=e["time"] + offset) for e in prod.flush()]
        rows["adaptive"] += [dict(e, time=e["time"] + offset) for e in adap.flush()]
        for k in ("frames", "prefilter_pass", "scaled_onsets", "scaled_dropped_for_exact"):
            stats[k] += adap.stats[k]
        stage2 += adap.stats["stage2_ms"]
        locks.append(adap.locked)

    def slim(e):
        return {k: e.get(k) for k in ("time", "source", "adjusted_tier", "popup_score", "popup_template", "certain_counted",
                                      "approx_counted", "scaled_popup", "reason")}

    ms = {k: 1000 * np.array(v) for k, v in timing.items()}
    result = {"source": name, "label_name": label_name, "frames": stats["frames"],
              "prefilter_pass_rate": stats["prefilter_pass"] / max(stats["frames"], 1),
              "stage2_ms_mean": float(np.mean(stage2)) if stage2 else 0.0,
              "stage2_ms_max": float(np.max(stage2)) if stage2 else 0.0,
              "frame_ms": {k: {"mean": float(v.mean()), "p99": float(np.percentile(v, 99)), "max": float(v.max())}
                           for k, v in ms.items()},
              "scaled_onsets": stats["scaled_onsets"], "scaled_dropped_for_exact": stats["scaled_dropped_for_exact"],
              "locked_scales": locks, "audit": audit,
              "production": [slim(e) for e in rows["production"]], "adaptive": [slim(e) for e in rows["adaptive"]]}
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / f"{name}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(name, "done")


def summary(out):
    import regress
    lines = []
    for name in SOURCES:
        f = Path(out) / f"{name}.json"
        if not f.exists():
            lines.append(f"{name}: missing")
            continue
        r = json.loads(f.read_text(encoding="utf-8"))

        def cls(t):
            if r["label_name"]:
                return regress.classify(r["label_name"], t)
            truth = SESSION_TRUTH.get(name, [])
            return "REAL" if any(abs(t - x) <= 2.0 for x in truth) else "unchecked"

        def counts(evs):
            c = [e for e in evs if e["certain_counted"]]
            a = [e for e in evs if e["approx_counted"]]
            return len(c), len(a), sum(cls(e["time"]) == "REAL" for e in a), sum(cls(e["time"]) in ("FALSE", "NONCHEST") for e in a)

        p, a = counts(r["production"]), counts(r["adaptive"])
        prod_keys = {(round(e["time"], 1), e["adjusted_tier"], e["certain_counted"], e["approx_counted"]) for e in r["production"]}
        changed = [e for e in r["adaptive"] if (round(e["time"], 1), e["adjusted_tier"], e["certain_counted"], e["approx_counted"])
                   not in prod_keys]
        lost = [e for e in r["production"] if not any(abs(e["time"] - x["time"]) < 0.05 and e["adjusted_tier"] == x["adjusted_tier"]
                                                       and e["approx_counted"] == x["approx_counted"] for x in r["adaptive"])]
        fm = r["frame_ms"]
        lines.append(f"{name:15s} frames {r['frames']:6d} | production C/A {p[0]}/{p[1]} (real {p[2]}, wrong {p[3]}) -> adaptive "
                     f"C/A {a[0]}/{a[1]} (real {a[2]}, wrong {a[3]}) | new/changed {len(changed)}, lost {len(lost)} | "
                     f"prefilter {100 * r['prefilter_pass_rate']:.1f}% of frames, misses {r['audit']['rejected_by_prefilter']}/"
                     f"{r['audit']['qualifying_frames']} qualifying frames | ms/frame prod {fm['production']['mean']:.1f} "
                     f"(p99 {fm['production']['p99']:.1f}, max {fm['production']['max']:.0f}) adaptive {fm['adaptive']['mean']:.1f} "
                     f"(p99 {fm['adaptive']['p99']:.1f}, max {fm['adaptive']['max']:.0f}); stage 2 {r['stage2_ms_mean']:.1f} ms when "
                     f"run | lock {r['locked_scales']}")
        for e in changed:
            lines.append(f"      + {e['time']:7.1f}s [{cls(e['time'])}] {e['adjusted_tier']} C={int(e['certain_counted'])} "
                         f"A={int(e['approx_counted'])} {e.get('scaled_popup')} {e['source']}")
        for e in lost:
            lines.append(f"      - {e['time']:7.1f}s [{cls(e['time'])}] {e['adjusted_tier']} lost/changed")
    text = "\n".join(lines)
    (Path(out) / "summary.txt").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    if sys.argv[1] == "--summary":
        summary(sys.argv[2])
    else:
        run(sys.argv[1], sys.argv[2])
