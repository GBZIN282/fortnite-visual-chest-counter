"""
Extra evidence cues around candidate chest events (additive; nothing here changes
the popup detector, its thresholds, or the base confidence tier).

Cues, all measured from fixed regions of the 1280x720-normalized HD video:

  ammo      the magazine-ammo number (bottom right). It changes every shot, so
            repeated changes near a candidate mean THE LOCAL PLAYER is firing
            (enemy gunfire elsewhere does not change it). Negative evidence.
  prompt    the round interaction-button icon of the "SEARCH / COLLECT" prompt.
            Language independent. "The player was interacting with something."
  flash     warm very bright pixels (muzzle flash) in the middle of the screen.
  gold      share of chest-gold coloured pixels near the middle of the screen.

Cue DEFINITIONS (fixed from the physical signal, not fitted to the labelled events):

  ammo steps   a sample where the ammo region jumps by >= AMMO_STEP_MIN_PIXELS right after
               a stable sample. The region also contains sky/foam, so raw "change" is
               meaningless (median frame difference is already 6 px); a firing player
               shows clean jumps between stable levels, which is what a step is.
               player_shooting = at least SHOOTING_MIN_STEPS steps in the window.
  prompt       (a) the binary ring score (weak, noisy) and (b) a grayscale ring-on-dark-disc
               correlation at 2 fps (much more selective, but cut from ONE frame).
  flash        number of samples whose warm-bright pixel count rose by >= FLASH_JUMP_PIXELS.
  gold         mean gold-pixel share in the central box.

The raw per-frame series are cached in analysis_output/<name>_cues.npz so cue
windows can be explored without re-reading the video.

Usage
-----
    python -m fortnite_chest_counter.detection.evidence --name Fortnite-PS5-Pro            # extract/cached cue series
"""

import argparse
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

from fortnite_chest_counter import paths
from fortnite_chest_counter.detection import visual as V
from fortnite_chest_counter.detection.audio import OUTPUT_DIR

SAMPLES = Path("samples/video tests")

# ==================================================================
# REGIONS (normalized 1280x720 pixels: x0, y0, x1, y1)
# ==================================================================

AMMO_BOX = (930, 648, 986, 676)          # magazine number, white digits
PROMPT_SEARCH_BOX = (360, 200, 960, 560)  # where the prompt pill can be
FLASH_BOX = (300, 250, 900, 560)
GOLD_BOX = (480, 200, 800, 520)

# Windows (seconds relative to the popup onset), chosen from the physics: a shot is fired
# BEFORE the hit-popup it causes (bullet flight + damage latency), so shooting is looked
# for from 1 s before to 0.5 s after; a prompt precedes the opening by up to a couple of seconds.
SHOOTING_WINDOW = (-1.0, 0.5)
PROMPT_WINDOW = (-2.5, 0.0)
GOLD_WINDOW = (-1.5, 0.0)
AMMO_STEP_MIN_PIXELS = 15
AMMO_STABLE_MAX_PIXELS = 3
SHOOTING_MIN_STEPS = 2
FLASH_JUMP_PIXELS = 100

SAMPLE_FPS = 15                           # frames analysed per second
PROMPT_EVERY_N = 2                        # prompt correlation on every 2nd sampled frame

# Interaction-ring template, cut once from the confirmed chest at 61.1 s of the PS5 clip.
RING_TEMPLATE_FILE = paths.TEMPLATES_DIR / "ui/interaction_ring.npy"
RING_SOURCE = (SAMPLES / "Fortnite-PS5-Pro-HD-No-Audio.mp4", 61.1, (745, 383, 770, 407))
RING_MASK_MIN = 150                       # all channels above this = ring pixel


def white_mask(frame, minimum):
    return (frame.min(axis=2) > minimum)


