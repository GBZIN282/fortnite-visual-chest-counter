"""
Evidence accumulation: combine the independent chest clues into counted events.

Clues (each one is an independent detector run on captured media only):

    popup   the word CHEST in the XP popup (visual_detector.py)   near-certain
    sprite  "+75 CONTAINER OPENED" tag by the sprite badge          strong, but
            (sprite_detector.py)                                    conditional
            and generic (any container)
    audio   chest-like 4-11 kHz burst accepted by the audio         weak
            verifier (detector.py)

How clues are grouped
---------------------
Popup events are ANCHORS: each other clue is attached to the nearest anchor
within GROUP_WINDOW_SECONDS. Clues with no anchor are grouped among themselves
(single linkage, gap <= ORPHAN_GAP_SECONDS). Anchoring on the popup rather than
chaining every clue together keeps two chests 2 s apart (70.2 s and 72.2 s) as
two events.

Decision per group = sum of the weights of the clue types present:

    >= COUNT_SCORE      -> COUNT      (added to the chest total)
    >= CANDIDATE_SCORE  -> CANDIDATE  (reported, not counted)
    otherwise           -> ignored

Confidence tiers (interpretation layer only)
--------------------------------------------
Every group also gets a tier - CERTAIN / HIGH / MEDIUM / LOW / REJECT - from the
RAW popup score and which supporting clues are present. Tiers are evidence
categories, NOT probabilities, and they change neither the grouping nor the
COUNT/CANDIDATE decision. The cut-offs below are provisional and were not tuned
on any clip; the raw scores are always kept so the tiers can be calibrated once
predictions have been verified by hand. The same raw score does not necessarily
mean the same thing in every language (the Portuguese BAU template is much
shorter than the English CHEST one).

WARNING - the weights are PRIORS, NOT FITTED. The test clip has no real chest
without a popup, so the "no popup" branch (sprite + audio) cannot be validated
here; it exists to show the structure. Do not tune these numbers on this clip.

Usage
-----
    python -m fortnite_chest_counter.detection.fusion
"""

from pathlib import Path

import numpy as np

from fortnite_chest_counter.detection import audio as detector
from fortnite_chest_counter.detection import sprite as sprite_detector
from fortnite_chest_counter.detection import visual as V


# ==================================================================
# PARAMETERS (priors, unvalidated)
# ==================================================================

CLUE_WEIGHTS = {"popup": 1.00, "sprite": 0.75, "audio": 0.35}
COUNT_SCORE = 1.00
CANDIDATE_SCORE = 0.50

GROUP_WINDOW_SECONDS = 1.5      # how far a clue may be from its popup anchor
ORPHAN_GAP_SECONDS = 1.0        # clustering of clues that have no popup
MATCH_TOLERANCE_SECONDS = 0.75

# Provisional tier cut-offs on the raw popup template score. "Supporting clue"
# means a sprite OR audio clue in the same group.
TIER_CERTAIN_POPUP = 0.90
TIER_CERTAIN_POPUP_WITH_SUPPORT = 0.85
TIER_HIGH_POPUP = 0.85
TIER_HIGH_POPUP_WITH_SUPPORT = 0.80
TIER_MEDIUM_POPUP = 0.75          # equals the popup fire threshold: every popup event is at least MEDIUM
TIERS = ("CERTAIN", "HIGH", "MEDIUM", "LOW", "REJECT")


def confidence_tier(popup_score, has_sprite, has_audio):
    """-> (tier, rule that assigned it). Evidence category, not a probability."""
    support = has_sprite or has_audio
    if popup_score is not None:
        if popup_score >= TIER_CERTAIN_POPUP:
            return "CERTAIN", f"popup >= {TIER_CERTAIN_POPUP:.2f}"
        if popup_score >= TIER_CERTAIN_POPUP_WITH_SUPPORT and support:
            return "CERTAIN", f"popup >= {TIER_CERTAIN_POPUP_WITH_SUPPORT:.2f} + supporting clue"
        if popup_score >= TIER_HIGH_POPUP:
            return "HIGH", f"popup >= {TIER_HIGH_POPUP:.2f}"
        if popup_score >= TIER_HIGH_POPUP_WITH_SUPPORT and support:
            return "HIGH", f"popup >= {TIER_HIGH_POPUP_WITH_SUPPORT:.2f} + supporting clue"
        if popup_score >= TIER_MEDIUM_POPUP:
            return "MEDIUM", f"popup >= {TIER_MEDIUM_POPUP:.2f}"
        return "LOW", "weak popup"
    if has_sprite and has_audio:
        return "MEDIUM", "sprite + audio"
    if has_sprite:
        return "LOW", "sprite only"
    return "REJECT", "audio only"


def nearest_detail(details, t):
    return min(details, key=lambda d: abs(d["time"] - t)) if details else None


def describe_groups(groups, popup_detail, sprite_detail):
    """
    One row per non-ignored group, keeping the RAW evidence next to the decision
    and the tier: time, fused score, decision, tier, rule, popup score/template,
    sprite/audio present, clue list.
    """
    rows = []
    for g in groups:
        score = score_group(g)
        decision = "COUNT" if score >= COUNT_SCORE else "CANDIDATE" if score >= CANDIDATE_SCORE else None
        if decision is None:
            continue
        popup = nearest_detail(popup_detail, g["clues"]["popup"][0]) if "popup" in g["clues"] else None
        sprite = nearest_detail(sprite_detail, g["clues"]["sprite"][0]) if "sprite" in g["clues"] else None
        tier, rule = confidence_tier(popup["score"] if popup else None, "sprite" in g["clues"], "audio" in g["clues"])
        rows.append({
            "time": g["time"], "fused": score, "decision": decision, "tier": tier, "rule": rule,
            "popup_score": popup["score"] if popup else None,
            "template": popup["template"] if popup else "-",
            "sprite": "sprite" in g["clues"], "audio": "audio" in g["clues"],
            "sprite_score": sprite["score"] if sprite else None,
            "clues": ",".join(g["clues"]),
        })
    return rows


