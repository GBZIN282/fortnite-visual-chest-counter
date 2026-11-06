"""Offline experiment: does a narrow scale tolerance raise REAL popup scores more than it raises non-chest scores?
Uses the masks stored by popup_traces.py. Research only."""
import sys, json, glob
import numpy as np
from scipy.ndimage import zoom
from fortnite_chest_counter.detection import visual as V
from fortnite_chest_counter import counter as C

name, trace, logdir = sys.argv[1:4]
scales = [0.88, 0.94, 1.0, 1.06, 1.12]
Z = np.load(trace)
t, sc = Z["t"], Z["scores"]; shape = tuple(Z["mask_shape"]); tpl_ids = list(Z["templates"])
kept = Z["kept_idx"]; masks = Z["kept_masks"]
tpls = {i: np.load(f"src/fortnite_chest_counter/templates/{p}") for i, p in zip(tpl_ids, ["chest/en/chest.npy", "chest/pt/bau.npy"])}
def variants(a):
    out = {}
    for s in scales:
        z = a if s == 1.0 else np.clip(zoom(a.astype(np.float32), s, order=1), 0, 1)
        out[s] = z.astype(np.float32)
    return out
bank = {i: variants(a) for i, a in tpls.items()}
log = [json.loads(l) for l in open(glob.glob(logdir + "/logs/*.jsonl")[0], encoding="utf-8") if l.strip()]
events = [e for e in log if e.get("popup_template")]
items = C.known_items(name)
def cls(on):
    m = [q for q in items if q[0] - q[1] <= on <= q[0] + q[2]]
    q = min(m, key=lambda q: abs(q[0] - on)) if m else None
    return {"chest": "REAL", "false": "FALSE", "non-chest": "NONCH"}[q[3]] if q else "unk"
pos = {int(i): n for n, i in enumerate(kept)}
def mask_of(i):
    return np.unpackbits(masks[pos[i]])[:shape[0] * shape[1]].reshape(shape).astype(np.float32)
def score_all(i, tid):
    m = mask_of(i)
    return {s: V.best_template_correlation(m, bank[tid][s])[0] for s in scales}
print("event scores by template scale (max over onset-0.3..onset+1.0)")
print("class  stamp    tid      " + "  ".join(f"{s:5.2f}" for s in scales))
event_frames = set()
for e in events:
    on, tid = e["time"], e["popup_template"]
    idx = [i for i in range(len(t)) if on - 0.3 <= t[i] <= on + 1.0 and i in pos]
    event_frames.update(range(int(np.searchsorted(t, on - 3)), int(np.searchsorted(t, on + 3))))
    if not idx: continue
    best = {s: 0.0 for s in scales}
    for i in idx:
        for s, v in score_all(i, tid).items():
            best[s] = max(best[s], v)
    print(f"{cls(on):5} {e['stamp']:>8} {tid:8} " + "  ".join(f"{best[s]:5.3f}" for s in scales))
# non-event frames: how many would cross 0.75 under each scale?
neg = [int(i) for i in kept if int(i) not in event_frames]
print(f"\nnon-event frames with unscaled score >= 0.40: {len(neg)}")
cnt = {(tid, s): 0 for tid in tpls for s in scales}; mx = {(tid, s): 0.0 for tid in tpls for s in scales}
for n, i in enumerate(neg[:1500]):
    m = mask_of(i)
    for tid in tpls:
        for s in scales:
            v = V.best_template_correlation(m, bank[tid][s])[0]
            cnt[(tid, s)] += v >= 0.75; mx[(tid, s)] = max(mx[(tid, s)], v)
for tid in tpls:
    print(tid, "frames>=0.75:", {s: cnt[(tid, s)] for s in scales}, " max:", {s: round(mx[(tid, s)], 3) for s in scales})
