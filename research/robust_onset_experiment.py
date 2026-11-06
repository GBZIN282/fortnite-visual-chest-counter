"""Offline: would a second popup trigger on the blurred score (when the exact score stays < 0.75) recover chests without
adding non-chest events? Uses v_<tag>.npz from score_variants.py and the verified labels."""
import json, numpy as np
from fortnite_chest_counter import counter as C

def episodes(t, ok):
    out, cur = [], []
    for i in np.where(ok)[0]:
        if cur and t[i] - t[cur[-1]] > 0.2: out.append(cur); cur = []
        cur.append(i)
    if cur: out.append(cur)
    return out

for clip, name, tags in (("en", "Fortnites-NEW", ["enc", "en6", "en"]), ("ps5", "Fortnite-PS5-Pro", ["ps5c", "ps56", "ps52"])):
    items = C.known_items(name)
    real = [q for q in items if q[3] == "chest"]
    for tag in tags:
        Z = np.load(f"analysis_output/traces/v_{tag}.npz"); t = Z["t"]; s = Z["s"]; names = list(Z["names"])
        base = s[:, 0, :].max(1); rob = s[:, names.index("blur06"), :]
        # what the shipped trigger already finds: any frame >= 0.75 within the chest window
        found = {q for q in real if (base[(t >= q[0] - q[1]) & (t <= q[0] + q[2])] >= 0.75).any()}
        line = []
        for T in (0.90, 0.92, 0.94):
            for nmin in (2, 3):
                for gate in (0.55,):
                    ok = (rob.max(1) >= T) & (base >= gate) & (base < 0.75)
                    eps = [e for e in episodes(t, ok) if len(e) >= nmin]
                    rec, fp = set(), 0
                    for e in eps:
                        te = t[e[0]]
                        hit = [q for q in items if q[0] - q[1] - 1 <= te <= q[0] + q[2] + 1]
                        if any(q[3] == "chest" for q in hit):
                            rec |= {q for q in hit if q[3] == "chest" and q not in found}
                        elif not hit:
                            fp += 1                    # unknown episode: treat as a potential false positive
                        else:
                            fp += 1                    # verified false / non-chest
                    line.append(f"T{T:.2f}/n{nmin}: +{len(rec)} real, {fp} other")
        print(f"{tag:5} shipped trigger finds {len(found)}/{len(real)} real chests | " + " | ".join(line))
