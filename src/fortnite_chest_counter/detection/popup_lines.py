"""
Pop-up content tracking (v0.2.2, docs/INVESTIGATION_2026-11-08.md): what is INSIDE the XP pop-up while it stays on screen.

Fortnite does not show a new pop-up for every chest. While a pop-up is on screen, the next chest is ADDED to it:

    +900 XP          +1,800 XP            +1,800 XP             +2,700 XP
    RARE CHEST   ->  RARE CHEST X2    or  RARE CHEST        ->  RARE CHEST
                                          SPRITE CHEST          SPRITE CHEST X2

so a counter that only reacts to a pop-up appearing misses every chest after the first. This module finds the CHEST lines
of the pop-up (every line whose word matches the chest-word template - "RARE CHEST", "SPRITE CHEST", "CHEST"; other lines
such as SPRITE LEVEL or NEW STORM PHASE score clearly lower) and the multiplier ("X2", "X3", ...) right of each word, and
reports a chest each time that content changes:

  * a chest line is added                                      (+1)
  * a multiplier appears on a line ("RARE CHEST" -> "X2")      (+1)
  * a line's multiplier digit changes ("X2" -> "X3")           (+1)

Safeguards (each from a measured failure case):
  * a state must hold for STABLE_SECONDS before it counts - lines, multipliers AND the XP number standing still: after
    every addition the XP number counts up ("+2,016" ... "+2,700") and a state caught mid-animation made a false step;
  * the pop-up's XP total ("+1,800 XP" -> "+2,700 XP") must have changed too: every chest adds XP and the number
    animates, while a lavender wall behind a line or compression noise does not touch it (measured: the XP line matches
    itself at 0.98-1.00 inside a state and drops to 0.32-0.43 at every real addition);
  * the first state of a pop-up never counts by itself - the pop-up's onset already counted one chest, and "X3" seen
    first does not prove three chests were opened while we watched;
  * at most one chest per change, and none within SETTLE_SECONDS of the previous one: opening a chest takes about a
    second (the onset detector's 1 s rule), while the multiplier and XP number keep animating for a moment after a change -
    meanwhile the reference follows the settled content silently (a reference caught mid-animation made a false step);
  * lines and multipliers never go away while a pop-up lives (they all fade together at the end), so a state with
    fewer lines or a lost multiplier is never adopted: a line flickering under the threshold would otherwise come back
    as a "new" line (seen on the reference clip's RARE CHEST line at 0.74-0.77);
  * a digit change must keep the line's strength and ink (a fading pop-up erodes the digit);
  * lines are matched by order from the top: a line added below pushes the others up, which is not a change.

Each frame also reads every chest line's TYPE (chest_types.py, via the `classify` hook) as a vote per line, so the
estimator can label each counted chest with the line that produced it - a label only, never a count.

No OCR: the digit is compared with the line's previous digit only, so X4..X9 need no templates. Pure numpy on the
lavender mask the detector computes anyway; it only runs while a pop-up is being tracked.
"""

from collections import Counter, defaultdict, deque

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter
from scipy.signal import fftconvolve

from fortnite_chest_counter.detection import visual as V

SIGMA = 0.6
STABLE_SECONDS = 0.18          # a new state must hold this long (>= 2 frames) before it counts
GONE_SECONDS = 0.33            # no chest line this long = the pop-up has gone
AROUND_LINES = 6               # the tracker searches this many line heights above / below the pop-up's lines...
AROUND_WORDS = 3               # ...and this many word widths left / right (purple rooms flood the whole box with ink)
MULT_BOX = 16 / 27             # multiplier box width, relative to the chest-word template width (27 px at normal HUD)
DIGIT_FROM = 8 / 27            # the digit starts this far into the box (the "X" comes first)
MULT_MIN_FILL = 0.18           # multiplier present: ink >= this share of the box
HALO_MAX = 0.35                # ...and the rows just above / below it are mostly empty (not a lavender wall behind it)
SAME_DIGIT = 0.90              # blurred digit patches this similar are the same digit (same digit: 0.94-1.00 measured)
NEW_DIGIT = 0.90               # ...below this a new digit (2 vs 3: 0.77-0.85 at normal HUD, 0.86-0.89 at 0.8x), WITH an XP change
XP_CHANGED = 0.6               # the XP line dropped below this similarity to the previous state's (0.32-0.43 at a change)
XP_STEADY = 0.9                # a state is stable only while its XP line keeps this similarity (not counting up)
SETTLE_SECONDS = 0.6           # after a counted change: adopt new states without counting (real steps: 0.93-1.9 s apart)
CHANGE_LEAD = 1.0              # a change is dated at most this long before its new state held still
LINE_WINDOW, LINE_VOTES = 5, 3  # a chest line ADDED counts when more lines show in 3 of the last 5 frames (with the XP
                                # change) - no need to stand still: the new line arrives while the XP number counts up
                                # and an old line may flicker under the threshold (reference clip, 72.4 s)
