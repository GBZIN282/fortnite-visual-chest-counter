"""Summarise score_variants.py output against the verified baseline events: real peaks, false peaks, background floor."""
import json, sys
import numpy as np
from fortnite_chest_counter import counter as C

def load(clip, tag):
    Z = np.load(f"analysis_output/traces/v_{tag}.npz"); return Z["t"], Z["s"], list(Z["names"])

def summary(clip, name, tag):
    t, s, names = load(clip, tag)
    ev = [e for e in json.load(open(f"tests/baselines/{clip}_v0.1.0.json")) if e["popup_template"]]
    tid = {"en:CHEST": 0, "pt:BAÚ": 1}
    items = C.known_items(name)
    def cls(on):
        m = [q for q in items if q[0] - q[1] <= on <= q[0] + q[2]]
        q = min(m, key=lambda q: abs(q[0] - on)) if m else None
        return "REAL" if q and q[3] == "chest" else "FALSE" if q else "unk"
    near = np.zeros(len(t), bool)
    for e in ev: near |= (t >= e["time"] - 3) & (t <= e["time"] + 3)
    for q in items: near |= (t >= q[0] - 4) & (t <= q[0] + 5)
    print(f"\n[{clip} {tag}]")
    print("variant   REAL peaks (sorted)                                | FALSE peaks                       | floor(max away)")
    for vi, vn in enumerate(names):
        real, false = [], []
        for e in ev:
            k = tid[e["popup_template"]]; m = (t >= e["time"] - 0.3) & (t <= e["time"] + 1.0)
            pk = float(s[m, vi, k].max()) if m.any() else 0.0
            (real if cls(e["time"]) == "REAL" else false).append(round(pk, 2))
        floor = float(s[~near][:, vi, :].max()) if (~near).any() else 0.0
        print(f"{vn:8} {sorted(real)} | {sorted(false)} | {floor:.2f}")

for clip, name, tags in (("en", "Fortnites-NEW", ["enc", "en6", "en"]), ("ps5", "Fortnite-PS5-Pro", ["ps5c", "ps56", "ps52"])):
    for tag in tags:
        try: summary(clip, name, tag)
        except FileNotFoundError: print("missing", tag)
