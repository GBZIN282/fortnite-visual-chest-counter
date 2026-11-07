"""
Streaming chest estimator: consumes frames one at a time (no future frames, no rescans),
runs the existing clue detectors, merges their evidence into ONE event per chest, and
says how each event should be counted.

Frame source  ->  ChestEstimator.process_frame(t, frame)  ->  finished events
(MP4 today; a capture card / OBS source later: anything yielding (seconds, 720p RGB frame).)

Clues used (all existing detectors, parameters untouched):
  popup        word CHEST / BAU in the XP popup           (visual_detector.py)
               + scale-aware channel: CHEST drawn larger (bigger HUD), blurred match at smaller scales - APPROX only
  sprite       "+75 CONTAINER OPENED" tag                  (sprite_detector.py)
  ammo         ammo-counter jumps = the local player fires (evidence.py)
  prompt       interaction-button icon + chest-object colours around it (evidence.py / object_cue.py)
NOT in the live path yet: the audio detector (it needs a streaming audio buffer and was the
weakest clue; it never gated anything).

An event is FINISHED a little after it starts, because its evidence needs a short look-ahead:
  popup events   1.0 s after the popup appears (peak score, ammo steps, sprite tag)
  prompt events  5.6 s after the prompt (waiting to see whether a popup merges with it)

Counting rules (see the constants below; all explicit and configurable):
  CERTAIN count      popup events whose adjusted tier is CERTAIN or HIGH.
  APPROX count       CERTAIN + HIGH, plus
                     - MEDIUM popups of languages whose word is long enough to be reliable
                       (config), plus
                     - MEDIUM popups backed by a prompt + chest-object, plus
                     - prompt + chest-object events whose popup never fired, plus
                     - scale-aware pop-ups (HUD drawn larger; exact match too low): MEDIUM, APPROX only.
  never counted      LOW (e.g. MEDIUM while the player is shooting), generic prompts
                     (pickups, ammo crates, cannons...), anything else. They are still logged.
"""

import time
from collections import Counter, deque

import numpy as np

from fortnite_chest_counter.detection import evidence
from fortnite_chest_counter.detection import fusion
from fortnite_chest_counter.detection import object_cue
from fortnite_chest_counter.detection import sprite as sprite_detector
from fortnite_chest_counter.detection import visual as V

# ==================================================================
# COUNTING RULES (explicit; change here, not in the code)
# ==================================================================

CERTAIN_TIERS = ("CERTAIN", "HIGH")

# MEDIUM popups counted as APPROX even without other support, per popup template.
# English CHEST (27 px word): every popup >= 0.75 on the English clip was a real chest (6/6).
# Portuguese BAU (14 px word): only 2 of 9 MEDIUM popups were real chests on the PS5 clip.
APPROX_COUNTS_MEDIUM_ALONE = {"en:CHEST": True, "pt:BAÚ": False}

# A MEDIUM popup that also has a prompt >= INTERACTION_SUPPORT_PROMPT_MIN with a chest-like
# object near it counts as APPROX. PROVISIONAL: this 0.60 level was fixed after seeing the
# prompt scores of the verified PS5 events, so treat it as unvalidated.
APPROX_MEDIUM_WITH_OBJECT_SUPPORT = True

# "Shooting" (ammo-counter steps around the popup) demotes an ambiguous MEDIUM popup to LOW. That is right for SHORT
# chest words: on the PS5 clip the 14 px BAU template matched combat-time lavender text at 0.77-0.82 and all 3 shooting
# demotions removed verified-false popups. It is wrong for a SPECIFIC word: across ~25 min of footage (both clips,
# including heavy combat) the 27 px CHEST template never scored above 0.65 on anything that was not a chest (max 0.37 on
# the PS5 combat popups), while live users saw real English chests opened mid-fight demoted to LOW and lost.
# So shooting only demotes popups whose word is NOT reliable on its own (APPROX_COUNTS_MEDIUM_ALONE). v0.1.0 = True.
SHOOTING_DEMOTES_RELIABLE_WORDS = False

