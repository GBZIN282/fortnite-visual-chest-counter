"""
Real-world detection cases (tests/cases/cases.json): every confirmed failure from a diagnostic capture becomes a case with
truth labels, so each detector change is measured against all of them (misses, duplicates, false counts).

    python research/cases.py fetch --from "C:/.../captures"   copy the needed 10 s segments into samples/cases/ (not in Git)
    python research/cases.py run [--case NAME ...] [--set NAME=value ...] [--json OUT]
    python research/cases.py fixtures                          write tests/fixtures/popups/<case>.npz (pop-up box masks)

`run` replays the full RGB frames through the real ChestEstimator (current code, default [detector] settings);
--set overrides estimator constants first (e.g. --set SMALL_HUD_POPUPS=False) to compare variants. A detector event
matches a truth row if it starts within [t - 0.5, t + 2.5] s; a second event on the same truth is a DUPLICATE; an event
near no chest (or near a not_chest row) is FALSE.
"""

import argparse
import ast
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from fortnite_chest_counter import estimator as E  # noqa: E402
from fortnite_chest_counter import settings  # noqa: E402
from fortnite_chest_counter.detection import visual as V  # noqa: E402

CASES_FILE = ROOT / "tests" / "cases" / "cases.json"
FOOTAGE = ROOT / "samples" / "cases"
FIXTURES = ROOT / "tests" / "fixtures" / "popups"
FPS = 15
BEFORE, AFTER = 0.5, 2.5                       # an event may start this long before / after the truth moment


def load_cases():
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


def _clip(folder, clip_file):
    clips = json.loads((folder / "video" / "clips.json").read_text(encoding="utf-8"))
    return next(c for c in clips if c["file"] == clip_file)


def _segments(folder):
    rows = []
    for line in (folder / "video" / "segments.csv").read_text(encoding="utf-8").splitlines():
        name, a, b = line.split(",")
        rows.append((name, float(a), float(b)))
    return rows


def needed_segments(folder, case):
    clip = _clip(folder, case["clip"])
    r0, r1 = clip["start"] + case["window"][0], clip["start"] + case["window"][1]
    return clip, [s for s in _segments(folder) if s[0] in clip["segments"] and s[2] > r0 and s[1] < r1]


def fetch(source_root):
    source_root = Path(source_root)
    for name, case in load_cases().items():
        src = source_root / case["capture"]
        dst = FOOTAGE / case["capture"]
        (dst / "video").mkdir(parents=True, exist_ok=True)
        for f in ("capture.json", "timeline.csv", "labels.csv", "events.jsonl", "marks.jsonl"):
            if (src / f).exists() and not (dst / f).exists():
                shutil.copy2(src / f, dst / f)
        for f in ("clips.json", "segments.csv"):
            shutil.copy2(src / "video" / f, dst / "video" / f)
        _, segs = needed_segments(src, case)
        for seg, _, _ in segs:
            if not (dst / "video" / seg).exists():
                shutil.copy2(src / "video" / seg, dst / "video" / seg)
        print(f"{name}: {len(segs)} segment(s) -> {dst}")


