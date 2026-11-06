"""
Offline Fortnite chest-opening detector experiment.

Works ONLY on captured media (a video/WAV file). No game interaction.

Pipeline
--------
1. Extract mono audio from the video with FFmpeg (cached as WAV).
2. Baseline detector: RMS loudness peaks (the original experiment).
3. Chest-specific detector:
     a) candidate generator - sudden rises in the 4-11 kHz band, measured
        RELATIVE to the local background (so absolute volume matters less)
     b) verifier - cosine similarity between the candidate's 11-band
        spectral shape and a reference fingerprint built from the labelled
        chests
4. Score both against ground-truth timestamps (one-to-one matching).
5. Cross-validated (leave-one-chest-out) similarity, because with only five
   labelled chests an in-sample score is optimistic.
6. Plots (saved to analysis_output/, optionally shown).

Usage
-----
    python -m fortnite_chest_counter.detection.audio                       # full run, shows plots
    python -m fortnite_chest_counter.detection.audio --no-show             # just save PNGs
    python -m fortnite_chest_counter.detection.audio --zoom 45 90          # zoom the timeline plot
    python -m fortnite_chest_counter.detection.audio --tolerance 1.0
"""

import argparse
import subprocess
from pathlib import Path

import importlib

import numpy as np
from scipy.signal import find_peaks


class _LazyModule:
    """Import a heavy, analysis-only module (librosa, matplotlib) on first use, so the live counter
    and the packaged app never load it."""

    def __init__(self, name):
        self._name, self._module = name, None

    def __getattr__(self, attr):
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return getattr(self._module, attr)


librosa = _LazyModule("librosa")
matplotlib = _LazyModule("matplotlib")


# ==================================================================
# FILES
# ==================================================================

VIDEO_FILE = Path("samples/video tests/Fortnites-NEW-Low.mp4")
AUDIO_FILE = Path("samples/video tests/Fortnites-NEW-Low.wav")
GROUND_TRUTH_FILE = Path("samples/video tests/Fortnites-NEW-Low-chests-timestamps.txt")
OUTPUT_DIR = Path("analysis_output")


# ==================================================================
# EVALUATION PARAMETERS
# ==================================================================

# A detection counts as a hit if it is within this many seconds of a labelled
# chest. Labels were placed by hand, so they are not sample-accurate.
MATCH_TOLERANCE_SECONDS = 0.75


# ==================================================================
# BASELINE (RMS) DETECTOR PARAMETERS
# ==================================================================

RMS_FRAME_LENGTH = 2048
RMS_HOP_LENGTH = 512
RMS_THRESHOLD_STD_MULTIPLIER = 2.5   # threshold = mean + k * std
RMS_MIN_EVENT_DISTANCE_SECONDS = 0.8


# ==================================================================
# CHEST DETECTOR PARAMETERS (tunable)
# ==================================================================

STFT_N_FFT = 2048
STFT_HOP = 256                        # ~5.8 ms at 44.1 kHz

# Frequency bands (Hz) used for the spectral-shape fingerprint.
# Chosen from the data: chest bursts are strong in 4-9 kHz and fall off
# steeply above ~11 kHz. Eleven bands keep the fingerprint small and robust.
BAND_EDGES_HZ = [200, 500, 1000, 2000, 3000, 4000, 5500, 7000, 9000, 11000, 13000, 16000]

# Bands (indices into BAND_EDGES_HZ intervals) summed for the candidate
# generator: 4 kHz - 11 kHz.
CANDIDATE_BANDS = slice(5, 9)

# Candidate generator
BACKGROUND_WINDOW_SECONDS = 4.0       # running-median background level
CANDIDATE_SMOOTHING_SECONDS = 0.03
CANDIDATE_MIN_RISE_DB = 8.0           # burst must be this far above background
CANDIDATE_MIN_SPACING_SECONDS = 0.3
SHAPE_HALF_WINDOW_SECONDS = 0.03      # shape averaged +/- this around the peak

# Verifier
SIMILARITY_THRESHOLD = 0.95           # cosine similarity to chest fingerprint

# Where a chest's burst may sit relative to its hand-placed label.
# MEASURED from the five labels (bursts occurred ~0 to +0.9 s after them);
# only used to pick the reference burst for each labelled chest.
REFERENCE_SEARCH_WINDOW_SECONDS = (-0.2, 1.3)

# Chest windows for the spectrogram figure
CHEST_WINDOW_SECONDS = (-1.0, 2.0)


# ==================================================================
# GROUND TRUTH
# ==================================================================

