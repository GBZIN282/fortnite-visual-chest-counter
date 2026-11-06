"""
Blind prediction on a recording that has NO ground truth.

Runs the existing clue detectors UNCHANGED (popup, sprite tag, audio), groups
them with fusion.py's logic, and writes a review file plus contact sheets so a
person can verify each prediction. It computes no accuracy: there are no labels.

Everything learned from the first clip is fixed:
  * templates/chest/<lang>/*.npy      (visual_detector.py: en CHEST, pt BAÚ)
  * templates/container_opened.npy    (sprite_detector.py)
  * templates/audio_fingerprint.npy   (built ONCE from the first clip's labels)
  * every threshold / weight / window  (module constants, not touched here)

The only thing that differs from the labelled-clip workflow is that the audio
fingerprint comes from the first clip instead of from this clip's labels,
because this clip has none.

Files expected in samples/video tests/:
    <name>-Low.mp4            video with audio  (audio detector)
    <name>-HD-No-Audio.mp4    same recording, no audio  (visual detectors)

Outputs:
    samples/video tests/<name>-predicted-chests.txt   (UNVERIFIED predictions)
    analysis_output/<name>_review/event_NNN_mm-ss.xx.png

Usage
-----
    python -m fortnite_chest_counter.detection.predict --name Fortnite-PS5-Pro
"""

import argparse
import subprocess
from pathlib import Path

import numpy as np

from fortnite_chest_counter import paths
from fortnite_chest_counter.detection import audio as detector
from fortnite_chest_counter.detection import fusion
from fortnite_chest_counter.detection import sprite as sprite_detector
from fortnite_chest_counter.detection import visual as V

SAMPLES = Path("samples/video tests")
AUDIO_FINGERPRINT_FILE = paths.TEMPLATES_DIR / "audio_fingerprint.npy"


def mmss(seconds):
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes):02d}:{rest:05.2f}"


# ==================================================================
# INPUT COMPATIBILITY
# ==================================================================

def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height,r_frame_rate,sample_rate,channels:format=duration",
         "-of", "default=nw=1", str(path)], capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)