def mmss(seconds):
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes):02d}:{rest:05.2f}"


def load_verified_labels(path):
    """
    Read a reviewed prediction file -> {timestamp text: True/False} for rows whose
    VERIFIED= field is YES/NO. Handles rows with or without a leading '#NNN' id
    ('#001 ...' is data; '# comment' is a comment). Rows left blank are skipped.
    """
    import re

    labels = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or (line.startswith("#") and not re.match(r"^#M?\d+\s", line)):
            continue
        tokens = line.split()
        if tokens[0].startswith("#"):
            tokens = tokens[1:]
        for token in tokens:
            if token.startswith("VERIFIED="):
                value = token.split("=", 1)[1].upper()
                if value in ("YES", "NO"):
                    labels[tokens[0]] = value == "YES"
    return labels


def format_row(r):
    popup = f"{r['popup_score']:.2f}" if r["popup_score"] is not None else " -  "
    ident = f"#{r['id']:03d}  " if "id" in r else ""
    return (f"{ident}{mmss(r['time'])}   {r['decision']:9s} {r['tier']:8s} fused={r['fused']:.2f}   popup={popup}   "
            f"{r['template']:8s} sprite={'yes' if r['sprite'] else 'no ':3s} audio={'yes' if r['audio'] else 'no'}")


def tier_distribution(rows):
    """Printable tier counts, overall and per popup template."""
    lines = ["Confidence distribution (evidence tiers, not probabilities):"]
    for tier in TIERS:
        n = sum(r["tier"] == tier for r in rows)
        if n or tier != "REJECT":
            lines.append(f"  {tier + ':':9s}{n:3d}")
    templates = sorted({r["template"] for r in rows if r["template"] != "-"})
    for tpl in templates:
        counts = ", ".join(f"{t} {sum(r['tier'] == t and r['template'] == tpl for r in rows)}" for t in TIERS[:4])
        lines.append(f"  by template {tpl}: {counts}")
    return "\n".join(lines)


def collect_clues(truth):
    """-> ({clue_name: np.array of event times}, popup_details, sprite_details)"""
    templates = V.load_templates()
    times, scores, ys, xs, which = V.score_video(templates)
    popup = V.detect_events(times, scores, ys, xs)
    popup_detail = V.popup_event_details(times, scores, ys, xs, which, templates, popup)

    s_template = sprite_detector.load_or_build_template()
    s_times, s_scores = sprite_detector.score_video(s_template)
    zeros = np.zeros(len(s_times), dtype=int)
    sprite = V.detect_events(s_times, s_scores, zeros, zeros,
                             sprite_detector.EVENT_HIGH_THRESHOLD, sprite_detector.EVENT_LOW_THRESHOLD)
    sprite_detail = sprite_detector.event_details(s_times, s_scores, sprite)

    audio, _, _, _ = detector.audio_chest_events(truth)
    return {"popup": popup, "sprite": sprite, "audio": audio}, popup_detail, sprite_detail


def group_clues(clues):
    """Return a list of groups: {'time', 'clues': {name: [times]}}."""
    anchors = [{"time": t, "clues": {"popup": [t]}} for t in clues["popup"]]
    orphans = []
    for name in ("sprite", "audio"):
        for t in clues[name]:
            if anchors:
                nearest = min(anchors, key=lambda g: abs(g["time"] - t))
                if abs(nearest["time"] - t) <= GROUP_WINDOW_SECONDS:
                    nearest["clues"].setdefault(name, []).append(t)
                    continue
            orphans.append((t, name))
    orphans.sort()
    group = None
    for t, name in orphans:
        if group is None or t - group["last"] > ORPHAN_GAP_SECONDS:
            group = {"time": t, "last": t, "clues": {}}
            anchors.append(group)
        group["clues"].setdefault(name, []).append(t)
        group["last"] = t
    return sorted(anchors, key=lambda g: g["time"])


def score_group(group):
    return sum(CLUE_WEIGHTS[name] for name in group["clues"])


def main():
    truth = detector.load_ground_truth(detector.GROUND_TRUTH_FILE)
    print(f"Ground truth ({len(truth)} chests): " + ", ".join(f"{t:.1f}" for t in truth))
    clues, popup_detail, sprite_detail = collect_clues(truth)
    print("Clue event counts: " + ", ".join(f"{k}={len(v)}" for k, v in clues.items()))

    groups = group_clues(clues)
    rows = describe_groups(groups, popup_detail, sprite_detail)
    ignored = len(groups) - len(rows)
    counted = [r["time"] for r in rows if r["decision"] == "COUNT"]
    candidates = [r["time"] for r in rows if r["decision"] == "CANDIDATE"]

    print("\nGroups scoring >= CANDIDATE_SCORE:")
    for r in rows:
        print("  " + format_row(r) + f"   [{r['rule']}]")
    print(f"\n{len(groups)} groups total; {len(counted)} counted, {len(candidates)} candidates, "
          f"{ignored} ignored (single weak audio clue)")
    print("\n" + tier_distribution(rows))

    detector.report("FUSED COUNT (COUNT decisions only)", truth, np.array(counted), MATCH_TOLERANCE_SECONDS)
    print(f"\nESTIMATED CHEST COUNT: {len(counted)}   (labelled: {len(truth)})")
    if candidates:
        print("Candidates NOT counted: " + ", ".join(f"{t:.1f}s" for t in candidates))


if __name__ == "__main__":
    main()
