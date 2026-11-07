"""
`review`: replay diagnostic captures through the CURRENT detector and compare.

    python -m fortnite_chest_counter review captures                 # every capture folder below captures/
    python -m fortnite_chest_counter review captures/20261107_203011  # one capture

For each capture (see capture.py) every recorded clip is analysed again, from its first frame, exactly like a recording
("Analyse a recording"), with the detector settings that were used live (`--current-settings` = config.toml instead).
The result is compared with
  * the live decisions (events.jsonl): same / changed / only live / only replay - a detector change shows up here;
  * the person's labels (labels.csv "truth" column): real chests found or missed, things wrongly counted.
Writes review.txt + review.json into each capture folder and prints a summary over all of them. Read-only otherwise:
it never changes the live counter, the OBS files or the recordings.
"""

import json
import subprocess
from pathlib import Path

import numpy as np

from fortnite_chest_counter import paths, settings
from fortnite_chest_counter.capture import find_captures, mmss, read_labels
from fortnite_chest_counter.detection import visual as V

MATCH_SECONDS = 0.6                       # two decisions this close in time are the same chest (as research/regress.py)
REAL = ("chest", "sprite_chest", "missed_chest", "missed")
NOT_REAL = ("not_chest", "no", "false")


def frames(path, fps):
    """(clip seconds, 1280x720 RGB) for a recorded clip (.ffconcat playlist or a video file)."""
    path = Path(path)
    cmd = ["ffmpeg", "-v", "error"] + (["-f", "concat", "-safe", "0"] if path.suffix == ".ffconcat" else [])
    cmd += ["-i", str(path), "-vf", f"{V.scale_filter()},fps={fps}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8,
                               creationflags=paths.child_process_flags())
    size = V.NORMALIZED_WIDTH * V.NORMALIZED_HEIGHT * 3
    i = 0
    try:
        while True:
            raw = process.stdout.read(size)
            if len(raw) < size:
                break
            yield i / fps, np.frombuffer(raw, np.uint8).reshape(V.NORMALIZED_HEIGHT, V.NORMALIZED_WIDTH, 3)
            i += 1
    finally:
        process.kill()


def replay(folder, detector_cfg, progress=None):
    """Run the detector over every clip of one capture. -> list of events with live times."""
    from fortnite_chest_counter import estimator
    info = json.loads((folder / "capture.json").read_text(encoding="utf-8"))
    clips = json.loads((folder / "video" / "clips.json").read_text(encoding="utf-8"))
    fps = info["fps"]
    live_t = np.loadtxt(folder / "timeline.csv", delimiter=",", skiprows=1, usecols=1, ndmin=1)
    estimator.configure(detector_cfg)
    out = []
    for clip in clips:
        est = estimator.ChestEstimator()
        first = int(round(clip["start"] * fps))
        found, last = [], 0.0
        for t, frame in frames(folder / clip["file"], fps):
            found += est.process_frame(t, frame)
            last = t
        found += est.flush()
        for ev in found:
            ev.pop("_snapshot", None)
            k = min(first + int(round(ev["time"] * fps)), len(live_t) - 1)
            ev["clip"], ev["clip_time"], ev["live_time"] = clip["file"], round(ev["time"], 3), float(live_t[k])
            out.append(ev)
        if progress:
            progress(clip, last)
    return out


def _decision(ev):
    return "certain" if ev.get("certain_counted") else "approx" if ev.get("approx_counted") else "not counted"


def _near(items, t, key):
    best = min(items, key=lambda e: abs(e[key] - t), default=None)
    return best if best is not None and abs(best[key] - t) <= MATCH_SECONDS else None


def _seconds(stamp):
    minutes, _, rest = str(stamp).partition(":")
    return int(minutes) * 60 + float(rest)


