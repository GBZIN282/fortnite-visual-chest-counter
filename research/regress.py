"""
Experiment harness: run the full recordings through the detector and diff the event lists against a snapshot.

    python research/regress.py snapshot --tag v0.1.0            # (re)write tests/baselines/<clip>_<tag>.json from a fresh run
    python research/regress.py compare  --tag v0.1.0            # run + print BASELINE vs EXPERIMENT per clip
    python research/regress.py compare  --tag v0.1.0 --video en=analysis_output/variants/en_tw6000.mp4   # degraded variant

Needs samples/ locally (not in Git). Exit code 1 if any baseline clip regresses (lost event, tier/count change that lowers
a verified real chest, or a new counted event on a verified non-chest).
"""
import argparse, glob, json, subprocess, sys, tempfile
from pathlib import Path

from fortnite_chest_counter import counter as C

CLIPS = {"en": ("Fortnites-NEW", "samples/video tests/Fortnites-NEW-HD-No-Audio.mp4"),
         "ps5": ("Fortnite-PS5-Pro", "samples/video tests/Fortnite-PS5-Pro-HD-No-Audio.mp4"),
         # Twitch-like degradations (research/make_variants.sh): 1080p, x264 at a streaming bitrate. Same timeline, same labels.
         "en_tw6000": ("Fortnites-NEW", "analysis_output/variants/en_tw6000.mp4"),
         "en_tw2500": ("Fortnites-NEW", "analysis_output/variants/en_tw2500.mp4"),
         "ps5_tw6000": ("Fortnite-PS5-Pro", "analysis_output/variants/ps5_tw6000.mp4"),
         "ps5_tw2500": ("Fortnite-PS5-Pro", "analysis_output/variants/ps5_tw2500.mp4")}
DEFAULT_CLIPS = ["en", "ps5"]
KEYS = ("time", "source", "popup_score", "popup_template", "base_tier", "adjusted_tier", "shooting_negative", "ammo_steps",
        "interaction_score", "sprite_present", "certain_counted", "approx_counted")


def run_clip(video, tmp, sets=()):
    """Run `simulate` in a fresh process; `sets` = ["NAME=python-literal", ...] overrides estimator constants first."""
    tmp = Path(tmp)
    argv = ["simulate", "--video", str(video), "--reset", "--no-evaluate",
            "--state", str(tmp / "s.json"), "--obs-dir", str(tmp / "o"), "--log-dir", str(tmp / "l")]
    lines = ["import ast, sys", "import fortnite_chest_counter.estimator as E"]
    lines += [f"setattr(E, {k!r}, ast.literal_eval({v!r}))" for k, v in (x.split("=", 1) for x in sets)]
    lines += ["from fortnite_chest_counter.counter import main", f"sys.exit(main({argv!r}))"]
    code = "\n".join(lines)
    subprocess.run([sys.executable, "-c", code], check=True, stdout=subprocess.DEVNULL)
    rows = [json.loads(l) for l in open(glob.glob(str(tmp / "l" / "*.jsonl"))[0], encoding="utf-8") if l.strip()]
    out = []
    for e in rows:
        if "time" in e and e.get("source") != "manual":
            r = {k: e.get(k) for k in KEYS}
            r["chest_object"] = e.get("chest_object_gold") is not None
            out.append(r)
    return out


def classify(name, t):
    items = C.known_items(name)
    m = [q for q in items if q[0] - q[1] <= t <= q[0] + q[2]]
    q = min(m, key=lambda q: abs(q[0] - t)) if m else None
    return {"chest": "REAL", "false": "FALSE", "non-chest": "NONCHEST"}[q[3]] if q else "unknown"


def totals(ev):
    return sum(e["certain_counted"] for e in ev), sum(e["approx_counted"] for e in ev)