# Compression-robust confirmation. Streaming compression smears the 7 px-high popup word by a fraction of a pixel, so the
# exact binary match drops (real English chests: 0.78-1.00 clean -> 0.77-0.88 at a 2.5 Mbps 1080p encode = MEDIUM).
# Correlating the Gaussian-blurred mask with the equally blurred template (sigma 0.6 px) is insensitive to that smear:
# real English chests scored >= 0.92 in EVERY condition (clean, 6 Mbps, 2.5 Mbps) while nothing that was not a chest
# scored above 0.78 with the English template (25 min of footage incl. Portuguese combat popups); Portuguese: real
# >= 0.91 under compression, verified-false popups <= 0.83. This score never creates or removes a popup and never
# lowers a tier: a MEDIUM popup whose blurred match is >= ROBUST_HIGH_MIN is promoted to HIGH (= CERTAIN by default).
ROBUST_PROMOTION = True
ROBUST_SIGMA = 0.6
ROBUST_HIGH_MIN = 0.88
ROBUST_SEARCH_PX = 8          # the blurred match is searched within this many px of the exact match

# Scale-aware pop-ups (docs/INVESTIGATION_2026-11-07.md). Some streams draw the HUD ~1.2x larger, so the pop-up word is
# ~33 px wide instead of 27 px: the exact match (one fixed size) stays near 0.25 and nearly every chest is missed, while a
# blurred match of the picture made smaller (x0.8) scores 0.82-0.92. This is a second channel BESIDE the exact path:
#   - it runs only when the pop-up box has >= SCALED_PREFILTER_PX lavender pixels (production computes that mask anyway)
#   - it looks only for the specific English word (SCALED_POPUP_TEMPLATES) and only shrinks the picture (= larger HUD);
#     enlarging, or the short Portuguese word, matched non-chest text on the PS5 reference
#   - after two strong pop-ups agree on a scale (SCALED_LOCK_MIN), only that scale and its neighbours are searched
#   - a blurred onset becomes a pop-up only when the exact path has not fired within SCALED_WAIT seconds of it, so every
#     exact-path event (incl. back-to-back chests and the CERTAIN rules) is exactly as before
#   - no "position jumped" re-fire (a stacked "WEAKPOINT STREAK / CHEST" pop-up would count twice)
#   - such a pop-up is merged with prompts like any pop-up and counts APPROX ONLY (MEDIUM), never CERTAIN.
# Validation: event-identical on every reference clip (English and PS5, clean and compressed); on three large-HUD sessions
# 11 of 11 verified chests (exact path alone: 3), 0 duplicates, 0 wrong counts.
SCALE_AWARE_POPUPS = True
SCALED_POPUP_TEMPLATES = ("en:CHEST",)       # used only while the word also counts MEDIUM alone (APPROX_COUNTS_MEDIUM_ALONE)
SCALED_SCALES = (1.0, 0.9, 0.85, 0.8, 0.75)  # picture made smaller = HUD drawn larger
SCALED_TRIGGER = 0.80
SCALED_REARM = 0.55
SCALED_PREFILTER_PX = 60
SCALED_WAIT = 2.0
SCALED_LOCK_MIN = 0.84

# Prompt + chest-object events whose popup never fired: counted as APPROX only, never CERTAIN.
INTERACTION_ONLY_COUNTS_APPROX = True
INTERACTION_CAN_BE_CERTAIN = False

# ==================================================================
# EVIDENCE PARAMETERS
# ==================================================================

INTERACTION_COUNT_PROMPT_MIN = 0.70      # a prompt this strong starts an interaction event
INTERACTION_SUPPORT_PROMPT_MIN = 0.60    # weaker prompts can still support a MEDIUM popup
INTERACTION_REFRACTORY_SECONDS = 6.0
MERGE_POPUP_BEFORE_PROMPT = 1.0          # popup onset may lead the prompt by this much...
MERGE_POPUP_AFTER_PROMPT = 4.5           # ...or follow it by this much (M001: ~3 s, M004: ~2.7 s)
POPUP_FINISH_DELAY = 1.0
INTERACTION_FINISH_DELAY = MERGE_POPUP_AFTER_PROMPT + POPUP_FINISH_DELAY + 0.1
SPRITE_NEAR_SECONDS = 1.5