def load_ring_template():
    if RING_TEMPLATE_FILE.exists():
        return np.load(RING_TEMPLATE_FILE)
    video, t, (x0, y0, x1, y1) = RING_SOURCE
    frame = V.read_single_frame(video, t, crop=False)
    sub = white_mask(frame, RING_MASK_MIN)[y0:y1, x0:x1]
    ys, xs = np.where(sub)
    template = sub[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    RING_TEMPLATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    np.save(RING_TEMPLATE_FILE, template)
    return template


def correlate(mask, template):
    """Best Pearson correlation of a binary template inside a binary mask (score only)."""
    n = template.size
    s = template.sum()
    t_var = s - s * s / n
    overlap = fftconvolve(mask, template[::-1, ::-1], mode="valid")
    window = fftconvolve(mask, np.ones_like(template), mode="valid")
    numerator = overlap - window * s / n
    w_var = window - window * window / n
    return float((numerator / np.sqrt(np.maximum(t_var * w_var, 1e-6))).max())


def extract_cues(video, cache, rescan=False):
    """-> dict of per-sample arrays: t, ammo_lit, ammo_diff, prompt, flash, gold."""
    if cache.exists() and not rescan:
        cached = np.load(cache, allow_pickle=False)
        print(f"Using cached cue series ({cache}); --rescan to recompute.")
        return {k: cached[k] for k in cached.files}
    ring = load_ring_template()
    print(f"Extracting cue series at {SAMPLE_FPS} fps (ammo / prompt / flash / gold) - several minutes...")
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"{V.scale_filter()},fps={SAMPLE_FPS}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=10 ** 8)
    w, h = V.NORMALIZED_WIDTH, V.NORMALIZED_HEIGHT
    frame_bytes = w * h * 3
    ax0, ay0, ax1, ay1 = AMMO_BOX
    px0, py0, px1, py1 = PROMPT_SEARCH_BOX
    fx0, fy0, fx1, fy1 = FLASH_BOX
    gx0, gy0, gx1, gy1 = GOLD_BOX
    ammo_lit, ammo_diff, prompt, flash, gold = [], [], [], [], []
    previous, last_prompt, index = None, 0.0, 0
    while True:
        raw = process.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break
        frame = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
        ammo = white_mask(frame[ay0:ay1, ax0:ax1], 200)
        ammo_lit.append(int(ammo.sum()))
        ammo_diff.append(0 if previous is None else int((ammo ^ previous).sum()))
        previous = ammo

        if index % PROMPT_EVERY_N == 0:
            region = white_mask(frame[py0:py1, px0:px1], RING_MASK_MIN).astype(np.float32)
            last_prompt = correlate(region, ring) if region.sum() >= 20 else 0.0
        prompt.append(last_prompt)

        zone = frame[fy0:fy1, fx0:fx1].astype(np.int16)
        flash.append(int(((zone[..., 0] > 245) & (zone[..., 1] > 185) & (zone[..., 2] < 170)).sum()))
        zone = frame[gy0:gy1, gx0:gx1].astype(np.int16)
        r, g, b = zone[..., 0], zone[..., 1], zone[..., 2]
        gold.append(float(((r > 170) & (g > 110) & (g < r - 30) & (b < g - 40)).mean()))
        index += 1
    out = {"t": np.arange(index) / SAMPLE_FPS, "ammo_lit": np.array(ammo_lit), "ammo_diff": np.array(ammo_diff),
           "prompt": np.array(prompt, dtype=np.float32), "flash": np.array(flash), "gold": np.array(gold, dtype=np.float32)}
    cache.parent.mkdir(exist_ok=True)
    np.savez(cache, **out)
    return out


# ------------------------------------------------------------------
# Grayscale interaction-prompt patch (ring on dark disc), 2 fps
# ------------------------------------------------------------------

DISC_TEMPLATE_FILE = paths.TEMPLATES_DIR / "ui/interaction_disc.npy"
DISC_SOURCE = (SAMPLES / "Fortnite-PS5-Pro-HD-No-Audio.mp4", 61.2, (739, 377, 775, 413))
PROMPT_GRAY_FPS = 2
GRAY = np.array([0.299, 0.587, 0.114])


def load_disc_template():
    if DISC_TEMPLATE_FILE.exists():
        return np.load(DISC_TEMPLATE_FILE)
    video, t, (x0, y0, x1, y1) = DISC_SOURCE
    gray = V.read_single_frame(video, t, crop=False).astype(np.float64) @ GRAY
    DISC_TEMPLATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    np.save(DISC_TEMPLATE_FILE, gray[y0:y1, x0:x1])
    return gray[y0:y1, x0:x1]


def extract_prompt_gray(video, cache, rescan=False):
    """Zero-mean normalized correlation of the ring-on-disc patch, every 0.5 s -> (t, score)."""
    if cache.exists() and not rescan:
        c = np.load(cache, allow_pickle=False)
        return c["t"], c["score"]
    template = load_disc_template()
    t0 = template - template.mean()
    norm = np.sqrt((t0 ** 2).sum())
    ones = np.ones_like(template)
    n = template.size
    px0, py0, px1, py1 = PROMPT_SEARCH_BOX
    print("Extracting grayscale prompt score at 2 fps - about 90 s...")
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"{V.scale_filter()},fps={PROMPT_GRAY_FPS}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=10 ** 8)
    frame_bytes = V.NORMALIZED_WIDTH * V.NORMALIZED_HEIGHT * 3
    scores = []
    while True:
        raw = process.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break
        frame = np.frombuffer(raw, np.uint8).reshape(V.NORMALIZED_HEIGHT, V.NORMALIZED_WIDTH, 3)
        region = frame[py0:py1, px0:px1].astype(np.float64) @ GRAY
        num = fftconvolve(region, t0[::-1, ::-1], mode="valid")
        s1 = fftconvolve(region, ones, mode="valid")
        s2 = fftconvolve(region ** 2, ones, mode="valid")
        var = np.maximum(s2 - s1 * s1 / n, n * 25.0)      # variance floor: flat areas cannot score
        scores.append(float((num / (np.sqrt(var) * norm)).max()))
    t = np.arange(len(scores)) / PROMPT_GRAY_FPS
    np.savez(cache, t=t, score=np.array(scores))
    return t, np.array(scores)


# ------------------------------------------------------------------
# Cue features for one event
# ------------------------------------------------------------------

def _window(t, event, window):
    return (t >= event + window[0]) & (t <= event + window[1])


def ammo_steps(cues, event, window=SHOOTING_WINDOW):
    diff = cues["ammo_diff"]
    idx = np.where(_window(cues["t"], event, window))[0]
    return int(sum(1 for i in idx if i > 0 and diff[i] >= AMMO_STEP_MIN_PIXELS and diff[i - 1] <= AMMO_STABLE_MAX_PIXELS))


def flash_bursts(cues, event, window=SHOOTING_WINDOW):
    f = cues["flash"].astype(int)
    idx = np.where(_window(cues["t"], event, window))[0]
    return int(sum(1 for i in idx if i > 0 and f[i] - f[i - 1] >= FLASH_JUMP_PIXELS))


def prompt_binary(cues, event, window=PROMPT_WINDOW):
    m = _window(cues["t"], event, window)
    return float(cues["prompt"][m].max()) if m.any() else 0.0


def prompt_gray(gray_t, gray_score, event, window=PROMPT_WINDOW):
    m = _window(gray_t, event, window)
    return float(gray_score[m].max()) if m.any() else 0.0


def gold_mean(cues, event, window=GOLD_WINDOW):
    m = _window(cues["t"], event, window)
    return float(cues["gold"][m].mean()) if m.any() else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="Fortnite-PS5-Pro")
    parser.add_argument("--rescan", action="store_true")
    args = parser.parse_args()
    video = SAMPLES / f"{args.name}-HD-No-Audio.mp4"
    cues = extract_cues(video, OUTPUT_DIR / f"{args.name}_cues.npz", args.rescan)
    print({k: v.shape for k, v in cues.items()})


if __name__ == "__main__":
    main()


def locate_prompt(frame_rgb):
    """Where is the best ring-on-disc match in a full normalized frame? -> (score, y, x) of its centre."""
    template = load_disc_template()
    t0 = template - template.mean()
    norm = np.sqrt((t0 ** 2).sum())
    ones = np.ones_like(template)
    n = template.size
    px0, py0, px1, py1 = PROMPT_SEARCH_BOX
    region = frame_rgb[py0:py1, px0:px1].astype(np.float64) @ GRAY
    num = fftconvolve(region, t0[::-1, ::-1], mode="valid")
    s1 = fftconvolve(region, ones, mode="valid")
    s2 = fftconvolve(region ** 2, ones, mode="valid")
    var = np.maximum(s2 - s1 * s1 / n, n * 25.0)
    score = num / (np.sqrt(var) * norm)
    y, x = np.unravel_index(np.argmax(score), score.shape)
    return float(score[y, x]), py0 + y + template.shape[0] // 2, px0 + x + template.shape[1] // 2