def compare(clip, base, new, tol=0.6):
    name = CLIPS[clip][0]
    bc, ba = totals(base); nc, na = totals(new)
    print(f"\n{clip.upper():4}  events {len(base)} -> {len(new)}   certain {bc} -> {nc}   approx {ba} -> {na}")
    bad = 0
    used = set()
    for b in base:
        m = [(abs(n["time"] - b["time"]), i) for i, n in enumerate(new) if i not in used and abs(n["time"] - b["time"]) <= tol]
        if not m:
            cls = classify(name, b["time"])
            print(f"  LOST   {C.mmss(b['time'])} {cls:8} was {b['adjusted_tier']} C={int(b['certain_counted'])} A={int(b['approx_counted'])}")
            bad += cls == "REAL" and b["approx_counted"]
            continue
        _, i = min(m); used.add(i); n = new[i]
        cls = classify(name, b["time"])
        if (b["adjusted_tier"], b["certain_counted"], b["approx_counted"]) != (n["adjusted_tier"], n["certain_counted"], n["approx_counted"]) \
                or abs((b["popup_score"] or 0) - (n["popup_score"] or 0)) > 0.005:
            print(f"  CHANGE {C.mmss(b['time'])} {cls:8} score {b['popup_score'] or 0:.3f}->{n['popup_score'] or 0:.3f} "
                  f"tier {b['adjusted_tier']}->{n['adjusted_tier']} C {int(b['certain_counted'])}->{int(n['certain_counted'])} "
                  f"A {int(b['approx_counted'])}->{int(n['approx_counted'])}")
            if cls in ("FALSE", "NONCHEST") and n["approx_counted"] and not b["approx_counted"]:
                bad += 1
            if cls == "REAL" and (b["approx_counted"] and not n["approx_counted"] or b["certain_counted"] and not n["certain_counted"]):
                bad += 1
    for i, n in enumerate(new):
        if i not in used:
            cls = classify(name, n["time"])
            print(f"  NEW    {C.mmss(n['time'])} {cls:8} {n['adjusted_tier']} score {n['popup_score'] or 0:.3f} C={int(n['certain_counted'])} A={int(n['approx_counted'])}")
            bad += cls in ("FALSE", "NONCHEST") and n["approx_counted"]
    if len(base) == len(new) and not bad and (bc, ba) == (nc, na) and not any(
            (b["adjusted_tier"], b["certain_counted"], b["approx_counted"]) != (n["adjusted_tier"], n["certain_counted"], n["approx_counted"])
            for b, n in zip(base, new)):
        print("  identical decisions")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["snapshot", "compare"])
    ap.add_argument("--tag", default="v0.1.0")
    ap.add_argument("--video", action="append", default=[], help="clip=path override (e.g. a degraded variant)")
    ap.add_argument("--clips", nargs="*", default=DEFAULT_CLIPS, help=f"any of {list(CLIPS)}")
    ap.add_argument("--set", dest="sets", action="append", default=[], help="NAME=VALUE estimator constant override (experiments)")
    ap.add_argument("--jobs", type=int, default=2, help="clips to run in parallel")
    a = ap.parse_args()
    override = dict(v.split("=", 1) for v in a.video)
    bad = 0
    from concurrent.futures import ThreadPoolExecutor

    def one(clip):
        with tempfile.TemporaryDirectory() as tmp:
            return clip, run_clip(override.get(clip, CLIPS[clip][1]), tmp, a.sets)
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        results = dict(pool.map(one, a.clips))
    if a.sets:
        print("experiment:", ", ".join(a.sets))
    for clip in a.clips:
        snap = Path("tests/baselines") / f"{clip}_{a.tag}.json"
        ev = results[clip]
        if a.mode == "snapshot":
            snap.write_text(json.dumps(ev, indent=1) + "\n", encoding="utf-8", newline="\n")
            print(f"{snap}: {len(ev)} events, certain/approx {totals(ev)}")
        else:
            bad += compare(clip, json.loads(snap.read_text(encoding="utf-8")), ev)
    if a.mode == "compare":
        print("\nRESULT:", "REGRESSION" if bad else "no regressions vs", a.tag)
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