def parse_timestamp(text):
    """'00:51.30' / '1:10.20' / '51.30' / '0:01:10.2' -> seconds."""
    seconds = 0.0
    for part in text.strip().split(":"):
        seconds = seconds * 60.0 + float(part)
    return seconds


def load_ground_truth(path):
    if not path.exists():
        raise FileNotFoundError(f"Ground-truth file not found: {path.resolve()}")
    times = []
    for line in path.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            times.append(parse_timestamp(line))
    return np.array(sorted(times))


def match_events(truth, detected, tolerance):
    """
    One-to-one matching between ground-truth times and detected times.

    Uses an optimal assignment (Hungarian algorithm) on |time difference|,
    restricted to pairs within `tolerance`. A detection can satisfy at most
    one chest and a chest at most one detection, so several detections near
    one chest produce ONE true positive and the extras count as false
    positives.

    Returns (matches, missed_truth_indices, false_positive_indices) where
    matches is a list of (truth_index, detection_index, signed_error).
    """
    detected = np.asarray(detected, dtype=float)
    matches = []
    if len(truth) and len(detected):
        diff = detected[None, :] - truth[:, None]
        cost = np.where(np.abs(diff) <= tolerance, np.abs(diff), 1e6)
        from scipy.optimize import linear_sum_assignment
        rows, cols = linear_sum_assignment(cost)
        matches = [(r, c, diff[r, c]) for r, c in zip(rows, cols) if cost[r, c] < 1e6]
    matched_truth = {m[0] for m in matches}
    matched_det = {m[1] for m in matches}
    missed = [i for i in range(len(truth)) if i not in matched_truth]
    false_pos = [i for i in range(len(detected)) if i not in matched_det]
    return matches, missed, false_pos


def report(name, truth, detected, tolerance, detail=True):
    matches, missed, false_pos = match_events(truth, detected, tolerance)
    tp, fn, fp = len(matches), len(missed), len(false_pos)
    recall = tp / len(truth) if len(truth) else 0.0
    precision = tp / len(detected) if len(detected) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"\n=== {name} ===")
    print(f"GROUND TRUTH:     {len(truth):4d}")
    print(f"DETECTOR EVENTS:  {len(detected):4d}")
    print(f"MATCHED (TP):     {tp:4d}")
    print(f"MISSED (FN):      {fn:4d}")
    print(f"FALSE POSITIVES:  {fp:4d}")
    print(f"RECALL:    {recall:6.1%}")
    print(f"PRECISION: {precision:6.1%}")
    print(f"F1:        {f1:6.3f}")
    if detail:
        for t_i, d_i, err in sorted(matches):
            print(f"  matched  chest {truth[t_i]:7.2f}s <- {detected[d_i]:7.2f}s  (error {err:+.2f}s)")
        for t_i in missed:
            print(f"  MISSED   chest {truth[t_i]:7.2f}s")
        if false_pos:
            fp_text = ", ".join(f"{detected[i]:.1f}" for i in false_pos)
            print(f"  false positives (s): {fp_text}")
    return matches, missed, false_pos


# ==================================================================
# AUDIO LOADING
# ==================================================================

def load_audio():
    if not VIDEO_FILE.exists() and not AUDIO_FILE.exists():
        raise FileNotFoundError(f"Gameplay video not found:\n{VIDEO_FILE.resolve()}")
    if not AUDIO_FILE.exists():
        print("Extracting audio from video...")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(VIDEO_FILE), "-vn", "-ac", "1", "-ar", "44100", str(AUDIO_FILE)],
            check=True,
        )
    audio, sr = librosa.load(AUDIO_FILE, sr=None, mono=True)
    print(f"Audio: {len(audio) / sr:.1f} s @ {sr} Hz")
    return audio, sr


# ==================================================================
# BASELINE: RMS LOUDNESS DETECTOR
# ==================================================================

def detect_rms_events(audio, sr):
    rms = librosa.feature.rms(y=audio, frame_length=RMS_FRAME_LENGTH, hop_length=RMS_HOP_LENGTH)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=RMS_HOP_LENGTH)
    threshold = rms.mean() + RMS_THRESHOLD_STD_MULTIPLIER * rms.std()
    distance = int(RMS_MIN_EVENT_DISTANCE_SECONDS * sr / RMS_HOP_LENGTH)
    peaks, _ = find_peaks(rms, height=threshold, distance=distance)
    return times, rms, threshold, times[peaks]


# ==================================================================
# CHEST DETECTOR
# ==================================================================

