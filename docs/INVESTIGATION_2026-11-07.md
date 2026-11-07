# Investigation: chests missed on live streams (diagnostic captures of 2026-11-07)

First real use of the diagnostic capture. The user counted YouTube/Twitch VODs of three different streamers through OBS and
marked missed chests with Ctrl+Alt+M. Captures (read-only, user's folder `captures/`): `20261107_032230` (events, 3
clips), `20261107_033211` (whole session, 12 min), `20261107_034436` (whole session, 28 s), `20261107_034505` (events, 2
clips, marks M001-M003). All lossless (FFV1), 0 frames not recorded. No detector code was changed during the
investigation; its result was integrated afterwards (see Integration into the detector).

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

## Adaptive two-stage recognition (experiment, `research/adaptive_popup.py`)

Goal: recover these pop-ups inside the real pipeline without a user-facing "algorithm" choice, keeping production's
accuracy and its 15 fps budget (66.7 ms per analysed frame). The experiment script itself is not used by the app; the
shipped version is in the detector (see Integration into the detector).

Design (each decision taken from a measurement above):

* **Production path untouched.** The exact word match, its onsets (incl. the position-jump re-fire for back-to-back chests),
  tiers, merging and counting rules run exactly as shipped; the new channel only ADDS pop-ups the exact path never claims.
* **Stage 1 - prefilter:** lavender pixels in the pop-up box >= 60 (production computes this mask every frame anyway).
* **Stage 2 - only after stage 1:** blurred match (production's sigma-0.6 NCC) of the reliable word (en:CHEST; never the short
  BAU word) at shrinking scales x1.0, 0.9, 0.85, 0.8, 0.75 - no enlarging scales (their only hit was the PT false alarm).
  After two strong (>= 0.84) pop-ups agree on a scale, only that scale and its neighbours are searched.
* **Ownership:** a blurred onset (>= 0.80) waits 2 s; if the exact path fires for the same pop-up, the exact path owns it.
* **Counting:** an unclaimed blurred pop-up is finished like any pop-up (prompt/object merge, shooting, sprite) and counts
  **APPROX only, never CERTAIN**, so CERTAIN keeps its meaning.
* **No position-jump re-fire in the blurred channel:** v1 had it and counted one stacked pop-up ("+200 / +691 / +800 XP,
  WEAKPOINT STREAK / CHEST", 034505 at 132.9 s) twice - the blurred best position jitters between scales and stacked lines.
  It re-arms only after the pop-up is gone. Cost: a second chest opened while the first pop-up is still on screen can be
  missed on large-HUD streams (recall, never a double count).
* **Fast stage 2 (exactly equivalent):** per scale, resize the box, mask, crop the SCALED mask to its ink plus a
  template-sized margin, production's NCC with window sums from integral images instead of two FFTs. Same score as
  production to 3.7e-14 on 124 frames x 5 scales; ~3x faster than the full-box computation (crop BEFORE resizing was
  faster still but changed scores by up to 0.036 - rejected).
* **Audit:** every frame is also scored by brute force (all scales, no prefilter) outside the timed path, to count
  qualifying frames the prefilter would have thrown away.

### Results (v2, every decision through the full pipeline; one counted event allowed per real chest)

| Footage | Production: real chests counted | Adaptive: real chests counted | Changes vs production | Prefilter recall |
|---|---|---|---|---|
| English reference (6 verified) | 6/6, all CERTAIN, 0 wrong | 6/6, all CERTAIN, 0 wrong | **none** | 116/116 frames |
| ... 6 Mbps / 2.5 Mbps | 6/6 / 6/6, 0 wrong | identical | **none** | 117/117, 118/118 |
| PS5 Portuguese (16 verified) | 14 counted, 11 CERTAIN, 0 wrong | identical | **none** | (0 qualifying frames) |
| ... 6 Mbps / 2.5 Mbps | 12 / 10 counted, 0 wrong | identical | **none** | (0 qualifying frames) |
| `032230` normal HUD, purple storm (4 verified) | 3/4, all CERTAIN | **4/4** (+1 APPROX) | +53.5 s MEDIUM, blurred 0.834 at x1.0 | 94/94 |
| `034505` 1.2x HUD, marked (3 verified) | 0/3 | **3/3** (APPROX) | +30.5, +115.3, +132.9 s at x0.8 | 34/34 |
| `033211` "Denie" 1.2x HUD, 12 min (4 verified) | 0/4 | **4/4** (APPROX) | +188.7, +507.8, +619.0, +689.7 s at x0.8; scale locked at x0.8 | 83/83 |

* Popup-onset recall vs counted decisions: on the reference clips every adaptive decision equals production's (the exact
  path owns every pop-up there). On the real sessions every recovered pop-up became exactly one APPROX decision; 0
  duplicates, 0 wrong counts. CERTAIN is unchanged everywhere (by design).
* The PT stacked pop-up that the brute-force search (enlarging scale x1.25) mistook for CHEST no longer triggers: on the
  three PS5 versions the blurred English match never reached the trigger at the shrinking scales.
