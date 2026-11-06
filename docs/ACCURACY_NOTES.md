# Accuracy pass before v0.1.0 (Nov 2026)

Goal: more real chests counted and a more useful CERTAIN number, **without** lowering any threshold and without new false
positives. Rule: the v0.1.0 detector is the baseline; a change is kept only if it wins against it, event by event.

## Evidence used

| Data | What it is | Labels |
|---|---|---|
| `en` | English PC recording, 8.5 min | 6 verified chests |
| `ps5` | Portuguese PS5 recording, 17 min | 16 verified chests, 8 verified non-chest events |
| `*_tw6000`, `*_tw2500` | the same two recordings upscaled to 1080p and re-encoded with x264 at 6 Mbps / 2.5 Mbps (`research/make_variants.sh`): a stand-in for Twitch compression | same labels (same timeline) |
| live session 2026-11-05 | 20 min OBS Virtual Camera, English (`analysis_output/live_sessions/`, local only) | **none** - event logs only, no frames |

| live Twitch sessions 2026-11-06 (00:33, 01:26) | packaged v0.1.0 on a 1080p Twitch stream via OBS Virtual Camera (copied to `analysis_output/live_sessions/`) | user observation: the shooting-demoted 10:48.26 and 10:57.26 popups were real chests |

The live logs have no frames, so they were used to *describe* the problem, not to tune anything: 49/50, 44/50 and 167/190
popups were English MEDIUM (median exact score 0.774 in every session, max 0.85), CERTAIN 1-17. Across the two Twitch sessions
9 English MEDIUM popups (0.75-0.83) were demoted to LOW by "shooting" and lost, including the two the user identified as real.
Rule A (below) counts those 9 as APPROX. Rule B's effect on these sessions cannot be computed from logs; with
`save_snapshots = true` the next sessions will show it.

Harness: `python research/regress.py compare --tag v0.1.0 --clips en ps5 en_tw6000 en_tw2500 ps5_tw6000 ps5_tw2500`
diffs every event against the frozen v0.1.0 snapshots in `tests/baselines/` and fails on any regression.
`--set NAME=VALUE` toggles estimator constants, so the v0.1.0 behaviour can always be reproduced exactly
(`--set SHOOTING_DEMOTES_RELIABLE_WORDS=True --set ROBUST_PROMOTION=False` -> identical decisions on both clips, verified).

## Key finding: compression, not missing chests, is why CERTAIN stays low

On the 2.5 Mbps encodes the exact binary glyph match of real chests falls from 0.78-1.00 to 0.77-0.88 (English) and from
0.77-1.00 to 0.68-0.88 (Portuguese). v0.1.0 then sees the chest but rates it MEDIUM (English) or misses it (Portuguese):
PS5 CERTAIN 10 -> 5 and APPROX 15 -> 12 at 2.5 Mbps. That matches the live symptom (many 0.75-0.83 MEDIUM popups,
almost no CERTAIN).

## Experiments

| # | Idea | Result | Decision |
|---|---|---|---|
| 1 | **Temporal consensus** (frames >= 0.75, span, position stability, top-5 mean) | Real English popups persist 7-14 frames, but so do verified-false Portuguese popups (11 frames >= 0.75 at 09:14 and 10:56); the two missed real Portuguese chests had only 1. Persistence does not separate true from false in the data. | **Rejected** as a rule; kept as logged diagnostics (`popup_trace`) |
| 2 | **Scale tolerance** (template x0.88-1.12) | Frames are normalised to 1280x720, so HUD scale does not change with stream resolution. Every off-scale template scored lower on real chests (e.g. 0.785 -> 0.47 at x0.94), no gain anywhere. | **Rejected** |
| 3 | **Template bank** (compressed-looking variants) | Could only be cut from our own synthetic encodes of the same chest instances (in-sample, not a valid test). Superseded by 5, which models compression smear generically. | **Not adopted** |
| 4 | **Graded colour mask** instead of the hard lavender threshold | Raised real scores a little, raised false Portuguese scores about as much. No separation gain. | **Rejected** |
| 5 | **Blurred glyph match** (mask and template Gaussian sigma 0.6 px, general NCC) | English template: real chests >= 0.92 in **every** condition; nothing that was not a chest > 0.78 (incl. 17 min of Portuguese combat popups). Portuguese: real >= 0.91 under compression, verified-false MEDIUM <= 0.83. sigma 0.4/0.8 and the graded mask were worse. Used only as **extra positive evidence**: MEDIUM -> HIGH when >= 0.88. | **Accepted** (`ROBUST_PROMOTION`) |
| 6 | **Shooting audit** | "Shooting" = >= 2 changes of the 56x28 px ammo-counter box in [-1.0, +0.5] s. It fires at 3-8 % of random moments (English) and 20 % (PS5 combat clip); compression does not increase that. On PS5 all 3 shooting demotions removed verified-false popups (short 14 px BAU word, which combat-time lavender text matches at 0.77-0.82). The 27 px CHEST template never exceeded 0.37 on those combat popups and 0.65 on any non-chest frame. | **Accepted**: shooting no longer demotes popups of a word marked reliable (`SHOOTING_DEMOTES_RELIABLE_WORDS = False`); still demotes Portuguese |
| 7 | **Second trigger on the blurred score** (recover popups whose exact score stays < 0.75) | Recovers 2-4 Portuguese chests at 2.5 Mbps with 0 false triggers, nothing elsewhere; margin thin (0.90 vs a 0.86 background ceiling); needs new tiering rules. | **Rejected for v0.1.0**, promising for low-bitrate Portuguese |
| 8 | Audio | Not used live; no new evidence it adds independent signal. | **Left out** |

## Regression: v0.1.0 -> accepted detector

Every changed decision below is a verified real chest moving MEDIUM -> HIGH. No event was added or lost, APPROX is unchanged,
no verified-false event changed.

| Clip | CERTAIN | APPROX | Events |
|---|---|---|---|
| en | 3 -> **6** (6/6 real) | 6 -> 6 | 6 -> 6 |
| en_tw6000 | 4 -> **6** | 6 -> 6 | 6 -> 6 |
| en_tw2500 | 3 -> **6** | 6 -> 6 | 6 -> 6 |
| ps5 | 10 -> **11** | 15 -> 15 | 24 -> 24 |
| ps5_tw6000 | 11 -> **12** | 14 -> 14 | 16 -> 16 |
| ps5_tw2500 | 5 -> **6** | 12 -> 12 | 14 -> 14 |

Margins at the 0.88 promotion level: verified-false MEDIUM popups <= 0.83; real promoted chests 0.90-0.96.
The one remaining real Portuguese miss (01:32, blurred 0.81) stays MEDIUM, uncounted, exactly as in v0.1.0.

Experiment 6 changes nothing on these clips (no English popup coincides with shooting there). Its support is the
template-specificity measurement above plus live reports of English chests opened mid-fight being demoted.

## Cost

Blurred match is computed only while a popup is being evaluated (~15 frames per popup) and only within +-8 px of the exact
match: ~0.2 ms per template. Live OBS Virtual Camera: 15 fps, 0 dropped frames.

## What would move accuracy further

Labeled live footage. Turn on `[logging] save_snapshots = true`: every considered popup is saved as a small PNG with its
event id, tier and decision, plus `robust_score` and `popup_trace` in the session log. A few labeled Twitch sessions would
allow validating experiment 7 and a calibrated English CERTAIN rule on real streams instead of synthetic encodes.