def band_energies(audio, sr):
    """
    Power in each band of BAND_EDGES_HZ for every STFT frame -> (bands, frames).

    Computed in chunks so the full 1025 x frames spectrogram never sits in
    memory (it would be ~700 MB for an 8-minute clip).
    """
    freqs = librosa.fft_frequencies(sr=sr, n_fft=STFT_N_FFT)
    masks = [(freqs >= lo) & (freqs < hi) for lo, hi in zip(BAND_EDGES_HZ[:-1], BAND_EDGES_HZ[1:])]
    padded = np.pad(audio, STFT_N_FFT // 2, mode="reflect")   # same framing as center=True
    n_frames = 1 + (len(padded) - STFT_N_FFT) // STFT_HOP
    chunk = 4000
    out = np.zeros((len(masks), n_frames), dtype=np.float64)
    for a in range(0, n_frames, chunk):
        b = min(a + chunk, n_frames)
        seg = padded[a * STFT_HOP: (b - 1) * STFT_HOP + STFT_N_FFT]
        power = np.abs(librosa.stft(seg, n_fft=STFT_N_FFT, hop_length=STFT_HOP, center=False)) ** 2
        for k, mask in enumerate(masks):
            out[k, a:b] = power[mask].sum(axis=0)
    return out


def relative_burst_envelope(bands, frames_per_second):
    """
    4-11 kHz level in dB minus its own running-median background.

    Subtracting the local background makes this a "something sudden happened
    in this band" signal, so overall game/streamer volume largely cancels.
    """
    level_db = 10 * np.log10(bands[CANDIDATE_BANDS].sum(axis=0) + 1e-12)
    from scipy.ndimage import median_filter
    background = median_filter(level_db, size=int(BACKGROUND_WINDOW_SECONDS * frames_per_second), mode="nearest")
    rise = level_db - background
    k = int(CANDIDATE_SMOOTHING_SECONDS * frames_per_second) | 1
    return np.convolve(rise, np.ones(k) / k, mode="same")


def spectral_shape(bands, frame, frames_per_second):
    """11-band dB profile around a frame, mean-removed (level-independent)."""
    half = int(SHAPE_HALF_WINDOW_SECONDS * frames_per_second)
    a, b = max(frame - half, 0), frame + half + 1
    db = 10 * np.log10(bands[:, a:b].mean(axis=1) + 1e-12)
    return db - db.mean()


def cosine(a, b):
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def find_candidates(bands, frames_per_second):
    rise = relative_burst_envelope(bands, frames_per_second)
    peaks, _ = find_peaks(
        rise,
        height=CANDIDATE_MIN_RISE_DB,
        distance=int(CANDIDATE_MIN_SPACING_SECONDS * frames_per_second),
    )
    times = peaks / frames_per_second
    shapes = np.array([spectral_shape(bands, p, frames_per_second) for p in peaks])
    return rise, peaks, times, shapes


def reference_shapes(truth, cand_times, cand_rise, cand_shapes):
    """For each labelled chest, the strongest candidate burst near its label."""
    lo, hi = REFERENCE_SEARCH_WINDOW_SECONDS
    ref_index = []
    for t in truth:
        inside = np.where((cand_times >= t + lo) & (cand_times <= t + hi))[0]
        ref_index.append(inside[np.argmax(cand_rise[inside])] if len(inside) else None)
    return ref_index


def cross_validated_scores(truth, cand_times, cand_shapes, ref_index):
    """
    Similarity score per candidate that does not let a chest vote for itself.

    - candidates that are a labelled chest's reference burst are scored against
      a fingerprint built from the OTHER four chests;
    - every other candidate is scored against the all-chest fingerprint.
    """
    valid = [i for i in ref_index if i is not None]
    full = cand_shapes[valid].mean(axis=0)
    scores = np.array([cosine(s, full) for s in cand_shapes])
    for k, idx in enumerate(ref_index):
        if idx is None:
            continue
        others = [j for n, j in enumerate(ref_index) if n != k and j is not None]
        scores[idx] = cosine(cand_shapes[idx], cand_shapes[others].mean(axis=0))
    return scores, full


def audio_chest_events(truth=None, fingerprint=None):
    """
    Run the chest audio detector and return (accepted_times, all_candidate_times,
    similarity_per_candidate, fingerprint). Used by fusion/agreement/predict code.

    - truth given, no fingerprint: the fingerprint is built from the labelled
      chests of THIS clip and scores are cross-validated (original behaviour).
    - fingerprint given: no labels are needed; every candidate is scored against
      that fixed fingerprint (use this for a different, unlabelled recording).
    """
    audio, sr = load_audio()
    bands = band_energies(audio, sr)
    fps = sr / STFT_HOP
    rise, peaks, cand_times, cand_shapes = find_candidates(bands, fps)
    if fingerprint is None:
        ref = reference_shapes(truth, cand_times, rise[peaks], cand_shapes)
        scores, fingerprint = cross_validated_scores(truth, cand_times, cand_shapes, ref)
    else:
        scores = np.array([cosine(s, fingerprint) for s in cand_shapes])
    return cand_times[scores >= SIMILARITY_THRESHOLD], cand_times, scores, fingerprint


# ==================================================================
# PLOTTING
# ==================================================================

def shade_truth(ax, truth, tolerance):
    for i, t in enumerate(truth):
        ax.axvspan(t - tolerance, t + tolerance, color="tab:green", alpha=0.18,
                   label="ground-truth chest +/- tolerance" if i == 0 else None)
        ax.axvline(t, color="tab:green", linewidth=1.0)


def plot_timeline(path, truth, tolerance, rms_data, rise, frames_per_second,
                  cand_times, scores, detected_mask, rms_matches, rms_events, zoom, show):
    import matplotlib.pyplot as plt

    times, rms, rms_threshold, _ = rms_data
    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)

    # --- RMS baseline ---
    ax = axes[0]
    shade_truth(ax, truth, tolerance)
    ax.plot(times, rms, linewidth=0.7, color="tab:blue", label="RMS loudness")
    ax.axhline(rms_threshold, linestyle="--", color="tab:red", label="RMS threshold")
    matched_det = {m[1] for m in rms_matches}
    for i, t in enumerate(rms_events):
        good = i in matched_det
        ax.scatter(t, np.interp(t, times, rms), s=40 if good else 18, zorder=3,
                   color="tab:green" if good else "tab:red", marker="o" if good else "x")
    ax.set_ylabel("RMS")
    ax.set_title("Baseline RMS detector  (green = matched a chest, red x = false positive)")
    ax.legend(loc="upper right", fontsize=8)

    # --- 4-11 kHz burst envelope ---
    ax = axes[1]
    shade_truth(ax, truth, tolerance)
    ax.plot(np.arange(len(rise)) / frames_per_second, rise, linewidth=0.6, color="tab:purple")
    ax.axhline(CANDIDATE_MIN_RISE_DB, linestyle="--", color="tab:red", label="candidate min rise")
    ax.set_ylabel("4-11 kHz rise over\nbackground (dB)")
    ax.set_title("Candidate generator: sudden 4-11 kHz bursts")
    ax.legend(loc="upper right", fontsize=8)

    # --- similarity of every candidate ---
    ax = axes[2]
    shade_truth(ax, truth, tolerance)
    ax.scatter(cand_times[~detected_mask], scores[~detected_mask], s=14, color="0.6", label="rejected candidate")
    ax.scatter(cand_times[detected_mask], scores[detected_mask], s=26, color="tab:orange", label="accepted (>= threshold)")
    ax.axhline(SIMILARITY_THRESHOLD, linestyle="--", color="tab:red", label="similarity threshold")
    ax.set_ylim(max(-0.2, scores.min() - 0.05), 1.02)
    ax.set_ylabel("cosine similarity to\nchest fingerprint (CV)")
    ax.set_xlabel("Time (seconds)")
    ax.set_title("Spectral-shape verification of each candidate")
    ax.legend(loc="lower right", fontsize=8)

    if zoom:
        axes[0].set_xlim(*zoom)
        for a in axes[:2]:   # rescale y to the visible range
            a.relim(); a.autoscale_view(scalex=False)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    print(f"Saved {path}")
    if show:
        plt.show()
    plt.close(fig)