def case_frames(case, root=FOOTAGE):
    """(clip seconds, 1280x720 RGB) over the case window, decoded from the copied segments."""
    folder = root / case["capture"]
    clip, segs = needed_segments(folder, case)
    if not segs:
        raise FileNotFoundError(f"no footage for {case['capture']} {case['clip']} (run: research/cases.py fetch)")
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "window.ffconcat"
        listing.write_text("ffconcat version 1.0\n" + "".join(
            f"file '{(folder / 'video' / s).as_posix()}'\n" for s, _, _ in segs), encoding="utf-8")
        first = segs[0][1]
        start = clip["start"] + case["window"][0] - first
        dur = case["window"][1] - case["window"][0]
        cmd = ["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-ss", f"{start:.3f}",
               "-t", f"{dur:.3f}", "-vf", f"{V.scale_filter()},fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8)
        size = V.NORMALIZED_WIDTH * V.NORMALIZED_HEIGHT * 3
        i = 0
        try:
            while True:
                raw = p.stdout.read(size)
                if len(raw) < size:
                    break
                yield case["window"][0] + i / FPS, np.frombuffer(raw, np.uint8).reshape(V.NORMALIZED_HEIGHT,
                                                                                          V.NORMALIZED_WIDTH, 3)
                i += 1
        finally:
            p.kill()
            p.wait()


def run_estimator(frames, sets=()):
    E.configure(settings.DEFAULTS["detector"])
    for k, v in sets:
        setattr(E, k, v)
    est = E.ChestEstimator()
    events, ms = [], []
    for t, frame in frames:
        a = time.perf_counter()
        events += est.process_frame(t, frame)
        ms.append(1000 * (time.perf_counter() - a))
    events += est.flush()
    for ev in events:
        ev.pop("_snapshot", None)
    return events, ms, est


def score(case, events):
    """-> per-truth matches and the counted events that matched nothing."""
    counted = sorted((e for e in events if e.get("approx_counted")), key=lambda e: e["time"])
    chests = [dict(r, hits=[]) for r in case["truth"] if r["what"] != "not_chest"]
    others = [r for r in case["truth"] if r["what"] == "not_chest"]
    false, dup = [], []
    for e in counted:
        cands = [c for c in chests if c["t"] - BEFORE <= e["time"] <= c["t"] + AFTER]
        free = [c for c in cands if not c["hits"]]
        if free:
            min(free, key=lambda c: abs(c["t"] - e["time"]))["hits"].append(e)
        elif cands:
            dup.append(e)
        else:
            near = [r for r in others if r["t"] - BEFORE <= e["time"] <= r["t"] + AFTER]
            false.append((e, near[0]["text"] if near else ""))
    return chests, dup, false


def describe(e):
    kind = "CERTAIN" if e.get("certain_counted") else "APPROX"
    extra = ""
    if e.get("scaled_popup"):
        extra = f" scaled x{e['scaled_popup']['scale']}"
    if e.get("increment"):
        extra += f" {e['increment']['kind']}"
    if e.get("chest_type"):
        extra += f" type={e['chest_type']}"
    return f"{e['time']:.2f}s {kind} {e['adjusted_tier']}{extra}"


def run(names, sets, out=None, quiet=False):
    cases = load_cases()
    summary = {}
    for name in names or cases:
        case = cases[name]
        if case.get("known_limitation"):
            continue
        try:
            events, ms, est = run_estimator(case_frames(case), sets)
        except FileNotFoundError as error:
            print(f"{name}: SKIPPED ({error})")
            continue
        chests, dup, false = score(case, events)
        got = sum(1 for c in chests if c["hits"])
        summary[name] = {"real": len(chests), "found": got, "missed": len(chests) - got, "duplicates": len(dup),
                         "false": len(false), "certain": sum(1 for c in chests for e in c["hits"][:1] if e.get("certain_counted")),
                         "ms_mean": round(float(np.mean(ms)), 2), "ms_p99": round(float(np.percentile(ms, 99)), 1),
                         "types": [(c["type"], c["hits"][0].get("chest_type") if c["hits"] else None) for c in chests]}
        if not quiet:
            print(f"\n=== {name}  ({case['source']}; HUD {case['hud']})")
            for c in chests:
                hit = "; ".join(describe(e) for e in c["hits"]) or "MISSED"
                print(f"  {c['t']:7.2f}s {c['what']:10s} {c['type']:6s} {c['text'][:44]:44s} -> {hit}")
            for e in dup:
                print(f"  DUPLICATE  {describe(e)}  {e['reason'][:100]}")
            for e, near in false:
                print(f"  FALSE      {describe(e)}  {near}  {e['reason'][:100]}")
        s = summary[name]
        print(f"  {name}: {s['found']}/{s['real']} found, {s['missed']} missed, {s['duplicates']} duplicate, "
              f"{s['false']} false; first hit CERTAIN {s['certain']}; {s['ms_mean']} ms/frame (p99 {s['ms_p99']})")
    tot = {k: sum(s[k] for s in summary.values()) for k in ("real", "found", "missed", "duplicates", "false")}
    print(f"\nTOTAL: {tot['found']}/{tot['real']} found, {tot['missed']} missed, {tot['duplicates']} duplicates, "
          f"{tot['false']} false")
    if out:
        Path(out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def fixtures():
    """Pop-up box lavender masks (bit-packed) for every frame of every case window -> tests/fixtures/popups/."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, case in load_cases().items():
        if case.get("known_limitation"):
            continue
        times, masks = [], []
        for t, frame in case_frames(case):
            roi = frame[V.ROI_Y:V.ROI_Y + V.ROI_H, V.ROI_X:V.ROI_X + V.ROI_W]
            times.append(round(t, 4))
            masks.append(np.packbits(V.lavender_mask(roi).astype(bool), axis=None))
        path = FIXTURES / f"{name}.npz"
        np.savez_compressed(path, times=np.array(times), masks=np.array(masks), shape=np.array([V.ROI_H, V.ROI_W]))
        print(f"{name}: {len(times)} frames -> {path} ({path.stat().st_size / 1024:.0f} KB)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--from", dest="src", required=True)
    r = sub.add_parser("run")
    r.add_argument("--case", action="append")
    r.add_argument("--set", action="append", default=[])
    r.add_argument("--json")
    r.add_argument("--quiet", action="store_true")
    sub.add_parser("fixtures")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.src)
    elif a.cmd == "run":
        sets = [(k, ast.literal_eval(v)) for k, v in (s.split("=", 1) for s in a.set)]
        run(a.case, sets, a.json, a.quiet)
    else:
        fixtures()


if __name__ == "__main__":
    main()
