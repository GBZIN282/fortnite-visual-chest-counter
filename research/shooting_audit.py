"""Research: how often does the ammo-step 'shooting' cue fire, and are the steps persistent (a real ammo change) or flicker?"""
import json, numpy as np
from fortnite_chest_counter.detection import evidence as E

print("AMMO_BOX", E.AMMO_BOX, "step>=", E.AMMO_STEP_MIN_PIXELS, "stable<=", E.AMMO_STABLE_MAX_PIXELS, "needs steps:", E.SHOOTING_MIN_STEPS)
for clip in ("en", "ps5"):
    Z = np.load(f"analysis_output/traces/{clip}.npz"); t = Z["t"]; d = Z["ammo_diff"]
    steps = [i for i in range(1, len(d)) if d[i] >= E.AMMO_STEP_MIN_PIXELS and d[i - 1] <= E.AMMO_STABLE_MAX_PIXELS]
    pers = {i for i in steps if i + 1 < len(d) and d[i + 1] <= E.AMMO_STABLE_MAX_PIXELS}
    print(f"{clip}: frames {len(d)}  steps {len(steps)}  persistent {len(pers)}  frames diff>=15: {int((d >= 15).sum())}")
    for e in json.load(open(f"tests/baselines/{clip}_v0.1.0.json")):
        on = e["time"]; w = [i for i in steps if on - 1.0 <= t[i] <= on + 0.5]
        if w:
            print(f"   {on:7.2f} steps {len(w)} persistent {sum(i in pers for i in w)} shoot={e['shooting_negative']} {e['adjusted_tier']} diffs {[int(d[i]) for i in w]}")