def compare(folder, replayed):
    live = [json.loads(l) for l in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] \
        if (folder / "events.jsonl").exists() else []
    rows, same = [], 0
    for ev in live:
        other = _near(replayed, ev["time"], "live_time")
        a, b = _decision(ev), _decision(other) if other else "-"
        rows.append((ev["time"], a, b, ev.get("adjusted_tier"), other.get("adjusted_tier") if other else "-"))
        same += a == b and (other or {}).get("adjusted_tier") == ev.get("adjusted_tier")
    for ev in replayed:
        if not _near(live, ev["live_time"], "time"):
            rows.append((ev["live_time"], "-", _decision(ev), "-", ev.get("adjusted_tier")))
    rows.sort()
    labels = []
    for lab in read_labels(folder):
        try:
            t = _seconds(lab["live_time"])
        except (TypeError, ValueError):
            continue                               # a hand-edited row without a usable time (mm:ss.ss)
        truth = lab["truth"].strip().lower()
        hit = _near([e for e in replayed if e.get("approx_counted")], t, "live_time")
        live_hit = _near([e for e in live if e.get("approx_counted")], t, "time")
        labels.append({"id": lab["id"], "time": t, "truth": truth, "replay": _decision(hit) if hit else "not counted",
                       "live": _decision(live_hit) if live_hit else "not counted"})
    return {"live": len(live), "replay": len(replayed), "same": same, "rows": rows, "labels": labels}


def score(labels, which):
    real = [l for l in labels if l["truth"] in REAL]
    wrong = [l for l in labels if l["truth"] in NOT_REAL]
    return {"real": len(real), "found_certain": sum(l[which] == "certain" for l in real),
            "found_approx": sum(l[which] in ("certain", "approx") for l in real),
            "wrongly_counted": sum(l[which] in ("certain", "approx") for l in wrong), "labelled_not_chest": len(wrong)}


def report(folder, result, detector_cfg):
    lines = [f"Review of {folder.name} - replayed with the current detector", "",
             f"Live decisions: {result['live']}   replay decisions: {result['replay']}   identical: {result['same']}",
             f"Detector settings used: languages {detector_cfg['languages']}, certain_min_tier {detector_cfg['certain_min_tier']}",
             "", "  live time   live          replay        (tier live -> replay)"]
    for t, a, b, ta, tb in result["rows"]:
        flag = "" if (a, ta) == (b, tb) else "   <- different"
        lines.append(f"  {mmss(t):9s}  {a:12s}  {b:12s}  ({ta} -> {tb}){flag}")
    if result["labels"]:
        lines += ["", "Labels (labels.csv truth) - counted live / counted on replay:"]
        for lab in result["labels"]:
            lines.append(f"  {mmss(lab['time']):9s}  {lab['id']:6s} truth={lab['truth']:13s} live={lab['live']:12s} "
                         f"replay={lab['replay']}")
        for which in ("live", "replay"):
            s = score(result["labels"], which)
            lines.append(f"  {which:6s}: real chests {s['real']}, found as CERTAIN {s['found_certain']}, counted at all "
                         f"(APPROX) {s['found_approx']}, labelled not-a-chest but counted {s['wrongly_counted']} of "
                         f"{s['labelled_not_chest']}")
    else:
        lines += ["", "No labels yet: fill in the 'truth' column of labels.csv to measure accuracy."]
    return "\n".join(lines) + "\n"


def run(path, current_settings=False, out=print):
    captures = find_captures(path)
    if not captures:
        raise FileNotFoundError(f"no diagnostic captures found in {path} (folders with capture.json)")
    cfg, _, _ = settings.load_config()
    totals = {"live": {}, "replay": {}}
    for folder in captures:
        info = json.loads((folder / "capture.json").read_text(encoding="utf-8"))
        detector_cfg = cfg["detector"] if current_settings or "detector" not in info.get("app", {}) else \
            {**settings.DEFAULTS["detector"], **info["app"]["detector"]}
        out(f"Replaying {folder.name} ({info.get('mode')}, {info.get('clips', '?')} clip(s)) ...")
        replayed = replay(folder, detector_cfg)
        result = compare(folder, replayed)
        text = report(folder, result, detector_cfg)
        (folder / "review.txt").write_text(text, encoding="utf-8")
        (folder / "review.json").write_text(json.dumps({"detector": detector_cfg, **result,
                                                        "replay_events": [{k: v for k, v in e.items() if k != "popup_trace"}
                                                                          for e in replayed]},
                                                       indent=1, default=str), encoding="utf-8")
        out(text)
        for which in totals:
            for k, v in score(result["labels"], which).items():
                totals[which][k] = totals[which].get(k, 0) + v
    if len(captures) > 1 and totals["replay"].get("real"):
        out("All captures:")
        for which, s in totals.items():
            out(f"  {which:6s}: real chests {s['real']}, CERTAIN {s['found_certain']}, counted {s['found_approx']}, "
                f"wrongly counted {s['wrongly_counted']} of {s['labelled_not_chest']} labelled not-a-chest")
    return captures
