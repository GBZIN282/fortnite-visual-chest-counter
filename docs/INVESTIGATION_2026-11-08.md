# Investigation: chests missed on Thiefs' stream (smaller HUD), 2026-11-08

v0.2.2 task 1. Forensic look at the user's v0.2.1 diagnostic captures before any detector change (sections 1-9, no
detector code changed). Part 2 (section 10 onward) covers the user's later recordings and the detector changes made from
all of this evidence. Captures were only read (never modified).

## 1. Evidence located

Installation: `Downloads\Fortnite-Visual-Chest-Counter\Fortnite-Visual-Chest-Counter-v0.2.1` (`logs\`, `captures\`,
`state\`; capture dir = default `captures`).

| Time (2026-11-08) | Session log | Source | What | Counted |
|---|---|---|---|---|
| 02:27:10 | `session_20261108_022708` | Livestream URL `twitch.tv/replays` | 417 s, no recording | 12 / 13 |
| 02:39:38 | `session_20261108_023938` | manual | Reset (was 12 / 13) | - |
| 02:39:44 | `session_20261108_023942` | Livestream URL **`twitch.tv/thiefs`** | 85.7 s, **no recording** | **0 / 0** |
| 02:41:38 | `session_20261108_024138` | OBS Virtual Camera | 62 s, recording `20261108_024147` (marks mode), **marks M001-M004** | **0 / 0** |
| 03:01:21 | `session_20261108_030119` | Livestream URL `twitch.tv/replays` | 45 s, recording `20261108_030121` (no clips) | 0 / 0 |
| 03:02:11 | `session_20261108_030211` | OBS Virtual Camera | 25 min, recording `20261108_030211` (events mode, 6 clips) | 65 / 86 |

**Which footage is Thiefs':** `20261108_024147` - the squad list shows the player name "Thiefs" with teammate "Replays",
the webcam and a "1019/1100" overlay are his stream's, and it starts 2 minutes after the `twitch.tv/thiefs` URL session.
`20261108_030211` is **not** Thiefs: the webcam is the streamer of our English reference clip, the squad list shows
"Thiefs" as a teammate - it is Replays' stream (normal HUD), used below as normal-HUD regression footage. The 85.7 s
Thiefs URL session has no recording, so only its result (0 counted) is known.

## 2. Missed chests (capture `20261108_024147`, `video/clip_001.ffconcat`)

Recording time = live time - 8.81 s. Replaying the recording through the v0.2.1 detector gives 0 events - identical to
live, so the recording reproduces the failure.

| # | Recording time | Live time | Pop-up on screen | Visible? | Nearest mark |
|---|---|---|---|---|---|
| 1 | 21.33 s | 30.14 | "+900 XP / RARE CHEST" (new pop-up) | clearly | M001 at 23.27 |
| 2 | 24.93 s | 33.74 | "+900 XP / SPRITE CHEST" (new pop-up) | clearly | M002 at 26.73 |
| 3 | 26.67 s | 35.48 | same pop-up grows: "+1,800 XP / SPRITE CHEST / RARE CHEST" | clearly | M002 |
| 4 | 28.27 s | 37.08 | same pop-up: "+2,700 XP / SPRITE CHEST / RARE CHEST X2" | clearly | M003 at 29.40 |
| 5 | 30.00 s | 38.81 | same pop-up: "+3,600 XP / SPRITE CHEST / RARE CHEST X3" | clearly | M004 at 31.60 |

Five chest openings (one Sprite chest, four Rare chests); the user's four marks follow them by 1.3-2.0 s (one mark
covers #2 and #3). A new chest is visible being opened at each step. The stream's "1019/1100" overlay did not change
during these five openings, so it cannot serve as ground truth.

**Size and position (normalized 1280x720):**

| | Word CHEST | Box |
|---|---|---|
| Reference template (`en:CHEST`) | 27 x 7 px | x 885-911, y 229-235 |
| Thiefs, "RARE CHEST" line | **22 x 7 px** | x 889-910, y 228-234 |
| Thiefs, whole pop-up (3 lines) | - | x 844-916, y 210-241 |

The best-matching rescale is x1.25 (the picture enlarged by 25 %), i.e. **Thiefs' HUD is drawn at ~0.80x** of the
reference. His other HUD elements agree (hotbar slots ~40 px vs ~51 px, health bar ~153 px vs ~190 px on Replays' stream).
The pop-up is **inside** the detector's search region (x 716-1076, y 158-360) with a wide margin; the search region is
not the problem.

**Scores (en:CHEST; per frame, during pop-ups #1-#5):**

| Match | Needs | Thiefs' pop-ups | Result |
|---|---|---|---|
| Exact binary match, picture x1.0 (production onset) | >= 0.75 | 0.21-0.32 | never fires |
| Blurred match x1.0 (shipped scale-aware channel searches x1.0-0.75 only) | >= 0.80 | 0.60-0.65 | never fires |
| Blurred match, picture enlarged x1.25 (not searched today) | >= 0.80 | 0.80-0.86 | would fire |
| Exact match, picture enlarged x1.25 | >= 0.75 | 0.48-0.59 | still too low |

**Rejection reason:** candidate generation. No pop-up is ever opened: the exact match is far below 0.75, and the v0.2.0
scale-aware channel only shrinks the picture (larger HUD) - smaller HUDs were never searched because no smaller HUD had
been observed and the only enlarging-scale hit of the 2026-11-07 brute-force search was a false alarm. The prompt clue
gave nothing either (no interaction events), and the "+75 CONTAINER OPENED" sprite tag area is covered by the streamer's
webcam/goal overlay on this stream.

## 3. Would scale alone recover them?

Two candidate-generation variants, simulated with the production onset rules (fire / re-arm below for 0.3 s / 1 s apart;
the existing exact path owns anything it fires on within 2 s):

| Variant | Thiefs (5 real) | Notes |
|---|---|---|
| Blurred `en:CHEST` at enlarging scales x1.2 / 1.25 / 1.3, trigger 0.80 | **2** (#1 at 21.40 s 0.81, #2 at 24.93 s 0.83) | margins 0.01-0.03 at the onset |
| Native small-HUD template (`CHEST` cut from #1 at 22.0 s, 22 x 7 px), exact >= 0.75 | **2** (#1 0.86, #2 0.82) | on the pop-ups it was NOT cut from: exact 0.83-0.90, blurred 0.91-0.98 |

Neither variant recovers #3-#5: **they are not new pop-ups**. Fortnite keeps one pop-up on screen and adds a line ("RARE
CHEST") or a multiplier ("X2", "X3"). The score never drops (no re-arm), the matched word moves only ~6 px (below the
8 px position-jump rule of the exact path; the scale-aware channel has no position re-fire by design), and on the stacked
lines the small template's exact score falls to 0.59-0.67. This is a separate counting problem, independent of HUD size:
**stacked chest pop-ups**. Whether the normal-HUD detector counts "X2" steps is unknown - no labelled normal-HUD "X2"
pop-up is in our footage.

## 4. False alarms on reference footage

Onsets that the existing exact path would not own (counts of false alarms; "max" = highest score on that footage):

| Footage | Enlarging scales x1.2-1.3, blurred >= 0.80 | Native small template: exact >= 0.75 / blurred >= 0.90 |
|---|---|---|
| English reference (8.5 min) | 0 (max 0.70) | 0 / 0 (max 0.46 / 0.81) |
| ... 6 Mbps | not scanned | 0 / 0 (max 0.53 / 0.79) |
| ... 2.5 Mbps | 0 (max 0.72) | 0 / 0 (max 0.46 / 0.81) |
| PS5 Portuguese (17 min) | **1 false alarm**: 72.33 s, 0.806 at x1.25 (the stacked Portuguese pop-up already flagged on 2026-11-07) | 0 / 0 (max 0.62 / 0.87) |
| ... 6 Mbps | not scanned | 0 / 0 (max 0.60 / 0.86) |
| ... 2.5 Mbps | 0 (max 0.775) | 0 / 0 (max 0.62 / 0.87) |
| Replays' stream `030211`, 6 clips, normal HUD | 0 (max 0.771) | 0 / 0 (max 0.48 / 0.83) |
| **Thiefs, real chests** (for comparison) | onsets 0.813 / 0.828 | exact 0.82-1.00, blurred 0.91-1.00 |

The native template separates far better: its highest score on anything that is not a small-HUD chest is 0.62 exact
(PS5 combat text), 0.20 below the weakest real onset; the enlarging search leaves a 0.007 gap. Normal-size CHEST words do
not match the small template either (max 0.48 exact on Replays' session), so it cannot double count normal pop-ups.
Limits: the template was cut from this same session (only cross-checked on its other pop-ups), and it is one streamer at
one HUD size.

## 5. HUD-scale assumptions in the pipeline (audit)

| Assumption | Where | Value | Small-HUD effect |
|---|---|---|---|
| Frame normalization | `video_sources`, `visual.scale_filter` | every source scaled to 1280x720 | removes resolution differences, NOT the in-game HUD Scale |
| Pop-up search region | `visual.ROI_*` | x 716-1076, y 158-360 | fine (pop-up x 844-916, y 210-241) |
| Chest-word templates | `templates/chest/en/chest.npy`, `pt/bau.npy` | 27 x 7 px / 14 px, one size | **root cause**: exact match 0.21-0.32 |
| Exact onset / re-arm | `visual.EVENT_HIGH/LOW_THRESHOLD` | 0.75 / 0.50 | never reached |
| Tiers | `fusion.TIER_*` | 0.75 / 0.80 / 0.85 / 0.90 | irrelevant until a pop-up exists |
| Compression-robust promotion | `estimator.ROBUST_*` | blurred >= 0.88 within 8 px of the exact match | runs only after an exact onset |
| Scale-aware channel | `estimator.SCALED_*` | shrink scales 1.0-0.75 only, trigger 0.80, re-arm 0.55, prefilter 60 px, lock 0.84 | never searches smaller HUDs; prefilter passes (290-1,900 px) |
| Debouncing | `visual.EVENT_*`, `estimator.SCALED_WAIT` | 1.0 s apart, 0.3 s re-arm hold, 8 px position jump (exact path only), 2 s ownership | stacked pop-ups (#3-#5) never re-fire; 8 px is ~6 px at 0.8x |
| Sprite tag | `sprite.TEMPLATE_SEARCH_BOX` | x 1020-1180, y 372-400, fixed size | HUD-scale dependent; covered by the overlay here |
| Prompt / object clue | `evidence.PROMPT_SEARCH_BOX`, disc template 36 px | fixed size | weaker at 0.8x (gave nothing here) |
| Shooting (ammo box) | `evidence.AMMO_BOX` | x 930-986, y 648-676 | moves with HUD scale; only demotes short (PT) words |

Also seen (normal HUD, not part of this fix): in Replays' session the live counter made two decisions (E0014 186.75 s and
E0015 188.21 s live) during ONE unchanged "+600 XP / CHEST" pop-up while the camera turned; both at exact 0.75. Replaying
the recording gives only the first one, so it is not reproducible from the (MJPEG) recording. Possible over-count by a
borderline re-fire - unconfirmed.

## 6. Conclusions

1. **Confirmed missed chests:** 5 in `20261108_024147` (table in section 2), all clearly visible, all inside the search
   region.
2. **Root cause:** the chest word is drawn ~0.80x the template's size (HUD drawn smaller), so the exact match (0.21-0.32)
   never opens a pop-up, and the scale-aware channel searches only larger HUDs. Secondary: 3 of the 5 chests are stacked
   steps of one pop-up ("RARE CHEST", "X2", "X3"), which no current rule counts.
3. **HUD-scale hypothesis: supported** (x1.25 best match, HUD ~0.80x, every HUD element ~0.8x). It explains 5 of 5 missed
   onsets, but fixing it alone recovers 2 of 5 here, because of stacking.
4. **Smallest reliable fix:** a native-size small-HUD CHEST template in the scale-aware channel, APPROX only (section 7).
5. **Regression tests:** section 8.
6. **Performance at 15 fps:** section 9.

## 7. Recommendation

**Do not ship a blind enlarging-scale search.** Its only false alarm on our references (PS5, 72.3 s, 0.806 at x1.25)
sits 0.007-0.02 below Thiefs' real onsets (0.813 / 0.828), and enlarging the picture costs ~34 ms per frame with
scipy (section 9).

**Smallest reliable fix for v0.2.2 (proposed; needs approval and more footage first):** a second, native-size
"small HUD" CHEST template inside the existing scale-aware channel - same contract as the v0.2.0 large-HUD channel:

* template cut at native size from real small-HUD footage (today: Thiefs, 22 x 7 px); no picture resizing;
* candidate when the exact small-template match >= 0.75 AND its blurred match >= 0.90 (both measured above on the
  pop-ups the template was not cut from: exact 0.82-0.90, blurred 0.91-0.98);
* English word only, 60 px prefilter, the exact path owns anything it fires on within 2 s, no position-jump re-fire;
* counts **APPROX only (MEDIUM), never CERTAIN**, logged with its own reason ("pop-up drawn smaller than usual").

Expected on today's evidence: Thiefs 2 of 5 (+2 APPROX), 0 new counts on the references and Replays' session
(section 4).

**Evidence still missing before implementing it:**

1. More small-HUD footage at other sizes. One streamer at one HUD size is not enough to choose templates: the user can
   produce it by setting their own Fortnite HUD Scale to a few values below normal, opening some chests with the
   diagnostic recording on (Events), and marking each one.
2. Labelled stacked pop-ups ("CHEST X2", "RARE CHEST X2/X3") at normal HUD size, to learn whether the v0.2.1 detector
   already loses multiplier steps for everyone.

**Stacked pop-ups (a second v0.2.2 item, research first):** 3 of Thiefs' 5 chests were multiplier or new-line steps inside
one pop-up. At normal size, a new CHEST line was counted by the position-jump rule (Replays' clip 2, 30.7 s: "CHEST /
SPRITE LEVEL / CHEST" -> E0022), but nothing reacts to "X2" / "X3". The candidate rule ("the pop-up's chest lines or
multiplier changed -> +1, APPROX only") needs labelled data first, because the 2026-11-07 adaptive experiment (v1) double
counted a stacked pop-up.

## 8. Regression tests needed

1. `research/regress.py compare --tag v0.1.0 --clips en ps5 en_tw6000 en_tw2500 ps5_tw6000 ps5_tw2500`: event-identical
   (no lost, changed or new counts).
2. Replays' normal-HUD capture `20261108_030211` (6 clips): replayed decisions identical with the new channel on and off.
3. Thiefs' capture `20261108_024147`: label the 5 chests; expect #1 and #2 as APPROX, 0 duplicates, 0 CERTAIN.
4. Unit tests (`tests/test_release.py`, like the v0.2.0 large-HUD ones): a synthetic small CHEST word is missed with the
   channel off and counted MEDIUM / APPROX with it on; normal pop-ups (incl. the back-to-back position-jump re-fire)
   identical on and off; channel off for Portuguese-only settings; a stacked pop-up counted at most once.
5. The 2026-11-07 large-HUD captures (`20261107_032230`, `_033211`, `_034505`; 11 verified chests) are no longer on disk.
   If the user still has them elsewhere they belong in this gate; otherwise the large-HUD channel is covered by unit tests
   only.
6. Packaged app, live at 15 fps on the reference clip and on Thiefs' recording: 0 dropped frames, Activity shows the
   recovered chests as APPROX.

## 9. Expected performance impact (15 fps, 66.7 ms per analysed frame)

Measured on Thiefs' 750 recorded frames, on a heavily loaded development PC (13 analysis processes running), so absolute
numbers are high; compare them with each other:

| Work, per frame that passes the 60 px prefilter | ms |
|---|---|
| Production exact en:CHEST match (for comparison) | 2.9 |
| Native small template, exact match | 3.0 |
| Native small template, blurred match (cropped, integral sums) | 3.8 |
| Picture enlarged x1.25 (scipy, order 1) + mask + blurred match | 34.4 |

The prefilter passed 73 % of Thiefs' frames and ~40 % on the reference clips (2026-11-07 measurements). The proposed
channel adds roughly one more template match per such frame: **about +1-3 ms per analysed frame on average**, against
live averages of 13-27 ms per frame in the user's v0.2.1 sessions (the higher ones are Livestream URL sessions). No new dropped frames are expected; per the project's
rule this must be confirmed end to end (packaged app, 15 fps, dropped-frame count), not by these micro-measurements.

---

# Part 2: the 05:40-05:50 recordings and the detector changes (v0.2.2)

## 10. New recordings (user, 2026-11-08 05:40-05:50)

| Capture | Source (from footage + metadata) | Clips | Marks | Live decisions | Finding |
|---|---|---|---|---|---|
| `20261108_054023` | OBS Virtual Camera, Replays (normal HUD) | 12.6 s | - | 1 | "+600 XP / CHEST", counted - fine |
| `20261108_054035` | OBS Virtual Camera, marks mode | none | 0 | 7 | no video kept (no mark) |
| `20261108_054155` | desktop capture of Replays' Twitch stream, fullscreen | 40 s | M001, M002 | 25 | 6 pop-ups in the clip (one SPRITE CHEST), all 6 counted. Both marks sit next to counted chests (M001 during the counted SPRITE CHEST, M002 just before a counted CHEST): labelled examples, not misses |
| `20261108_054639` / `_054649` | desktop, monitor 1 / 2, a few seconds | none | 0 | 0 | nothing recorded |
| `20261108_054841` clip 1 | desktop capture of the WHOLE Twitch page (`twitch.tv/replays`, not fullscreen) | 20 s | M001, M002 | 0 | the player fills ~half the screen: the pop-up ("RARE CHEST") is far outside the search box. **Framing problem, not the detector** (fullscreen / theatre mode or the Livestream URL input avoid it) |
| `20261108_054841` clip 2 | the same, fullscreen, normal HUD | 54 s | M003, M004, M005 | 1 | **stacked chests at NORMAL HUD**: "+900 XP / RARE CHEST" (39.33 s, counted APPROX), "RARE CHEST X2" (40.33 s, missed), "RARE CHEST X3" (42.00 s, missed); each mark 1-1.5 s after a step |

So the stacking problem of Thiefs' chests #3-#5 is not a small-HUD problem: Fortnite merges consecutive chests into the
pop-up on screen for every player. Re-reading Replays' 25-min session found the counterpart: a new CHEST line was counted
by the old "position jumped" rule (clip 2, 30.67 s), but the same rule also counted ONE chest TWICE when a non-chest line
("SPRITE LEVEL") pushed the word up (clip 3, 98.8 s - reproducible from the recording), and live E0015 is the same rule
firing on the pop-up's scale-in animation (the word moved exactly 8 px: 183 -> 191). With per-frame score noise of
0.01-0.02 (the size of live-vs-recording differences) the old rule counts that pop-up twice in 2.4-3.5 % of runs.

## 11. Case catalogue (permanent)

`tests/cases/cases.json` holds every confirmed case with truth labels (clip times, what changed, chest type);
`research/cases.py fetch` copies only the needed 10 s segments into `samples/cases/` (not in Git, 543 MB),
`research/cases.py run` replays the full frames through the detector and scores missed / duplicate / false counts,
`research/cases.py fixtures` stores the pop-up box masks (304 KB for 7 cases) in `tests/fixtures/popups/` so
`tests/test_cases.py` checks every case on any machine without footage.

| Case | Real chests | v0.2.1 (replayed) | v0.2.2 |
|---|---|---|---|
| `thiefs_small_hud` (HUD 0.8x) | 5 | 0 found | 5 found (all APPROX) |
| `replays_stack_x2_x3` | 3 | 1 found | 3 found |
| `replays_new_chest_line` | 2 | 2 found | 2 found (second via a new chest line, CERTAIN as before) |
| `replays_sprite_level_line` | 1 | 1 found + **1 duplicate** | 1 found, 0 duplicates |
| `replays_e0015_duplicate` | 2 | 2 found (live: +1 duplicate, see above) | 2 found |
| `replays_six_chests` (incl. NEW STORM PHASE, WEAKPOINT STREAK lines) | 6 | 6 found | 6 found, 0 false |
| `replays_vault_five_chests` (RARE, X2, + SPRITE line, + RARE line, its X2) | 5 | 4 (the last one by a fire as the pop-up faded) | 5 found |
| `replays_chest_x2_late_exact` ("CHEST" -> "CHEST X2") | 2 | 2 (the X2 missed; a late exact fire on the first chest made up for it) | 2 found |
| `replays_weakpoint_line` (MAXIMUM AMMO, WEAKPOINT STREAK lines added) | 1 | 1 + **1 over-count** | 1 found |
| `replays_static_popup_refire` (one unchanged pop-up) | 1 | 1 + **1 duplicate** | 1 found |
| **Total** | **28** | **20 found, 8 missed, 3 over-counts** (and 2 right totals for the wrong reason) | **28 found, 0 missed, 0 over-counts** |

The last four cases came from comparing a full replay of Replays' 25-minute session with the v0.2.1 detector and the
new one, decision by decision, and checking every difference on the footage (section 13).
| `twitch_page_not_fullscreen` | (known limitation) | - | - |

## 12. What changed in the detector

1. **Small-HUD channel** (`estimator.SMALL_HUD_POPUPS`): a CHEST word cut at its native 0.8x size
   (`templates/chest/en/chest_small.npy`, 22 x 7 px, from Thiefs' first pop-up only - his four later chests are the
   out-of-sample check). Candidate when the exact match >= 0.75 AND the blurred match at that place >= 0.90. Same contract
   as the v0.2.0 large-HUD channel: English word only, 60 px prefilter, the exact path owns what it fires on, APPROX only.
   Searched in a 210 x 130 px box around the pop-up's place (the pop-up keeps its place when the HUD is smaller) and no
   longer searched once the session's HUD scale is voted normal or larger.
2. **Pop-up content tracker** (`detection/popup_lines.py`, `estimator.STACKED_POPUPS`) replaces the "position jumped"
   re-fire for the English word. While a pop-up is on screen it follows its chest lines (local maxima of the blurred
   chest-word match; non-chest lines score <= 0.70, chest lines >= 0.77) and the multiplier right of each word, and counts
   +1 for a chest line added, a multiplier appearing, or a multiplier digit changing - only when the XP total changed
   too (the XP line matches itself at 0.98-1.00 within a state and drops to 0.32-0.43 at every real addition), only after
   the whole pop-up stood still for 0.18 s (the XP number counts up after each addition; a state caught mid-animation made
   a false step during development), never within 1 s of the previous step, and never for the pop-up's first state (its
   onset counted it; "X3" seen first proves nothing about what we did not see). Lines are matched by order (an added line
   pushes the others up). A new chest line keeps the normal tier rules (it is a new CHEST word, as the re-fire was); a
   multiplier step, and every step of a scale-aware / small-HUD pop-up, counts APPROX only. The Portuguese word keeps the
   position re-fire (no stacked Portuguese footage).
3. Digit "2" vs "3" at the small HUD is ~4 px wide (similarity 0.86-0.89 against 0.94-1.00 for the same digit): the digit
   threshold (0.90) is only safe together with the XP-change requirement.

4. **One pop-up, one onset.** An exact-path onset on the pop-up the tracker already follows, after that pop-up was
   counted (by the scale-aware / small channel or an earlier exact onset), is the same pop-up, not a chest
   (`replays_chest_x2_late_exact`: v0.2.1 counted a "+600 XP / CHEST" at 14.07 s and again when the exact match first
   passed 0.75 at 16.67 s).
5. **Lines and multipliers never go away while a pop-up lives**, so a state with fewer lines or a lost multiplier is
   never adopted (the reference clip's RARE CHEST line flickers at 0.74-0.77; adopting the dip would have counted the
   line's return as a new chest).
6. A step is dated from the first frame that differed (at most 1 s before it held still), takes its exact score from
   those frames, and needs only 0.6 s after the previous step (the vault's steps were 0.93 s apart; 1.0 s lost one).
   A new-line step whose word never reached the exact 0.75 counts APPROX only.
7. **A new chest line does not have to stand still.** It arrives while the XP number counts up, and an old line can
   flicker under the line threshold at the same moment (the reference clip's 72.3 s chest: "RARE CHEST" fell to ~0.70
   right as "SPRITE CHEST" was added). Added lines go to the bottom and push the others UP (a non-chest line moved CHEST
   up 6 px), so a chest line appearing >= 0.9 word heights BELOW the known bottom line is a new line even when an old one
   is not visible; it counts when more lines show in 3 of the last 5 frames, with the XP change. Its compression-robust
   confirmation (for CERTAIN) is taken from the frames since the change began (kept as a 4 s history while a pop-up is
   followed), as v0.2.1's re-fire measured it from the re-fire on.

Rejected on evidence: enlarging the picture to find the small word (false alarm on PS5 at 0.806, ~34 ms per frame);
letting the digit reference follow the content (Thiefs' X3 drifted in unnoticed).

## 13. Replays' 25-minute session, replayed with v0.2.1 and v0.2.2

`20261108_030211`, all 6 clips (15,000 frames): v0.2.1 84 counted (63 CERTAIN), v0.2.2 82 (58 CERTAIN). Every
difference was checked on the footage:

| Clip / time | v0.2.1 | v0.2.2 | Footage |
|---|---|---|---|
| 2 / 311.2 s | CERTAIN | - | over-count: WEAKPOINT STREAK line added to "+850 XP / CHEST / MAXIMUM AMMO" |
| 3 / 77.2 s | CERTAIN | - | over-count: the same unchanged "+600 XP / CHEST" pop-up |
| 3 / 98.8 s | CERTAIN | - | over-count: SPRITE LEVEL line added |
| 3 / 111.5 s | - | APPROX (X2) | real chest, missed by v0.2.1 |
| 3 / 116.1 s (v0.2.1: 118.1 s) | CERTAIN (fire as the pop-up faded) | APPROX (X2 on the third line) | the same real chest; v0.2.2 for the right reason |
| 2 / 16.7 s | CERTAIN (late exact fire on the counted pop-up) | APPROX (X2, 15.9 s) | the same real chest; v0.2.2 for the right reason |

Net: 3 over-counts removed, 1 missed chest recovered; all 5 CERTAINs that v0.2.2 does not give were over-counts or right
for the wrong reason. `20261108_054155`: identical (6 -> 6, all CERTAIN).

Processing cost, measured old and new on the same decoded frames one after the other (no other load):

| Capture | v0.2.1 mean / p99 | v0.2.2 mean / p99 | frames > 66.7 ms |
|---|---|---|---|
| `054155` (normal HUD, 600 frames) | 14.8 / 58 ms | 16.2 / 62 ms | 0-1 -> 0 |
| `030211` clip 3 (normal HUD, vault, 1,950 frames) | 10.6 / 46 ms | 11.2 / 49 ms | 0 -> 1-2 |
| `024147` Thiefs (small HUD, 750 frames) | 12.0 / 36 ms | 9.1 / 36 ms | 0 -> 0 |

About +1 ms per frame at normal HUD (the small-word search until the HUD scale is voted, and the tracker while a pop-up is
on screen); faster on the small-HUD stream, because the large-HUD search stops once its scale is known. The live check of
the packaged app (sustained 15 fps, dropped frames) is still to be done.

## 14. Chest types (v0.2.2 statistics)

`detection/chest_types.py`: every counted chest is labelled with the type of its own pop-up line - the word left of
CHEST: nothing = a normal chest; RARE or SPRITE decided by the word's LENGTH relative to CHEST (RARE 0.77-0.89, SPRITE
1.04-1.18, nothing 0.00-0.04 on the labelled lines) and confirmed by the EXACT match of that word (>= 0.50 and >= 0.15
above the other word; real words 0.67-0.94 median, random ink of the same length <= 0.41 - a blurred match was rejected
because random ink reached 0.65 against it). Anything else is "unknown"; an uncertain line is never called normal. A
chest's type is the majority (>= 60 %, >= 3 readings) of its line's readings while the pop-up is on screen; a label that
becomes clearer after the chest was counted is sent as a type update and moves the chest between types - the totals never
change. Word templates: RARE (normal size) from the English reference clip, SPRITE (normal) from Replays' 054155 at 14 s,
both small-size words from Thiefs' first two pop-ups.

| Footage | Chests | Correct type | Unknown | Wrong |
|---|---|---|---|---|
| 11 cases (28 chests; 14 normal, 11 rare, 3 sprite) | 28 | 28 | 0 | 0 |
| English reference, clean | 6 | 5 | 1 (the SPRITE line at 72.3 s, its RARE line flickering) | 0 |
| English reference, 6 / 2.5 Mbps | 6 / 6 | 6 / 6 | 0 | 0 |

Partly in-sample: the SPRITE (normal) word and both small-size words come from footage that is also in the cases (the
in-sample lines are Replays' 13.0 s SPRITE chest and Thiefs' 21.3 s / 24.9 s chests). Out-of-sample: every RARE line at
normal size, the reference clip's SPRITE line, Replays' vault SPRITE line, and Thiefs' later lines. More streams are
needed before trusting the RARE / SPRITE split as much as the totals; other chest words (e.g. a future "DARK CHEST") will
read as unknown, or - if four letters long - must be checked before they are trusted not to read as RARE.