BELOW_MIN = 0.9                # x the word height: a chest line this far BELOW the known bottom line is a new line - added
                               # lines go to the bottom and push the others UP (a non-chest line moved CHEST up 6 px; a
                               # new chest line appeared 9 px below the old position, 7 px at the 0.8x HUD), so this holds
                               # even while an old line flickers under the threshold
FADE_SCORE_DROP = 0.06         # a digit change must keep the line's word score within this of the previous state
FADE_INK = 0.7                 # ...and at least this share of the previous digit's ink


def _ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def correlation_peaks(mask, blurred_template, min_score, sigma=SIGMA):
    """Every local maximum >= min_score of the blurred NCC map (visual.robust_correlation_at's score, all positions)
    -> [(score, word_y, word_x)] in mask coordinates, word = the unpadded template's top-left."""
    ys, xs = np.nonzero(mask)
    th, tw = blurred_template.shape
    if len(ys) < 20:
        return []
    y0, x0 = max(0, ys.min() - th - 4), max(0, xs.min() - tw - 4)
    img = gaussian_filter(mask[y0:ys.max() + th + 5, x0:xs.max() + tw + 5].astype(np.float64), sigma)
    if img.shape[0] < th or img.shape[1] < tw:
        return []
    n = blurred_template.size
    ts = blurred_template.sum()
    tvar = (blurred_template * blurred_template).sum() - ts * ts / n
    ws = V._window_sums(img, th, tw)
    ws2 = V._window_sums(img * img, th, tw)
    num = fftconvolve(img, blurred_template[::-1, ::-1], mode="valid") - ws * ts / n
    wvar = ws2 - ws * ws / n
    corr = np.where(wvar > 5e-4 * n, num / np.sqrt(np.maximum(tvar * wvar, 1e-9)), 0.0)
    peak = (corr == maximum_filter(corr, size=(max(3, th - 6), tw))) & (corr >= min_score)
    py, px = np.nonzero(peak)
    return [(float(min(corr[y, x], 1.0)), int(y0 + y + 2), int(x0 + x + 2)) for y, x in zip(py, px)]   # +2: padding


class Line:
    __slots__ = ("y", "x", "score", "ink", "has_mult", "digit", "digit_ink")

    def __init__(self, y, x, score, ink, has_mult, digit, digit_ink):
        self.y, self.x, self.score, self.ink = y, x, score, ink
        self.has_mult, self.digit, self.digit_ink = has_mult, digit, digit_ink