def tiny_gray_frames(path, fps=4):
    """Whole video as 64x36 grayscale frames at `fps` -> (n, 36, 64) float32."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", f"fps={fps},scale=64:36",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 36, 64).astype(np.float32)


def check_sync(low_path, hd_path, fps=4, max_lag_seconds=3):
    """
    Are the two videos the same recording and aligned in time?
    1. Per-frame image correlation at lag 0 (same picture?).
    2. Cross-correlation of frame-to-frame motion energy over +/- max_lag.
    """
    a, b = tiny_gray_frames(low_path, fps), tiny_gray_frames(hd_path, fps)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    flat_a, flat_b = a.reshape(n, -1), b.reshape(n, -1)
    za = (flat_a - flat_a.mean(1, keepdims=True)) / (flat_a.std(1, keepdims=True) + 1e-6)
    zb = (flat_b - flat_b.mean(1, keepdims=True)) / (flat_b.std(1, keepdims=True) + 1e-6)
    per_frame = (za * zb).mean(1)
    motion_a = np.abs(np.diff(a, axis=0)).mean((1, 2))
    motion_b = np.abs(np.diff(b, axis=0)).mean((1, 2))
    max_lag = int(max_lag_seconds * fps)
    lags = range(-max_lag, max_lag + 1)
    corr = []
    for lag in lags:
        x, y = (motion_a[lag:], motion_b[:len(motion_b) - lag]) if lag >= 0 else (motion_a[:lag], motion_b[-lag:])
        m = min(len(x), len(y))
        corr.append(np.corrcoef(x[:m], y[:m])[0, 1])
    best = list(lags)[int(np.argmax(corr))] / fps
    return {"frames_compared": n, "median_image_corr": float(np.median(per_frame)),
            "min_image_corr": float(per_frame.min()), "best_motion_lag_s": best,
            "motion_corr_at_best": float(np.max(corr)), "motion_corr_at_zero": float(corr[max_lag])}


# ==================================================================
# CLUES (unchanged detectors, per-clip files/caches)
# ==================================================================

def ensure_audio_fingerprint():
    """Build the fingerprint ONCE from the first (labelled) clip and cache it."""
    if AUDIO_FINGERPRINT_FILE.exists():
        return np.load(AUDIO_FINGERPRINT_FILE)
    print("Building audio fingerprint from the first (labelled) clip...")
    truth = detector.load_ground_truth(detector.GROUND_TRUTH_FILE)
    _, _, _, fingerprint = detector.audio_chest_events(truth)
    AUDIO_FINGERPRINT_FILE.parent.mkdir(exist_ok=True)
    np.save(AUDIO_FINGERPRINT_FILE, fingerprint)
    return fingerprint


def popup_clue(rescan):
    templates = V.load_templates()
    times, scores, ys, xs, which = V.score_video(templates, rescan)
    events = V.detect_events(times, scores, ys, xs)
    detail = V.popup_event_details(times, scores, ys, xs, which, templates, events)
    return times, scores, events, detail, which, templates


def sprite_clue(rescan):
    template = sprite_detector.load_or_build_template()
    times, scores = sprite_detector.score_video(template, rescan)
    zeros = np.zeros(len(times), dtype=int)
    events = V.detect_events(times, scores, zeros, zeros,
                             sprite_detector.EVENT_HIGH_THRESHOLD, sprite_detector.EVENT_LOW_THRESHOLD)
    return times, scores, events, sprite_detector.event_details(times, scores, events)


# ==================================================================
# REVIEW OUTPUT
# ==================================================================

def make_contact_sheet(hd_path, t, path):
    start = max(t - 1.0, 0)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", "3.0", "-i", str(hd_path),
         "-vf", "fps=4,scale=426:-1,tile=4x3", "-frames:v", "1", str(path)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="Fortnite-PS5-Pro")
    parser.add_argument("--rescan", action="store_true")
    parser.add_argument("--no-sheets", action="store_true")
    args = parser.parse_args()

    low = SAMPLES / f"{args.name}-Low.mp4"
    hd = SAMPLES / f"{args.name}-HD-No-Audio.mp4"
    wav = SAMPLES / f"{args.name}-Low.wav"
    out_txt = SAMPLES / f"{args.name}-predicted-chests.txt"
    review_dir = detector.OUTPUT_DIR / f"{args.name}_review"
    for p in (low, hd):
        if not p.exists():
            raise FileNotFoundError(p.resolve())

    # ---- 0. fixed audio fingerprint from the first clip (before switching files) ----
    fingerprint = ensure_audio_fingerprint()

    # ---- 1. compatibility ----
    print(f"=== INPUT COMPATIBILITY: {args.name} ===")
    info_low, info_hd = probe(low), probe(hd)
    print(f"Low : {info_low.get('width')}x{info_low.get('height')}  fps {info_low.get('r_frame_rate')}  "
          f"duration {float(info_low['duration']):.2f}s  audio {info_low.get('channels')}ch @ {info_low.get('sample_rate')} Hz")
    print(f"HD  : {info_hd.get('width')}x{info_hd.get('height')}  fps {info_hd.get('r_frame_rate')}  "
          f"duration {float(info_hd['duration']):.2f}s")
    sync = check_sync(low, hd)
    print(f"Sync: {sync['frames_compared']} frames compared at 4 fps; median image correlation "
          f"{sync['median_image_corr']:.3f} (min {sync['min_image_corr']:.3f}); best motion lag "
          f"{sync['best_motion_lag_s']:+.2f}s (corr {sync['motion_corr_at_best']:.3f}, at 0 lag {sync['motion_corr_at_zero']:.3f})")

    # ---- 2. point the detectors at this clip (files and caches only) ----
    detector.VIDEO_FILE, detector.AUDIO_FILE = low, wav
    V.VIDEO_FILE = hd
    V.SCORE_CACHE = detector.OUTPUT_DIR / f"{args.name}_visual_scores.npz"
    sprite_detector.SCORE_CACHE = detector.OUTPUT_DIR / f"{args.name}_sprite_scores.npz"
    detector.OUTPUT_DIR.mkdir(exist_ok=True)

    # ---- 3. clues ----
    print("\n=== CLUES (detectors unchanged) ===")
    p_times, p_scores, popup_events, popup_detail, p_which, templates = popup_clue(args.rescan)
    s_times, s_scores, sprite_events, sprite_detail = sprite_clue(args.rescan)
    audio_events, cand_times, audio_scores, _ = detector.audio_chest_events(fingerprint=fingerprint)
    duration = float(info_low["duration"])

    print(f"\nCHEST popup events: {len(popup_events)}")
    for d in popup_detail:
        print(f"  {mmss(d['time'])}  score {d['score']:.2f}  template {d['template']}  match centre at (y={d['y']}, x={d['x']}) in ROI")
    for t in templates:
        n = sum(d["template"] == t["id"] for d in popup_detail)
        print(f"  detections by template {t['id']}: {n}")
    print("Popup score distribution over whole video (50/90/99/99.9 pct): "
          + " / ".join(f"{p:.2f}" for p in np.percentile(p_scores, [50, 90, 99, 99.9]))
          + "   [first clip: 0.00 / 0.40 / 0.77 / 0.91]")
    zero_pos = np.zeros(len(p_times), dtype=int)
    for thr in (0.65, 0.80):
        n = len(V.detect_events(p_times, p_scores, zero_pos, zero_pos, thr, thr - 0.25))
        print(f"  (diagnostic only) events if fire threshold were {thr}: {n}")

    # highest score peaks that did NOT become events (diagnostic only)
    from scipy.signal import find_peaks
    peaks, _ = find_peaks(p_scores, height=0.5, distance=int(2.0 * len(p_times) / duration))
    others = sorted(((p_scores[i], p_times[i], templates[int(p_which[i])]["id"]) for i in peaks
                     if len(popup_events) == 0 or np.min(np.abs(popup_events - p_times[i])) > 2.0), reverse=True)[:8]
    print("Highest NON-event score peaks (diagnostic): "
          + ", ".join(f"{sc:.2f}@{mmss(t)}({tid})" for sc, t, tid in others))

    print(f"\nSprite 'CONTAINER OPENED' events: {len(sprite_events)}")
    for d in sprite_detail:
        print(f"  {mmss(d['time'])}  score {d['score']:.2f}")

    print(f"\nAudio: {len(cand_times)} burst candidates, {len(audio_events)} accepted "
          f"(similarity >= {detector.SIMILARITY_THRESHOLD}) = {len(audio_events) / (duration / 60):.1f}/min "
          f"[first clip: 46 accepted in 8.5 min = 5.4/min]")
    print("Candidate similarity percentiles (50/90/99): "
          + " / ".join(f"{p:.2f}" for p in np.percentile(audio_scores, [50, 90, 99])))

    # ---- 4. fusion (unchanged grouping/decisions) + confidence tiers ----
    clues = {"popup": popup_events, "sprite": sprite_events, "audio": audio_events}
    groups = fusion.group_clues(clues)
    rows = fusion.describe_groups(groups, popup_detail, sprite_detail)
    for i, r in enumerate(rows, 1):
        r["id"] = i          # permanent chronological id (deterministic for a given video)
    ignored = len(groups) - len(rows)
    n_count = sum(r["decision"] == "COUNT" for r in rows)
    n_cand = sum(r["decision"] == "CANDIDATE" for r in rows)
    print(f"\n=== FUSION: {n_count} COUNT, {n_cand} CANDIDATE, {ignored} ignored weak groups ===")
    for r in rows:
        print("  " + fusion.format_row(r) + f"   [{r['rule']}]")
    print("\n" + fusion.tier_distribution(rows))
    near = sum(any(abs(a - e) <= 1.0 for a in audio_events) for e in popup_events)
    print(f"\n(diagnostic, not accuracy) popup events with an accepted audio event within 1 s: {near} of {len(popup_events)}")

    # ---- 5. review file (predictions only; NOT ground truth) ----
    # Never lose a reviewer's work: VERIFIED values are carried over by timestamp from the
    # permanent reviewed copy (<name>-verified-predictions.txt), which this script never writes.
    verified_copy = SAMPLES / f"{args.name}-verified-predictions.txt"
    carried = fusion.load_verified_labels(verified_copy) if verified_copy.exists() else {}
    lines = ["# AUTO-GENERATED — UNVERIFIED",
             "# Generated from detector output.",
             "# Review manually before using as ground truth.",
             "#",
             "# Confidence is an EVIDENCE TIER (CERTAIN / HIGH / MEDIUM / LOW), not a probability.",
             "# Raw scores are kept so the tiers can be calibrated after verification.",
             "# Each row has a permanent id (#NNN) shared with the review sheet filename event_NNN_*.png.",
             "# To review: edit VERIFIED= to VERIFIED=YES or VERIFIED=NO. Do not rename columns.",
             "# A row that starts '#NNN ' is data; a line starting '# ' is a comment.",
             "#",
             "# Format:",
             "# #id  timestamp    decision    confidence    fused-score    popup-score    template    clues    verified    # rule",
             ""]
    for r in rows:
        popup = f"{r['popup_score']:.2f}" if r["popup_score"] is not None else "-"
        stamp = mmss(r["time"])
        verdict = {True: "YES", False: "NO"}.get(carried.get(stamp), "")
        lines.append(f"#{r['id']:03d}  {stamp}    {r['decision']:9s}  {r['tier']:9s}  {r['fused']:.2f}    {popup}    "
                     f"{r['template']}    {r['clues']}    VERIFIED={verdict}    # {r['rule']}")
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out_txt}  ({len(carried)} reviewed labels carried over from {verified_copy.name})")

    if not args.no_sheets:
        review_dir.mkdir(parents=True, exist_ok=True)
        for old in review_dir.glob("event_*.png"):
            old.unlink()
        for i, r in enumerate(rows, 1):
            make_contact_sheet(hd, r["time"], review_dir / f"event_{i:03d}_{mmss(r['time']).replace(':', '-')}_{r['tier']}.png")
        print(f"Wrote {len(rows)} review contact sheets to {review_dir} (frames every 0.25 s, -1.0 s to +2.0 s)")


if __name__ == "__main__":
    main()