* The prefilter (>= 60 lavender px) rejected none of the 562 frames where the brute-force search reached the trigger, while
  skipping stage 2 on 57-72% of frames.
* v1 (with the position-jump re-fire) had counted the stacked "WEAKPOINT STREAK / CHEST" pop-up in `034505` twice; v2 does
  not. Recall cost of that choice on this data: none observed.

### Cost (measured alone on the development PC; 15 fps budget = 66.7 ms per analysed frame)

Experiment (Pillow resize), per-frame `process_frame` time, production and adaptive in separate passes:

| Source | Production mean / p99 / max | Adaptive v2 mean / p99 / max | Adaptive frames > 50 ms / > 66.7 ms |
|---|---|---|---|
| English reference, 7,630 frames | 4.8 / 31.6 / 45.9 ms | 7.8 / 40.2 / 63.3 ms | 25 / **0** |
| `034505`, 1,812 frames | 4.0 / 22.3 / 25.3 ms | 7.1 / 33.5 / 48.0 ms | 0 / **0** |

As shipped (`estimator.SCALE_AWARE_POPUPS`, numpy resize - see Integration), same method, channel off vs on:

| Source | Search ran on | Off: mean / p99 / max | On: mean / p99 / max | On: frames > 50 ms / > 66.7 ms |
|---|---|---|---|---|
| English reference, 7,630 frames | 3,267 frames (43%) | 4.5 / 30.2 / 38.8 ms | 10.2 / 45.3 / 68.5 ms | 38 / **2** |
| `034505`, 1,812 frames | 747 (41%) | 5.5 / 30.3 / 34.0 ms | 12.5 / 50.4 / 62.2 ms | 20 / **0** |
| `033211`, 10,845 frames | 4,497 (41%) | 6.0 / 30.6 / 39.2 ms | 10.7 / 50.6 / 82.1 ms | 117 / **4** |

Run-to-run noise on the development PC is larger than the resize difference: a profiling run of `034505` minutes later
measured 7.8 ms mean with the channel on, of which the resize was 1.4 ms per frame (Pillow: ~0.5), the blurred NCC 2.0,
the whole channel 3.6, the production prompt check 2.4 (every 8th frame, ~19 ms each). Over-budget frames are 0.02-0.04%
of frames; the live source keeps only the latest frame, so an overrun can skip a frame but never builds a queue.
Real-time check: see Integration.

The brute-force diagnostic (8 scales, exact + blurred, every frame) cost ~39 ms/frame on a loaded machine; the adaptive
version adds ~2-3.5 ms on average because stage 2 runs only on prefiltered frames, at <= 5 shrinking scales (fewer once
locked), with the cropped, integral-sum computation.

### Remaining uncertainties

* Small labelled set: 11 real large-HUD pop-ups from 2 streamers, 1 normal-HUD miss, 22 verified reference chests. The
  margin between real large-HUD chests (blurred 0.82-0.92) and the trigger (0.80) is thin; more labelled streamers needed.
* `033211` has no full labels: its 4 found chests are verified, but chests the adaptive channel still missed are unknown.
* Large-HUD Portuguese streams are not helped (the short BAU word is deliberately excluded) and smaller-than-reference HUDs
  are not searched (none observed yet).
* On large-HUD streams the sprite tag ("CONTAINER OPENED") and the prompt clue are still searched at reference size, so
  recovered chests get no supporting clues and stay APPROX.
* A second chest opened while the first pop-up is still on screen can be missed on large-HUD streams (no position-jump
  re-fire in the blurred channel).


## Integration into the detector (v0.2.0, user's decision 2026-11-07)

Shipped as `estimator.SCALE_AWARE_POPUPS = True` (a constant, not a setting; `ChestEstimator(scale_aware=False)` for
comparisons). Code: `ChestEstimator._scaled_popup / _scaled_best / _promote_scaled / _vote_scale`, `visual.resize_box`
and `visual.robust_correlation_at`.

* **Same decisions as the experiment:** `research/adaptive_popup.py --integrated` + `--same-as` - every event on all 9
  sources identical to adaptive v2 (time, source, tier, CERTAIN/APPROX, blurred score, scale) with the channel on, and
  identical to the unmodified production detector with it off; same scale locks.
* **Regression gate:** `research/regress.py compare --tag v0.1.0` on en, ps5 and their 6 / 2.5 Mbps versions: "no
  regressions"; the only differences from v0.1.0 are the known v0.1.1 compression-robust promotions (real chests MEDIUM ->
  HIGH), unchanged by the channel.
* **Resize without Pillow:** Pillow is not in the release (it would add unsigned native binaries). `visual.resize_box`
  reproduces Pillow's BOX filter (same weights, 22-bit fixed point, horizontal pass then vertical): bit-identical on 7,350
  resizes of the pop-up box at scales 0.51-0.99 and unit-tested against Pillow. It is ~0.8 ms per resize against Pillow's
  ~0.3 ms; measured end to end that is ~1 ms per frame (see Cost), so the dependency was not worth adding. Pillow 13 does the
  vertical pass first on some tall images, so `resize_box` claims equality only for shapes like the pop-up box and refuses
  shrinking by more than 2x.
