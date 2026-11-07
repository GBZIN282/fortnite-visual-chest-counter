# Investigation: chests missed on live streams (diagnostic captures of 2026-11-07)

First real use of the diagnostic capture. The user counted YouTube/Twitch VODs of three different streamers through OBS and
marked missed chests with Ctrl+Alt+M. Captures (read-only, user's folder `captures/`): `20261107_032230` (events, 3
clips), `20261107_033211` (whole session, 12 min), `20261107_034436` (whole session, 28 s), `20261107_034505` (events, 2
clips, marks M001-M003). All lossless (FFV1), 0 frames not recorded. No detector code was changed for this.

## Findings (confirmed)

1. **Marks and video were saved correctly.** M001 / M002 / M003 at recording 34.0 / 117.5 / 137.0 s, each inside a kept clip
   (30 s before, 10 s after); timelines complete; replay of the captures reproduces every live decision (3/3).
2. **Every marked miss is a real, readable "CHEST" pop-up**, in the expected place, and its colour passes the lavender filter:
   | Pop-up | Mark | What | exact score (needs 0.75) | blurred score, picture x0.8 |
   |---|---|---|---|---|
   | 30.5 s | M001 34.0 s | "+600 XP / CHEST" | 0.26 | 0.85 |
   | 115.3 s | M002 117.5 s | "+600 XP / CHEST" | 0.28 | 0.82 |
   | 132.9 s | M003 137.0 s | "+477 XP / WEAKPOINT STREAK / CHEST" (extra line: CHEST lower) | 0.24 | 0.82 |
3. **Cause: this streamer's HUD is drawn ~1.2x larger.** The word CHEST is 32-34 x 8-10 px in their 1280x720 frames against
   27 x 7 px for the template (reference clip: 28 px wide, same position x~893-898, y~229-230). The "+75 CONTAINER OPENED"
   tag is larger too and sits ~25 px higher (y~340 instead of ~384), outside the sprite clue's box. The picture is not cropped
   (minimap and hotbar complete with margins), so it is the game's HUD size (most likely a HUD Scale setting), not the capture.
4. **Size alone does not explain it.** Rescaled to the reference size, the exact (binary) match stays ~0.47: this stream's
   glyphs (outline, stroke width, compression) differ pixel by pixel. The detector's existing compression-tolerant (blurred,
   sigma 0.6) match scores 0.79-0.85 at x0.80-0.85 - but today it only runs AFTER an exact match >= 0.75 has opened a
   candidate, so on this footage it never runs.
5. **The failure stage is candidate generation** (popup onset), not template wording, classification or finalisation. The
   prompt clue also stayed below its threshold (max 0.58), so no fallback evidence fired either.
6. **Capturing did not change the footage**: lossless recording, every frame recorded, replay identical to live.
7. **A miss also happened at normal HUD size**: in `032230` (purple storm overlay) a "+600 XP / CHEST" at 53.5 s scored exact
   0.62 / blurred 0.83 and was not counted (live counted 3 of 4 chests). A non-chest lavender pop-up in the same clip
   ("+1,200 XP / CROWN BONUS / NEW STORM PHASE") scored blurred 0.21.

## Experiment: blurred trigger at several scales (diagnostic only)

`scratchpad/scale_experiment2.py` (not shipped): per frame, popup box resized by s in {1.25, 1.2, 1.1, 1.0, 0.9, 0.85, 0.8,
0.75}, lavender mask, exact and blurred correlation with the unchanged en:CHEST template; onset when the best blurred score
reaches 0.80 (re-arm below 0.55 for 0.3 s, >= 1 s apart). Every onset was checked by eye from a crop.

| Footage | Live detector | Blurred >= 0.80, best of the scales | Checked by eye / labels |
|---|---|---|---|
| `034505` (1.2x HUD, 3 marks) | 0 decisions | 3 onsets, all best at x0.8 | 3/3 = the marked chests, 0 false |
| `033211` "Denie", 12 min (1.2x HUD) | 0 decisions | 4 onsets, all at x0.8 | 4/4 real: CHEST, CHEST, "SPRITE LEVEL / CHEST", "RARE CHEST"; completeness unknown (no labels) |
| `032230` (normal HUD, purple storm) | 3 counted | 4 onsets, all at x1.0 | 4/4 real (one missed live: exact 0.62) |
| English reference clip (6 verified chests) | 6/6 | 5 onsets, all at x1.0 | 5/5 real, 0 false |
| ... at 6 Mbps / 2.5 Mbps (1080p x264) | 6/6, 6/6 | 5 / 5 onsets, all at x1.0 | 5/5 real each, 0 false |
| PS5 Portuguese clip (17 min, combat text) | (BAU template) | 1 onset, best at **x1.25** | **false alarm**: a stacked Portuguese XP pop-up ("BARRIL DE GLUP X2 / SEQUENCIA DE PONTOS FRACOS / BARRIL DE GLUP / ESCUDO CHEIO"), blurred 0.814 at x1.25, 0.59 at x1.0 |

Every real chest won at x1.0 or x0.8; no scale other than 1.0 ever won on normal-size footage; the only false alarm of the
brute-force search came from an ENLARGING scale (x1.25) on Portuguese footage. A production version must therefore not
search all scales blindly: shrinking scales only (HUD drawn larger) unless a smaller HUD is ever observed, and the
reliable English word only. The chest at 72.2 s in the reference clip follows another one 2 s earlier without the pop-up disappearing in
between; the real detector re-fires on such a "position jump", which this simplified experiment does not model.

Cost of the diagnostic version (all 8 scales, exact + blurred, on a loaded machine): ~39 ms/frame, against ~2-3 ms for the
single exact match. Too heavy as is for a 15 fps live loop (67 ms budget shared with everything else).

## Proposal (not implemented - needs approval and the regression gate)

1. **HUD scale estimate per session**: track which scale gives the best blurred CHEST score on strong pop-ups (and later
   other HUD anchors); after a couple of confident pop-ups, search only that scale +-1 step. Before that, search the full
   small set at a lower rate (e.g. every 3rd frame) - so steady-state cost is ~2-3 extra correlations per frame.
2. **Blurred score as a second onset trigger** (the "blurred second trigger" that the accuracy pass found promising),
   at the estimated scale, with its own threshold set from labelled data (here: real chests 0.81-0.88, non-chest 0.21).
   Exact-match events keep today's tiers; blurred-only events start at a conservative tier (APPROX first, CERTAIN only with
   support such as the prompt/object clue) until labelled captures show their precision.
3. **Scale the other clue boxes** (sprite tag, prompt) with the same estimate.
4. Gate: `research/regress.py compare --clips en ps5 en_tw6000 en_tw2500 ps5_tw6000 ps5_tw2500` event-identical except
   approved additions, plus the labelled captures from this session (and more streamers) via `review`; live cost measured
   at 15 fps with 0 dropped frames.