SAMPLE_FPS = 15                          # frames per second the estimator expects
PROMPT_EVERY_N_FRAMES = 8                # ~1.9 prompt scores per second (as in the offline analysis)


ENABLED_LANGUAGES = {"en", "pt"}

# Keep a copy of the popup region at each popup's peak so the session can save it as a PNG ([logging] save_snapshots).
SAVE_SNAPSHOTS = False


def configure(detector_cfg):
    """Apply the user's [detector] settings (settings.py) to the counting rules above."""
    global CERTAIN_TIERS, APPROX_COUNTS_MEDIUM_ALONE, APPROX_MEDIUM_WITH_OBJECT_SUPPORT
    global INTERACTION_ONLY_COUNTS_APPROX, ENABLED_LANGUAGES, SAMPLE_FPS, PROMPT_EVERY_N_FRAMES
    CERTAIN_TIERS = ("CERTAIN",) if detector_cfg["certain_min_tier"] == "CERTAIN" else ("CERTAIN", "HIGH")
    alone = set(detector_cfg["medium_counts_alone_languages"])
    APPROX_COUNTS_MEDIUM_ALONE = {t["id"]: t["id"].split(":")[0] in alone for t in V.CHEST_TEMPLATES}
    APPROX_MEDIUM_WITH_OBJECT_SUPPORT = detector_cfg["count_supported_medium_as_approx"]
    INTERACTION_ONLY_COUNTS_APPROX = detector_cfg["count_interaction_object_as_approx"]
    ENABLED_LANGUAGES = set(detector_cfg["languages"])
    SAMPLE_FPS = detector_cfg["process_fps"]
    PROMPT_EVERY_N_FRAMES = max(1, round(SAMPLE_FPS / 1.9))      # keep ~1.9 prompt scores per second


class OnsetDetector:
    """The offline hysteresis event detector (visual_detector.detect_events), one sample at a time."""

    def __init__(self, high, low, use_position):
        self.high, self.low, self.use_position = high, low, use_position
        self.events, self.armed, self.low_since, self.last_pos = [], True, None, None

    def update(self, t, score, y=0, x=0):
        fired = False
        spaced = not self.events or t - self.events[-1] >= V.EVENT_MIN_SEPARATION_SECONDS
        if score >= self.high:
            jumped = (self.use_position and self.last_pos is not None
                      and max(abs(y - self.last_pos[0]), abs(x - self.last_pos[1])) >= V.EVENT_POSITION_JUMP_PIXELS)
            if spaced and (self.armed or jumped):
                self.events.append(t)
                self.armed, fired = False, True
            self.last_pos = (y, x)
            self.low_since = None
        elif score < self.low:
            self.low_since = t if self.low_since is None else self.low_since
            if not self.armed and t - self.low_since >= V.EVENT_REARM_HOLD_SECONDS:
                self.armed, self.last_pos = True, None
        else:
            self.low_since = None
        return fired


def adjust_tier(base_tier, shooting, interaction):
    """Same rule as refine.adjust: only MEDIUM can move; CERTAIN/HIGH are protected."""
    if base_tier != "MEDIUM":
        return base_tier
    if shooting and not interaction:
        return "LOW"
    if interaction and not shooting:
        return "HIGH"
    return "MEDIUM"