* **Only where validated:** the channel searches `en:CHEST` only and only while English MEDIUM pop-ups count alone
  (`medium_counts_alone_languages`, default `["en"]`); Portuguese-only settings switch it off.
* **Events:** scaled pop-ups are MEDIUM, `certain_counted = False`, `approx_counted = True`, with
  `scaled_popup = {blur, scale}` and their own reason text; the Activity panel shows "pop-up drawn larger than usual
  (approx only)", events.jsonl / labels.csv carry the blurred score.
* **Unit tests** (`tests/test_release.py`): fast blurred NCC = `robust_correlation` (score and position); `resize_box` =
  Pillow on the pop-up box; a 1.25x word is missed with the channel off and counted MEDIUM / APPROX only with it on;
  normal pop-ups incl. the back-to-back position-jump re-fire are identical with the channel on or off; a stacked pop-up
  that moves is counted once; the channel is off for Portuguese-only settings.

* **Real-time check (packaged release candidate, fresh extraction, `live --source file`, both runs at the same time):**

| Run | Counted | Detector fps | Dropped | Avg / max frame | CPU (one core) |
|---|---|---|---|---|---|
| English reference, 8.5 min | 6 CERTAIN / 6 APPROX (6 of 6 real) | 15.0 | 0 of 7,630 | 10.4 / 72.4 ms | 57% |
| `033211` 1.2x HUD, 12 min, diagnostic recording on (events) | 0 CERTAIN / 4 APPROX (4 of 4 real) | 15.0 | 0 of 10,845 | 13.8 / 85.7 ms | 63% |

  Single frames over 66.7 ms happen but never cost a frame at 15 fps (the source keeps only the latest frame). The user's
  own acceptance test on a random stream counted correctly.

## Recommendation (made before the integration; kept for the record)

**One adaptive detector, no user-facing algorithm choice.** On every reference clip the adaptive version makes exactly the
production decisions, it recovers every verified miss on the real streams (8 of 8, plus the normal-HUD miss) with no
duplicate and no wrong count, and its average cost is +2-4 ms per frame. A "Balanced / Compatibility" setting is not
justified by these numbers; the one open point is the worst single frame (see Cost), which is an engineering fix, not a
user choice.

### Implementation plan (each step gated)

1. **Worst case first** (research, no shipping): keep stage 2 off production's heaviest frames (prompt-check frames,
   holding the previous blurred score - cost measured above) or cap it per frame, until > 66.7 ms frames are as rare as in
   production today. Re-run the full validation (`research/adaptive_popup.py`, 9 sources) for that variant.
2. **Move into the detector behind a constant** (`estimator.SCALE_AWARE_POPUPS`, not a setting): visual.py gets the
   location-returning, cropped, integral-sum blurred NCC (exactly equal to robust_correlation, unit-tested against it);
   estimator gets the second channel (prefilter 60 px, shrink scales, en:CHEST only, 2 s exact ownership, no position-jump
   re-fire, APPROX only); events carry `scaled_popup` so logs, Activity and review show why they counted.
3. **Regression gate:** `research/regress.py compare --clips en ps5 en_tw6000 en_tw2500 ps5_tw6000 ps5_tw2500` must be
   event-identical; the three labelled captures must give 4/4, 3/3 and 4/4 with 0 duplicates / 0 wrong; unit tests for
   the channel (ownership, no double count on a stacked pop-up, nothing on PT footage).
4. **Live check:** the packaged app at 15 fps on a large-HUD VOD and on the reference clip as a live source: 0 dropped
   frames, Activity shows the recovered chests as APPROX.
5. **Then collect:** more labelled large-HUD captures from different streamers (marks-only recording + labels.csv) before
   considering any CERTAIN rule for scaled pop-ups or scaling the sprite/prompt clue boxes.

### Risks

| Risk | Mitigation |
|---|---|
| New false counts on footage we have not seen | APPROX only; trigger 0.80 with shrink scales and the specific English word only; zero false triggers on 3 English + 3 PS5 versions; more labelled captures before widening |
| Thin margin (real large-HUD chests 0.82-0.92 vs trigger 0.80) | gather labels; the threshold is one constant, re-checked by the gate |
| Worst-case frame time above budget (as shipped: 2 of 7,630 frames on the reference, 4 of 10,845 on `033211`, worst 82 ms; the experiment with Pillow: 0) | accepted by the user; overrun only skips a frame (latest-frame source), never queues; real-time runs below |
| Behaviour change for existing users | none on normal-HUD footage (event-identical); CERTAIN unchanged everywhere |
| Back-to-back chests on large-HUD streams | under-count (APPROX), never double count; revisit with labelled data |

## Earlier proposal (superseded by the measurements above)


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