def plot_chest_windows(path, audio, sr, truth):
    import matplotlib.pyplot as plt

    t_lo, t_hi = CHEST_WINDOW_SECONDS
    n = len(truth)
    fig, axes = plt.subplots(1, n, figsize=(4.6 * n, 4.2), sharey=True)
    axes = np.atleast_1d(axes)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=STFT_N_FFT)
    keep = (freqs >= 1000) & (freqs <= 16000)
    for ax, t in zip(axes, truth):
        seg = audio[int(max(t + t_lo, 0) * sr): int((t + t_hi) * sr)]
        spec = np.abs(librosa.stft(seg, n_fft=STFT_N_FFT, hop_length=STFT_HOP))
        db = librosa.amplitude_to_db(spec, ref=np.max)
        ax.imshow(db[keep], origin="lower", aspect="auto", vmin=-70, vmax=0,
                  extent=[t_lo, t_hi, freqs[keep][0] / 1000, freqs[keep][-1] / 1000])
        ax.axvline(0, color="w", linewidth=0.8)
        ax.set_title(f"chest @ {t:.1f}s")
        ax.set_xlabel("seconds from label")
    axes[0].set_ylabel("kHz")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    print(f"Saved {path}")
    plt.close(fig)


# ==================================================================
# MAIN
# ==================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tolerance", type=float, default=MATCH_TOLERANCE_SECONDS)
    parser.add_argument("--zoom", type=float, nargs=2, metavar=("START", "END"),
                        help="zoom the timeline plot to this time range (seconds); the full plot is still saved")
    parser.add_argument("--no-show", action="store_true", help="save plots without opening a window")
    args = parser.parse_args()

    if args.no_show:
        matplotlib.use("Agg")

    truth = load_ground_truth(GROUND_TRUTH_FILE)
    print(f"Ground truth ({len(truth)} chests): " + ", ".join(f"{t:.2f}" for t in truth))

    audio, sr = load_audio()
    OUTPUT_DIR.mkdir(exist_ok=True)

    # ---- baseline RMS ----
    rms_data = detect_rms_events(audio, sr)
    rms_events = rms_data[3]
    rms_matches, _, _ = report("BASELINE: RMS loudness peaks", truth, rms_events, args.tolerance)

    # ---- chest detector ----
    print("\nComputing band energies...")
    bands = band_energies(audio, sr)
    fps = sr / STFT_HOP
    rise, peaks, cand_times, cand_shapes = find_candidates(bands, fps)
    cand_rise = rise[peaks]
    print(f"Candidate 4-11 kHz bursts: {len(cand_times)}")

    ref_index = reference_shapes(truth, cand_times, cand_rise, cand_shapes)
    for t, idx in zip(truth, ref_index):
        if idx is None:
            print(f"  WARNING: no candidate burst near chest {t:.2f}s")
    scores, fingerprint = cross_validated_scores(truth, cand_times, cand_shapes, ref_index)

    print("\nChest fingerprint (mean dB per band, mean-removed):")
    for (lo, hi), v in zip(zip(BAND_EDGES_HZ[:-1], BAND_EDGES_HZ[1:]), fingerprint):
        print(f"  {lo:5d}-{hi:5d} Hz  {v:+6.1f} dB")

    # ---- cross-validated check: does a held-out chest look like the others? ----
    print("\nLeave-one-chest-out: how does each held-out chest rank among all other candidates?")
    is_ref = np.zeros(len(cand_times), dtype=bool)
    for idx in ref_index:
        if idx is not None:
            is_ref[idx] = True
    # candidates within tolerance of ANY label are not counted as "other" lookalikes
    near_label = np.array([np.min(np.abs(truth - t)) <= args.tolerance + 0.3 for t in cand_times])
    others = scores[~near_label]
    for t, idx in zip(truth, ref_index):
        if idx is None:
            continue
        beat = int((others > scores[idx]).sum())
        print(f"  chest {t:7.2f}s  sim={scores[idx]:.3f}  beaten by {beat:3d} of {len(others)} non-chest candidates")

    # ---- decision ----
    accepted = scores >= SIMILARITY_THRESHOLD
    report(f"CHEST DETECTOR (cross-validated scores, similarity >= {SIMILARITY_THRESHOLD})",
           truth, cand_times[accepted], args.tolerance)

    print("\nThreshold sweep (cross-validated):")
    print("  thresh  events   TP  FP  recall  precision")
    for th in (0.90, 0.93, 0.95, 0.97, 0.98, 0.99):
        ev = cand_times[scores >= th]
        m, _, fp = match_events(truth, ev, args.tolerance)
        prec = len(m) / len(ev) if len(ev) else 0.0
        print(f"  {th:.2f}   {len(ev):5d}  {len(m):3d} {len(fp):3d}  {len(m) / len(truth):6.1%}  {prec:7.1%}")

    # ---- plots ----
    plot_timeline(OUTPUT_DIR / "timeline_full.png", truth, args.tolerance, rms_data, rise, fps,
                  cand_times, scores, accepted, rms_matches, rms_events, None, show=False)
    plot_chest_windows(OUTPUT_DIR / "chest_windows.png", audio, sr, truth)
    if args.zoom:
        plot_timeline(OUTPUT_DIR / "timeline_zoom.png", truth, args.tolerance, rms_data, rise, fps,
                      cand_times, scores, accepted, rms_matches, rms_events, tuple(args.zoom), show=False)
    if not args.no_show:
        import matplotlib.pyplot as plt
        for name in ("timeline_zoom.png" if args.zoom else "timeline_full.png", "chest_windows.png"):
            plt.figure(figsize=(16, 9))
            plt.imshow(plt.imread(OUTPUT_DIR / name)); plt.axis("off"); plt.tight_layout()
        plt.show()


if __name__ == "__main__":
    main()
