"""
Audio v2 experiments: does anything beat the 4-11 kHz burst-shape similarity?

This is a record of ideas that were TESTED, not part of the detector. Run:

    python research/audio_experiments.py

For every candidate burst found by detector.py it computes a few interpretable
features measured RELATIVE to the local background (so absolute loudness is not
required), then reports where each of the five labelled chests ranks among all
the other candidates (rank 0 = best, i.e. no other candidate scored higher).
With ~520 other candidates, a rank near 260 means "no better than chance".

Result (see README): nothing combined beat the burst-shape similarity already in
detector.py, so audio work stopped there.
"""

import numpy as np
from scipy.ndimage import median_filter

from fortnite_chest_counter.detection import audio as detector


def main():
    truth = detector.load_ground_truth(detector.GROUND_TRUTH_FILE)
    audio, sr = detector.load_audio()
    bands = detector.band_energies(audio, sr)
    fps = sr / detector.STFT_HOP
    rise, peaks, cand_times, cand_shapes = detector.find_candidates(bands, fps)
    ref = detector.reference_shapes(truth, cand_times, rise[peaks], cand_shapes)
    chest_idx = [i for i in ref if i is not None]
    scores, _ = detector.cross_validated_scores(truth, cand_times, cand_shapes, ref)

    # Candidates near a label are not counted as "other" lookalikes.
    near_label = np.array([np.min(np.abs(truth - t)) <= 1.2 for t in cand_times])

    # Every band's level in dB minus its own 4 s running median.
    level_db = 10 * np.log10(bands + 1e-12)
    relative = level_db - median_filter(level_db, size=(1, int(4 * fps)), mode="nearest")

    def region(t, start, end, band_slice):
        a, b = int(round((t + start) * fps)), int(round((t + end) * fps))
        return relative[band_slice, max(a, 0):b + 1]

    # Bands 0-2 = 200-1000 Hz, 0-4 = 200-3000 Hz, 5-8 = 4-11 kHz (see BAND_EDGES_HZ).
    features = {
        "pre-burst low energy (0.2-1 kHz, -0.25..-0.05 s)": lambda t: region(t, -.25, -.05, slice(0, 3)).mean(),
        "post-burst low energy, negated (0.2-3 kHz, +0.5..+1.1 s)": lambda t: -region(t, .5, 1.1, slice(0, 5)).mean(),
        "HF minus LF at burst": lambda t: region(t, -.03, .05, slice(5, 9)).mean()
                                         - region(t, -.03, .05, slice(0, 5)).mean(),
        "burst peak level (4-11 kHz)": lambda t: region(t, -.03, .05, slice(5, 9)).max(),
    }
    table = {"burst-shape cosine (current detector, cross-validated)": scores}
    for name, fn in features.items():
        table[name] = np.nan_to_num(np.array([fn(t) for t in cand_times]))

    def z(v):   # standardize using only non-chest candidates
        return (v - v[~near_label].mean()) / (v[~near_label].std() + 1e-9)

    keys = list(features)
    table["z-sum: pre-burst low + HF-LF + post-burst low"] = z(table[keys[0]]) + z(table[keys[2]]) + z(table[keys[1]])
    table["z-sum: burst-shape cosine + pre-burst low + HF-LF"] = z(scores) + z(table[keys[0]]) + z(table[keys[2]])
    for half in (0.4, 0.8, 1.5):
        neighbours = np.array([int(((np.abs(cand_times - t) <= half) & (cand_times != t)).sum()) for t in cand_times])
        table[f"isolation: few other bursts within +/-{half}s"] = -neighbours.astype(float)

    others = int((~near_label).sum())
    print(f"\nRank of each held-out chest among {others} non-chest candidates (0 = best, ~{others // 2} = chance)")
    print(f"{'feature':62s} ranks (5 chests)        median")
    for name, values in table.items():
        ranks = [int((values[~near_label] > values[i]).sum()) for i in chest_idx]
        print(f"{name:62s} {str(ranks):24s} {int(np.median(ranks))}")


if __name__ == "__main__":
    main()