def chest_lines(mask, template, blurred_template, min_score):
    """The pop-up's chest lines, top to bottom. `template` = the binary chest word at this HUD size."""
    th, tw = template.shape
    found = []
    for s, y, x in sorted(correlation_peaks(mask, blurred_template, min_score), reverse=True):
        if any(abs(y - f[1]) <= th // 2 + 1 for f in found):            # one line = one word (e.g. "SPRITE" also scores)
            continue
        found.append((s, y, x))
    lines = []
    bw = max(6, int(round(MULT_BOX * tw)))
    d0 = int(round(DIGIT_FROM * tw))
    for s, y, x in sorted(found, key=lambda f: f[1]):
        box = mask[max(0, y - 1):y + th + 1, x + tw + 1:x + tw + 1 + bw]
        if box.shape != (th + 2, bw):                                    # at the edge of the pop-up box
            lines.append(Line(y, x, s, 0, False, None, 0))
            continue
        ink = int(box.sum())
        halo = mask[max(0, y - 4):max(0, y - 1), x + tw + 1:x + tw + 1 + bw].sum() + \
            mask[y + th + 1:y + th + 4, x + tw + 1:x + tw + 1 + bw].sum()
        has = ink >= MULT_MIN_FILL * box.size and halo <= HALO_MAX * ink
        digit = gaussian_filter(box[:, d0:].astype(np.float64), SIGMA) if has else None
        lines.append(Line(y, x, s, ink, has, digit, int(box[:, d0:].sum()) if has else 0))
    return lines


def xp_box(mask, first_line, th, tw):
    """The "+N XP" line above the first chest line (anchored to it: added lines move the whole pop-up)."""
    y0 = max(0, first_line.y - int(round(2.4 * th)))
    x0 = max(0, first_line.x - int(round(2.2 * tw)))
    box = mask[y0:max(y0 + 1, first_line.y - 1), x0:first_line.x + int(round(1.2 * tw))]
    return gaussian_filter(box.astype(np.float64), 0.8) if box.size else None


def shifted_similarity(a, b, r=2):
    """Best NCC of two patches over +-r px shifts (the pop-up drifts by a pixel or two while it animates)."""
    if a is None or b is None:
        return 1.0
    best = -1.0
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            pa = a[max(0, dy):a.shape[0] + min(0, dy), max(0, dx):a.shape[1] + min(0, dx)]
            pb = b[max(0, -dy):b.shape[0] + min(0, -dy), max(0, -dx):b.shape[1] + min(0, -dx)]
            h, w = min(pa.shape[0], pb.shape[0]), min(pa.shape[1], pb.shape[1])
            if h > 2 and w > 2:
                best = max(best, _ncc(pa[:h, :w], pb[:h, :w]))
    return best


def _regresses(old, new):
    """Fewer lines, or a line that lost its multiplier: never real while the pop-up is on screen."""
    return len(new) < len(old) or any(lo.has_mult and not ln.has_mult for lo, ln in zip(old, new))


def _same(a, b):
    """Two observations (lists of Line) show the same content: same lines, same multipliers, same digits."""
    if len(a) != len(b):
        return False
    for la, lb in zip(a, b):
        if la.has_mult != lb.has_mult:
            return False
        if la.has_mult and _ncc(la.digit, lb.digit) < SAME_DIGIT:
            return False
    return True


class PopupTracker:
    """Follows one pop-up's chest lines. update() -> a change dict when a stable content change adds a chest."""

    def __init__(self, template, min_score, fps):
        self.template = template.astype(np.float64)
        self.blurred = V.blur_template(self.template, SIGMA)
        self.min_score = min_score
        self.stable_frames = max(2, int(round(STABLE_SECONDS * fps)))
        self.stable = None             # list of Line: the accepted content
        self.cand, self.cand_n, self.cand_t = None, 0, None
        self.last_seen = None
        self.started = None
        self.run = 0                   # +1 per pop-up followed
        self.stable_xp, self.xp_min = None, 1.0
        self.rejected_without_xp = 0
        self.last_change = None
        self.center = None             # (y, x) of the pop-up's chest lines in mask coordinates, followed every frame
        self.cand_xp, self.diff_since = None, None
        self.same_run = 0
        self.recent_counts = deque(maxlen=LINE_WINDOW)
        self.classify = None           # optional (mask, Line) -> chest type: one vote per line per frame
        self.info = None               # this run's {"votes": {line index: Counter}, "first_count": lines of state 1}

    @property
    def active(self):
        return self.started is not None

    def start(self, t, center=None):
        if self.started is None:
            self.started, self.last_seen, self.center = t, t, center
            self.run += 1
            self.info = {"votes": defaultdict(Counter), "first_count": None}   # a new dict per run: labels keep theirs

    def stop(self):
        self.started = self.stable = self.cand = self.last_seen = self.stable_xp = self.last_change = None
        self.cand_xp = self.diff_since = self.center = None
        self.same_run = 0
        self.cand_n, self.xp_min = 0, 1.0
        self.recent_counts.clear()

    def update(self, t, mask):
        if self.started is None:
            return None
        th, tw = self.template.shape
        y0 = x0 = 0
        if self.center is not None:                                     # only around the pop-up being followed
            cy, cx = self.center
            y0, x0 = max(0, cy - AROUND_LINES * th), max(0, cx - AROUND_WORDS * tw)
            mask = mask[y0:cy + (AROUND_LINES + 1) * th, x0:cx + (AROUND_WORDS + 1) * tw]
        lines = chest_lines(mask, self.template, self.blurred, self.min_score)
        if lines:
            self.center = (y0 + int(np.mean([ln.y for ln in lines])) + th // 2, x0 + lines[0].x + tw // 2)
        if not lines:
            if self.last_seen is not None and t - self.last_seen >= GONE_SECONDS:
                self.stop()                                              # the pop-up has gone
            self.cand, self.cand_n = None, 0
            return None
        self.last_seen = t
        layout = self.stable if self.stable is not None else self.cand
        if self.classify is not None and layout is not None:
            if len(lines) == len(layout):
                pairs = list(enumerate(lines))                          # same layout: line i is the same line
            else:                                                       # a line not visible: match the others by place
                pairs = []
                for ln in lines:
                    i = min(range(len(layout)), key=lambda k: abs(layout[k].y - ln.y))
                    if abs(layout[i].y - ln.y) <= 0.6 * th:
                        pairs.append((i, ln))
            for i, ln in pairs:
                self.info["votes"][i][self.classify(mask, ln)] += 1
        xp = xp_box(mask, lines[0], th, tw)
        count, seen = len(lines), lines
        if self.stable is not None:
            bottom = max(ln.y for ln in self.stable)
            below = [ln for ln in lines if ln.y > bottom + BELOW_MIN * th]
            if below and len(self.stable) + len(below) > count:      # an old line is not visible in this frame
                count, seen = len(self.stable) + len(below), list(self.stable) + below
        self.recent_counts.append(count)
        if self.stable is not None and count > len(self.stable) and                 sum(n > len(self.stable) for n in self.recent_counts) >= LINE_VOTES:
            return self._line_added(t, seen, xp)
        if self.stable is not None and _same(lines, self.stable):
            self.same_run += 1
            if self.same_run >= self.stable_frames:                    # the accepted content re-confirmed (one matching
                self.stable_xp, self.xp_min, self.diff_since = xp, 1.0, None    # noisy frame must not erase a change)
        else:
            self.same_run = 0
            self.diff_since = t if self.diff_since is None else self.diff_since
            if self.stable_xp is not None:
                self.xp_min = min(self.xp_min, shifted_similarity(self.stable_xp, xp))
        if self.cand is not None and _same(lines, self.cand) and shifted_similarity(self.cand_xp, xp) >= XP_STEADY:
            self.cand_n += 1
        else:
            self.cand, self.cand_n, self.cand_t, self.cand_xp = lines, 1, t, xp
        if self.cand_n != self.stable_frames:
            return None
        new, old = self.cand, self.stable
        if old is not None and _regresses(old, new):
            self.cand, self.cand_n = None, 0                             # a flicker, not a change: keep the content
            return None
        began = self.cand_t if self.diff_since is None or self.cand_t - self.diff_since > CHANGE_LEAD else self.diff_since
        xp_moved = self.xp_min < XP_CHANGED
        self.stable, self.stable_xp, self.xp_min = new, xp, 1.0
        self.diff_since, self.same_run = None, self.stable_frames      # any adopted state ends the previous difference
        if old is None:
            self.info["first_count"] = len(new)
            return None                                                  # the pop-up's first state: its onset counted it
        change = self._change(old, new)
        if change is None:
            return None
        if self.last_change is not None and began - self.last_change < SETTLE_SECONDS:
            return None                                                  # still settling after the previous chest
        if not xp_moved:
            self.rejected_without_xp += 1
            return None                                                  # content looked different but no XP was added
        self.last_change = change["t"] = began
        return change

    def _line_added(self, t, lines, xp):
        """More chest lines in most of the recent frames: adopt them (a line added; counted with an XP change)."""
        if self.diff_since is None:
            self.diff_since = t
        if self.stable_xp is not None:
            self.xp_min = min(self.xp_min, shifted_similarity(self.stable_xp, xp))
        began = self.diff_since
        xp_moved = self.xp_min < XP_CHANGED
        self.stable, self.stable_xp, self.xp_min = lines, xp, 1.0
        self.diff_since, self.same_run, self.cand, self.cand_n = None, self.stable_frames, None, 0
        self.recent_counts.clear()
        if self.last_change is not None and began - self.last_change < SETTLE_SECONDS:
            return None
        if not xp_moved:
            self.rejected_without_xp += 1
            return None
        self.last_change = began
        return {"kind": "new_line", "t": began, "lines": len(lines), "line": len(lines) - 1}

    def _change(self, old, new):
        if len(new) > len(old):
            return {"kind": "new_line", "t": self.cand_t, "lines": len(new), "line": len(new) - 1}
        if len(new) < len(old):
            return None                                                  # a line left (reflow / fade): never a chest
        for i, (lo, ln) in enumerate(zip(old, new)):
            if ln.has_mult and not lo.has_mult:
                return {"kind": "multiplier", "t": self.cand_t, "line": i, "change": "appeared"}
            if lo.has_mult and ln.has_mult:
                sim = _ncc(lo.digit, ln.digit)
                if sim < NEW_DIGIT and ln.score >= lo.score - FADE_SCORE_DROP and ln.digit_ink >= FADE_INK * lo.digit_ink:
                    return {"kind": "multiplier", "t": self.cand_t, "line": i, "change": "digit", "similarity": round(sim, 2)}
        return None