class ChestEstimator:
    def __init__(self, scale_aware=None):
        """scale_aware: None = SCALE_AWARE_POPUPS; False / True to compare both (tests, research)."""
        self.templates = [t for t in V.load_templates() if t["id"].split(":")[0] in ENABLED_LANGUAGES]
        if not self.templates:
            raise ValueError(f"no chest-word template for languages {sorted(ENABLED_LANGUAGES)}; "
                             f"available: {[t['id'] for t in V.CHEST_TEMPLATES]}")
        self.robust_templates = {t["id"]: V.blur_template(t["array"], ROBUST_SIGMA) for t in self.templates}
        self.sprite_template = sprite_detector.load_or_build_template()
        evidence.load_disc_template()
        self.popup = OnsetDetector(V.EVENT_HIGH_THRESHOLD, V.EVENT_LOW_THRESHOLD, True)
        self.sprite = OnsetDetector(sprite_detector.EVENT_HIGH_THRESHOLD, sprite_detector.EVENT_LOW_THRESHOLD, False)
        self.pending_popups, self.pending_interactions = [], []
        self.sprite_events = []
        self.prompt_series = deque()       # (t, score) every prompt sample
        self.prompt_obs = deque()          # (t, score, gold, gem, chest_like) for scores >= SUPPORT_MIN
        self.ammo_steps = deque()          # times of ammo-region steps
        self.popup_hist = deque()          # (t, best score, y, x, template index) every frame; diagnostics only
        self.ammo_prev, self.ammo_prev_diff = None, 0
        self.last_interaction_time = -1e9
        self.frame_index = 0
        self.now = 0.0
        on = SCALE_AWARE_POPUPS if scale_aware is None else scale_aware
        self.scaled_templates = {tid: self.robust_templates[tid] for tid in SCALED_POPUP_TEMPLATES
                                 if on and tid in self.robust_templates and APPROX_COUNTS_MEDIUM_ALONE.get(tid, False)}
        self.scaled_onset = OnsetDetector(SCALED_TRIGGER, SCALED_REARM, False)
        self.pending_scaled = []
        self.exact_onsets = deque()
        self.scale_votes, self.scale_locked = Counter(), None
        self.scaled_stats = {"prefilter_pass": 0, "onsets": 0, "dropped_for_exact": 0, "search_ms_total": 0.0,
                             "search_ms_max": 0.0}

    # ------------------------------------------------------------------ per frame
    def process_frame(self, t, frame):
        """Feed one 1280x720 RGB frame taken at video time `t`. Returns the events finished at this time."""
        self.now = t
        self._popup(t, frame)
        self._sprite(t, frame)
        self._ammo(t, frame)
        if self.frame_index % PROMPT_EVERY_N_FRAMES == 0:
            self._prompt(t, frame)
        self.frame_index += 1
        self._trim(t)
        return self._finish(t, final=False)

    def flush(self):
        """End of stream: finish whatever is pending with the evidence that exists."""
        for p in self.pending_scaled:
            self._promote_scaled(p)
        self.pending_scaled = []
        return self._finish(self.now, final=True)

    # ------------------------------------------------------------------ clue updates
    def _popup(self, t, frame):
        roi = frame[V.ROI_Y:V.ROI_Y + V.ROI_H, V.ROI_X:V.ROI_X + V.ROI_W]
        mask = V.lavender_mask(roi)
        best = (0.0, 0, 0, 0)
        where = {}                                          # template id -> top-left of its best exact match
        if mask.sum() >= 20:
            for k, tpl in enumerate(self.templates):
                score, y, x = V.best_template_correlation(mask, tpl["array"])
                where[tpl["id"]] = (y, x)
                if score > best[0]:
                    h, w = tpl["array"].shape
                    best = (score, y + h // 2, x + w // 2, k)
        score, y, x, k = best
        self.popup_hist.append((t, score, y, x, k if score > 0 else -1))
        for p in self.pending_popups:                       # keep the peak over the first second
            if t <= p["onset"] + POPUP_FINISH_DELAY and score > p["score"]:
                p.update(score=score, y=y, x=x, template=self.templates[k]["id"])
                if SAVE_SNAPSHOTS:
                    p["roi"] = roi.copy()
        exact_fired = self.popup.update(t, score, y, x)
        if exact_fired:
            self.pending_popups.append({"onset": t, "score": score, "y": y, "x": x,
                                        "template": self.templates[k]["id"] if score > 0 else "-"})
            if SAVE_SNAPSHOTS:
                self.pending_popups[-1]["roi"] = roi.copy()
        # Compression-robust glyph score, only while a popup is being evaluated (cheap: ~15 frames per popup).
        live = [p for p in self.pending_popups if t <= p["onset"] + POPUP_FINISH_DELAY]
        if live and ROBUST_PROMOTION and where:
            for tpl in self.templates:
                # Only around the exact match's position (+-8 px): the confirmation must come from the SAME glyph, and
                # it costs ~1 ms instead of ~12 ms for the whole popup region.
                (y0, x0), (h, w) = where[tpl["id"]], tpl["array"].shape
                crop = mask[max(0, y0 - ROBUST_SEARCH_PX):y0 + h + ROBUST_SEARCH_PX, max(0, x0 - ROBUST_SEARCH_PX):x0 + w + ROBUST_SEARCH_PX]
                r = V.robust_correlation(crop, self.robust_templates[tpl["id"]], ROBUST_SIGMA)
                for p in live:
                    best_r = p.setdefault("robust", {})
                    best_r[tpl["id"]] = max(best_r.get(tpl["id"], 0.0), r)
        if self.scaled_templates:
            self._scaled_popup(t, roi, mask, exact_fired)

    # ------------------------------------------------------------------ scale-aware pop-ups (SCALE_AWARE_POPUPS)
    def _scaled_popup(self, t, roi, mask, exact_fired):
        """Second pop-up channel, after the exact path of the same frame. Only adds pop-ups the exact path did not find."""
        if exact_fired:                                     # the exact path owns this pop-up: drop blurred onsets near it
            self.exact_onsets.append(t)
            kept = [p for p in self.pending_scaled if p["onset"] < t - SCALED_WAIT]
            self.scaled_stats["dropped_for_exact"] += len(self.pending_scaled) - len(kept)
            self.pending_scaled = kept
        while self.exact_onsets and self.exact_onsets[0] < t - SCALED_WAIT - 1.0:
            self.exact_onsets.popleft()
        best = (0.0, 0, 0, 1.0, None)
        if mask.sum() >= SCALED_PREFILTER_PX:
            a = time.perf_counter()
            best = self._scaled_best(roi, mask)
            ms = 1000 * (time.perf_counter() - a)
            st = self.scaled_stats
            st["prefilter_pass"] += 1
            st["search_ms_total"] += ms
            st["search_ms_max"] = max(st["search_ms_max"], ms)
        score, cy, cx, s, tid = best
        for p in self.pending_scaled:                       # keep the peak over the pop-up's first second
            if t <= p["onset"] + POPUP_FINISH_DELAY and score > p["blur"]:
                p.update(blur=score, scale=s, y=cy, x=cx)
                if SAVE_SNAPSHOTS:
                    p["roi"] = roi.copy()
        if self.scaled_onset.update(t, score, cy, cx):
            if not any(abs(o - t) <= SCALED_WAIT for o in self.exact_onsets) and \
                    not any(abs(p["onset"] - t) <= POPUP_FINISH_DELAY for p in self.pending_popups):
                self.pending_scaled.append({"onset": t, "blur": score, "scale": s, "y": cy, "x": cx, "template": tid})
                if SAVE_SNAPSHOTS:
                    self.pending_scaled[-1]["roi"] = roi.copy()
                self.scaled_stats["onsets"] += 1
        for p in list(self.pending_scaled):                 # not claimed by the exact path in time -> a pop-up
            if t >= p["onset"] + SCALED_WAIT:
                self.pending_scaled.remove(p)
                self._promote_scaled(p)

    def _scaled_scales(self):
        if self.scale_locked is None:
            return SCALED_SCALES
        i = SCALED_SCALES.index(self.scale_locked)
        return SCALED_SCALES[max(0, i - 1):i + 2]

    def _scaled_best(self, roi, mask):
        """Best blurred match over the active scales -> (score, centre y, centre x in pop-up box pixels, scale, template)."""
        best = (0.0, 0, 0, 1.0, None)
        for s in self._scaled_scales():
            m = mask if s == 1.0 else V.lavender_mask(V.resize_box(roi, round(roi.shape[1] * s), round(roi.shape[0] * s)))
            if m.sum() < 20:
                continue
            for tid, tpl in self.scaled_templates.items():
                score, y, x = V.robust_correlation_at(m, tpl, ROBUST_SIGMA)
                if score > best[0]:
                    h, w = tpl.shape
                    best = (score, int((y + h // 2) / s), int((x + w // 2) / s), s, tid)
        return best

    def _promote_scaled(self, p):
        """A blurred onset the exact path did not claim becomes a pending pop-up (finished and counted like any other)."""
        exact_peak = max((h[1] for h in self.popup_hist if p["onset"] <= h[0] <= p["onset"] + POPUP_FINISH_DELAY),
                         default=0.0)
        popup = {"onset": p["onset"], "score": exact_peak, "y": p["y"], "x": p["x"], "template": p["template"],
                 "scaled": {"blur": p["blur"], "scale": p["scale"]}}
        if "roi" in p:
            popup["roi"] = p["roi"]
        self.pending_popups.append(popup)

    def _vote_scale(self, p):
        """Strong pop-ups vote for the stream's HUD scale (scaled: its scale; strong exact: 1.0); 2 agreeing votes lock it."""
        s = p.get("scaled")
        if s is not None:
            if s["blur"] >= SCALED_LOCK_MIN:
                self.scale_votes[s["scale"]] += 1
        elif p["score"] >= ROBUST_HIGH_MIN:
            self.scale_votes[1.0] += 1
        if self.scale_votes and self.scale_locked is None:
            (scale, n), *rest = self.scale_votes.most_common()
            if n >= 2 and (not rest or n >= 2 * rest[0][1]):
                self.scale_locked = scale

    def _sprite(self, t, frame):
        x0, y0, w, h = sprite_detector.ROI_X, sprite_detector.ROI_Y, sprite_detector.ROI_W, sprite_detector.ROI_H
        mask = sprite_detector.white_mask(frame[y0:y0 + h, x0:x0 + w])
        score = V.best_template_correlation(mask, self.sprite_template)[0] if mask.sum() >= 40 else 0.0
        if self.sprite.update(t, score):
            self.sprite_events.append(t)

    def _ammo(self, t, frame):
        x0, y0, x1, y1 = evidence.AMMO_BOX
        mask = evidence.white_mask(frame[y0:y1, x0:x1], 200)
        diff = 0 if self.ammo_prev is None else int((mask ^ self.ammo_prev).sum())
        if diff >= evidence.AMMO_STEP_MIN_PIXELS and self.ammo_prev_diff <= evidence.AMMO_STABLE_MAX_PIXELS:
            self.ammo_steps.append(t)
        self.ammo_prev, self.ammo_prev_diff = mask, diff

    def _prompt(self, t, frame):
        score, y, x = evidence.locate_prompt(frame)
        self.prompt_series.append((t, score))
        if score >= INTERACTION_SUPPORT_PROMPT_MIN:
            f = object_cue.object_features(frame, y, x)
            self.prompt_obs.append((t, score, f["gold"], f["gem"], object_cue.chest_like(f)))
        if score >= INTERACTION_COUNT_PROMPT_MIN and t - self.last_interaction_time >= INTERACTION_REFRACTORY_SECONDS:
            self.pending_interactions.append({"t": t, "score": score, "merged": False})
            self.last_interaction_time = t

    def _trim(self, t):
        while self.popup_hist and self.popup_hist[0][0] < t - 4.0:
            self.popup_hist.popleft()
        for dq in (self.prompt_series, self.prompt_obs):
            while dq and dq[0][0] < t - 12.0:
                dq.popleft()
        while self.ammo_steps and self.ammo_steps[0] < t - 12.0:
            self.ammo_steps.popleft()
        self.sprite_events = [s for s in self.sprite_events if s > t - 12.0]

    # ------------------------------------------------------------------ finishing events
    def _finish(self, t, final):
        out = []
        for p in list(self.pending_popups):
            if final or p["onset"] + POPUP_FINISH_DELAY <= t:
                self.pending_popups.remove(p)
                out.append(self._popup_event(p))
        for i in list(self.pending_interactions):
            if final or i["t"] + INTERACTION_FINISH_DELAY <= t:
                self.pending_interactions.remove(i)
                if not i["merged"]:
                    out.append(self._interaction_event(i))
        return sorted(out, key=lambda e: e["time"])

    def _object_support(self, a, b):
        """Best chest-like prompt observation in [a, b] -> (score, gold, gem) or None."""
        hits = [o for o in self.prompt_obs if a <= o[0] <= b and o[4]]
        if not hits:
            return None
        best = max(hits, key=lambda o: o[1])
        return best[1], best[2], best[3]

    def _popup_trace(self, p):
        """Temporal summary of the popup over [onset-1 s, onset+1 s]. DIAGNOSTICS ONLY: logged with the event, never used to decide."""
        onset = p["onset"]
        win = [h for h in self.popup_hist if onset - 1.0 <= h[0] <= onset + POPUP_FINISH_DELAY]
        scores = np.array([h[1] for h in win]) if win else np.zeros(1)
        strong = [h for h in win if h[1] >= 0.65]
        lit = [h[0] for h in win if h[1] >= 0.60]
        win_k = next((i for i, t in enumerate(self.templates) if t["id"] == p["template"]), -1)
        return {"frames_ge_075": int((scores >= 0.75).sum()), "frames_ge_065": int((scores >= 0.65).sum()),
                "span_ge_060_s": round(max(lit) - min(lit), 2) if lit else 0.0,
                "top5_mean": round(float(np.sort(scores)[-5:].mean()), 3), "median_ge_065": round(float(np.median([h[1] for h in strong])), 3) if strong else None,
                "y_std": round(float(np.std([h[2] for h in strong])), 1) if len(strong) > 1 else None,
                "x_std": round(float(np.std([h[3] for h in strong])), 1) if len(strong) > 1 else None,
                "template_agreement": round(sum(h[4] == win_k for h in strong) / len(strong), 2) if strong else None}

    def _popup_event(self, p):
        onset = p["onset"]
        sprite_present = any(abs(s - onset) <= SPRITE_NEAR_SECONDS for s in self.sprite_events)
        base_tier, rule = fusion.confidence_tier(p["score"], sprite_present, False)
        steps = sum(1 for s in self.ammo_steps if onset - 1.0 <= s <= onset + 0.5)
        shooting = steps >= evidence.SHOOTING_MIN_STEPS
        prompts = [sc for (tt, sc) in self.prompt_series if onset - 2.5 <= tt <= onset]
        interaction_score = max(prompts) if prompts else 0.0
        interaction = interaction_score >= 0.70
        reliable_word = APPROX_COUNTS_MEDIUM_ALONE.get(p["template"], False)
        shooting_demotes = shooting and (SHOOTING_DEMOTES_RELIABLE_WORDS or not reliable_word)
        adjusted = adjust_tier(base_tier, shooting_demotes, interaction)
        robust = p.get("robust", {}).get(p["template"], 0.0)
        promoted = ROBUST_PROMOTION and adjusted == "MEDIUM" and robust >= ROBUST_HIGH_MIN

        merged = None
        for i in self.pending_interactions:
            if not i["merged"] and i["t"] - MERGE_POPUP_BEFORE_PROMPT <= onset <= i["t"] + MERGE_POPUP_AFTER_PROMPT:
                if merged is None or abs(i["t"] - onset) < abs(merged["t"] - onset):
                    merged = i
        support = self._object_support(onset - MERGE_POPUP_AFTER_PROMPT, onset + POPUP_FINISH_DELAY)
        if merged is not None:
            merged["merged"] = True

        certain = adjusted in CERTAIN_TIERS
        approx = certain
        reason = f"popup {p['score']:.2f} {p['template']} -> {base_tier} ({rule})"
        if adjusted != base_tier:
            reason += f"; adjusted to {adjusted} (shooting={shooting}, interaction={interaction})"
        elif shooting and not shooting_demotes and base_tier == "MEDIUM":
            reason += f"; shooting ignored: {p['template']} word is specific (combat text does not match it)"
        if promoted:
            adjusted = "HIGH"
            certain = adjusted in CERTAIN_TIERS
            approx = certain
            reason += f"; promoted to HIGH: compression-robust glyph match {robust:.2f} >= {ROBUST_HIGH_MIN:.2f}"
        if not certain and adjusted == "MEDIUM":
            if APPROX_COUNTS_MEDIUM_ALONE.get(p["template"], False):
                approx, reason = True, reason + f"; MEDIUM counted approx: {p['template']} word is reliable"
            elif APPROX_MEDIUM_WITH_OBJECT_SUPPORT and support is not None:
                approx, reason = True, reason + f"; MEDIUM counted approx: chest-object prompt support ({support[0]:.2f})"
        scaled = p.get("scaled")
        if scaled is not None:
            # HUD drawn larger: the exact score says nothing here, so the tier rules above do not apply. APPROX only.
            adjusted, certain, approx = "MEDIUM", False, True
            reason = (f"scale-aware pop-up: blurred {p['template']} match {scaled['blur']:.2f} at x{scaled['scale']} "
                      f"(exact match {p['score']:.2f}; HUD drawn larger) -> MEDIUM, counted approx only (never CERTAIN)")
        if self.scaled_templates:
            self._vote_scale(p)
        if not approx:
            reason += "; NOT counted"
        extra = {"_snapshot": p["roi"]} if "roi" in p else {}
        if scaled is not None:
            extra["scaled_popup"] = {"blur": round(float(scaled["blur"]), 3), "scale": scaled["scale"]}
        return {**extra, "time": onset, "source": "fused" if merged is not None else "popup",
                "base_tier": base_tier, "adjusted_tier": adjusted,
                "popup_score": p["score"], "popup_template": p["template"],
                "interaction_score": max(interaction_score, merged["score"] if merged else 0.0),
                "chest_object_gold": support[1] if support else None, "chest_object_gem": support[2] if support else None,
                "sprite_present": sprite_present, "audio_present": None, "shooting_negative": shooting,
                "ammo_steps": steps, "robust_score": round(robust, 3), "popup_trace": self._popup_trace(p),
                "certain_counted": certain, "approx_counted": approx, "reason": reason}

    def _interaction_event(self, i):
        tp = i["t"]
        obs = [o for o in self.prompt_obs if tp - 0.5 <= o[0] <= tp + 2.5 and o[4]]
        chest_like = bool(obs)
        best = max(obs, key=lambda o: o[1]) if obs else None
        counted = chest_like and INTERACTION_ONLY_COUNTS_APPROX
        steps = sum(1 for s in self.ammo_steps if tp - 1.0 <= s <= tp + 1.0)
        shooting = steps >= evidence.SHOOTING_MIN_STEPS
        if chest_like:
            reason = (f"prompt {i['score']:.2f} + chest-like object (gold {best[2] * 100:.1f}%, gems {best[3] * 100:.2f}%), "
                      f"no popup merged" + ("" if counted else "; NOT counted"))
        else:
            reason = f"prompt {i['score']:.2f} but no chest-like object: generic container/pickup, NOT counted"
        return {"time": tp, "source": "interaction_object", "base_tier": "-", "adjusted_tier": "-",
                "popup_score": None, "popup_template": None, "interaction_score": i["score"],
                "chest_object_gold": best[2] if best else None, "chest_object_gem": best[3] if best else None,
                "sprite_present": False, "audio_present": None, "shooting_negative": shooting, "ammo_steps": steps,
                "certain_counted": bool(counted and INTERACTION_CAN_BE_CERTAIN), "approx_counted": bool(counted),
                "reason": reason}
