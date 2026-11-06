> **Historical research log.** This is the original development README, kept as the record of how the detector was built and
> validated. Commands and file names below predate the move to `src/`. Mapping: `chest_counter.py` → `fortnite_chest_counter/counter.py`
> (`python -m fortnite_chest_counter`), `visual_detector.py` → `detection/visual.py`, `sprite_detector.py` → `detection/sprite.py`,
> `detector.py` → `detection/audio.py`, `video_sources.py`/`sources.py` → `input/video_sources.py`; `evidence`, `object_cue`, `fusion`,
> `refine`, `predict` → `detection/`. Research scripts are in `research/`. Run module scripts with
> `python -m fortnite_chest_counter.detection.visual` etc., from the repo root, with `samples/` present locally (it is not in Git).
> For the current user-facing behaviour read the top-level `README.md`.

# OBS Chest Counter

Experimental automatic Fortnite chest counter designed for OBS.

The goal is to detect chest-opening events from captured gameplay audio and/or video, maintain a persistent count, and expose the result through a text file that OBS can display.

## Current development stage

Everything here is **offline**: independent detectors analyze a prerecorded gameplay clip and score themselves against hand-labelled chest timestamps. There is no OBS or live-capture code yet and nothing writes `chest_count.txt` yet.

The design is **evidence accumulation**: several independent clues, each a separate detector, are grouped by time and weighed (`fusion.py`).

| Clue | File | Strength |
|---|---|---|
| `CHEST` word in the XP popup | `visual_detector.py` | near-certain; primary signal |
| `+75 CONTAINER OPENED` tag at the sprite badge | `sprite_detector.py` | strong, but conditional and generic (see below) |
| Chest-like 4-11 kHz audio burst | `detector.py` | weak |

Also: a shared ground-truth evaluation (one-to-one matching, raw counts, recall / precision / F1), saved plots, and `audio_experiments.py` (audio ideas that were tried and did not help).

Not implemented: OBS/live capture, a persistent count, writing `chest_count.txt`, loot-burst / chest-animation clues.

## Project structure

During development:

```text
obs-chest-counter/
│
├─ .venv/
│
├─ samples/
│  └─ video tests/
│     ├─ Fortnites-NEW-Low.mp4                      (640x360, with audio)
│     ├─ Fortnites-NEW-Low.wav                      (generated from the mp4)
│     ├─ Fortnites-NEW-HD-No-Audio.mp4              (1280x720, no audio, same recording)
│     └─ Fortnites-NEW-Low-chests-timestamps.txt    (ground truth)
│
├─ templates/                                       (generated: chest/en/chest.npy, chest/pt/bau.npy,
│                                                     container_opened.npy, audio_fingerprint.npy)
├─ analysis_output/                                 (generated plots and caches)
├─ detector.py                                      (audio detector + shared evaluation code)
├─ visual_detector.py                               (CHEST popup detector)
├─ sprite_detector.py                               (sprite "CONTAINER OPENED" tag detector)
├─ fusion.py                                        (groups clues into counted events)
├─ predict.py                                       (blind run on a recording with no labels)
├─ evidence.py                                      (shooting / interaction cue extraction)
├─ refine.py                                        (adjusts MEDIUM events; searches for missed chests)
├─ diagnose_misses.py                               (why did the popup path miss a chest?)
├─ object_cue.py                                    (chest-object cue; second independent candidate search)
├─ audio_experiments.py                             (audio ideas that were tested)
├─ requirements.txt
└─ README.md
```

Future versions will also generate files such as:

```text
chest_count_save.txt
chest_count.txt
```

`chest_count_save.txt` will store the persistent numerical count.

`chest_count.txt` will be intended for OBS to read as a Text source.

## Requirements

Recommended development environment:

- Windows 10/11
- Python 3.13
- FFmpeg
- OBS Studio for eventual live/streaming use

The current development environment was validated with:

- Python 3.13
- FFmpeg 9.0.2

## Setting up Python

Open a terminal in the project directory.

### Install Python

On Windows with WinGet:

```cmd
winget install Python.Python.3.13
```

Close and reopen the terminal after installation if necessary.

Verify available Python installations:

```cmd
py -0p
```

## Create the virtual environment

Create the environment explicitly with Python 3.13:

```cmd
py -3.13 -m venv .venv
```

### Command Prompt

Activate it with:

```cmd
.venv\Scripts\activate.bat
```

A successful activation looks like:

```text
(.venv) C:\...\obs-chest-counter>
```

Verify the Python version:

```cmd
python --version
```

It should report Python 3.13.x.

### PowerShell

Some Windows systems prevent PowerShell from executing `Activate.ps1` because of their execution-policy settings.

Using Command Prompt with:

```cmd
.venv\Scripts\activate.bat
```

avoids changing the system's PowerShell execution policy.

## Upgrade pip

After activating the virtual environment:

```cmd
python -m pip install --upgrade pip
```

## Install Python dependencies

Run:

```cmd
python -m pip install -r requirements.txt
```

The project currently uses:

- NumPy
- SciPy
- Matplotlib
- librosa
- SoundFile

`requirements.txt` contains:

```text
numpy
matplotlib
librosa
soundfile
scipy
```

## Install FFmpeg

FFmpeg is used to extract audio from gameplay video files.

Install it on Windows with WinGet:

```cmd
winget install Gyan.FFmpeg
```

After installation, close and reopen the terminal so the updated PATH is available.

Reactivate the virtual environment:

```cmd
.venv\Scripts\activate.bat
```

Verify FFmpeg:

```cmd
ffmpeg -version
```

If FFmpeg prints version and build information and exits normally, the installation succeeded.

You can also verify its location with:

```cmd
where ffmpeg
```

## Ground-truth timestamps

`samples/video tests/Fortnites-NEW-Low-chests-timestamps.txt` holds one manually verified chest opening per line. Accepted formats:

```text
00:51.30     # minutes:seconds.fraction
01:10.20
51.30        # plain seconds
0:01:10.2    # hours:minutes:seconds
```

Blank lines and `#` comments are ignored. The test clip has six chest openings: the five originally labelled by hand, plus one at about 37.0 s that the visual detector found. Its opening was cut out of the video edit but the `+600 XP CHEST` popup is on screen, and it was confirmed and appended with a comment. **Its time is the popup onset, so the visual detector's timing error there is circular and not meaningful.**

## Offline test workflow

Activate the virtual environment, then:

```cmd
python detector.py                             # audio detector: run, save plots, show them
python detector.py --no-show --zoom 45 90
python visual_detector.py                      # visual detector (first run scans the video, about a minute)
python visual_detector.py --no-show --fusion   # also compare with the audio detector
python sprite_detector.py                      # sprite-tag clue
python fusion.py                               # combine clues and print the estimated count
python predict.py --name Fortnite-PS5-Pro      # blind run on an UNLABELLED recording (writes predictions + review sheets)
python refine.py --name Fortnite-PS5-Pro       # second evidence layer + missed-chest candidates
python diagnose_misses.py --times 11.5 22.0 36.0 78.5 --compare 62.4 182.45   # per-frame diagnosis of misses
python object_cue.py --name Fortnite-PS5-Pro   # chest-object cue + second independent search
python chest_counter.py live --source obs-camera                   # LIVE from the OBS Virtual Camera
python chest_counter.py devices                                    # list video devices / monitors
python chest_counter.py simulate --name Fortnite-PS5-Pro --reset   # live-style run on a recording -> obs_output/
python chest_counter.py show | adjust --certain -1 --approx -1 | reset
python audio_experiments.py                    # reproduce the audio feature ranking table
```

Options: `--tolerance SECONDS` (match tolerance, default 0.75), `--zoom START END` (zoomed timeline), `--no-show` (save plots only). `visual_detector.py --rescan` ignores the cached scores in `analysis_output/visual_scores.npz`.

Both detectors print raw counts first (`MATCHED`, `MISSED`, `FALSE POSITIVES`) and then percentages. With only five labelled chests, one extra chest is a 20-point swing in recall, so read the counts, not the percentages.

Scoring is one-to-one: each detection can satisfy at most one real chest and vice versa, within the tolerance. Plots go to `analysis_output/`.

All tunable parameters are constants near the top of each script.

## Audio detector

Baseline: short-term RMS peaks above `mean + 2.5 * std`.

Chest experiment (`detector.py`):

1. *Candidates:* level of the 4-11 kHz band minus its 4 s running-median background; peaks 8 dB or more above background.
2. *Verifier:* cosine similarity of the candidate's 11-band spectral shape with a fingerprint averaged from the labelled chests. Scores are cross-validated (each labelled chest is scored against the other four).

## Visual detector

When a chest opens, Fortnite shows an XP popup just right of the crosshair (`+900 XP` / `RARE CHEST`). Other popups appear in the same place (`SHIELD CRACKED`, `ELIMINATION`, `CROWN BONUS`, `NEW STORM PHASE`...), so "a popup appeared" produced about 70 false positives. The word `CHEST` is what is chest-specific, and its font is fixed.

1. Video is scaled to 1280x720 and cropped to a region right of the crosshair.
2. Frames become a binary mask of the popup's pink-white lavender text colour.
3. A bitmap of the word `CHEST` (cut from the first labelled chest's popup, `templates/chest/en/chest.npy`; a Portuguese `BAÚ` template, `templates/chest/pt/bau.npy`, runs alongside it and the better match wins) is correlated over the mask (Pearson, so a solid lavender blob scores about 0).
4. An event fires when the score rises above 0.75. It re-arms after the score stays below 0.5 for 0.3 s, never fires twice within 1 s, and also fires if the matched word jumps 8+ px while still high (a second chest's popup replacing the first, as at 70.2 s -> 72.2 s).

## Results (test clip: 6 chests, 508.7 s, tolerance 0.75 s)

| Detector | Chests found | False positives | Events |
|---|---|---|---|
| Audio: RMS baseline | 3 / 6 | 51 | 54 |
| Audio: 4-11 kHz burst similarity (>= 0.95, cross-validated) | 3 / 6 | 43 | 46 |
| Sprite tag `CONTAINER OPENED` (conditional, see below) | 2 / 6 | 2 non-chest containers | 4 |
| **Visual: `CHEST` popup word** | **6 / 6** | **0** | 6 |
| Fused count (`fusion.py`) | 6 / 6 | 0 | 6 |

The visual and fused rows are partly circular: the sixth chest was found by the visual detector, and the fused decision is dominated by the popup. Timing errors for the five hand-labelled chests were -0.18 to +0.35 s, which also confirms the HD and low-res videos are in sync.

### Audio findings

- The five originally labelled chests share a short burst (0.1-0.25 s) concentrated at 4-9 kHz with a steep drop above 11 kHz (pairwise shape similarity 0.89-0.98). Whole-window spectrogram matching fails (music, speech and gunfire dominate).
- About 80 non-chest moments share that burst, mostly the high-frequency crack of gunfire. Burst width and attack time do not separate them.
- Chests have a low-frequency (0.2-1 kHz) precursor about 0.15 s before the burst, and quieter lows 0.5-1.1 s after. Both are real on average but far too variable.
- Tested and **not** better than the existing burst-shape score (median held-out rank 28 of 523): pre/post-burst low-frequency energy, HF-minus-LF contrast, burst level, time x band template correlation, equal-weight combinations, and burst isolation. See `python audio_experiments.py`.
- Audio work was stopped because improvements flattened and the remaining false positives are largely the same gunfire cracks. The chest at 51.3 s occurs in near-silence, where RMS fails but the relative 4-11 kHz measure works, so absolute loudness should not be required.

### Visual: the `CHEST` popup

- When a chest opens, Fortnite shows an XP popup right of the crosshair (`+900 XP` / `RARE CHEST`). Other popups appear there too (`SHIELD CRACKED`, `ELIMINATION`, `CROWN BONUS`, `NEW STORM PHASE`...), so "a popup appeared" gave about 70 false positives. The word `CHEST` is chest-specific and its font is fixed.
- Pipeline: video scaled to 1280x720 and cropped; lavender text colour mask; correlation with bitmaps of the chest word (English `CHEST` cut from the first labelled chest, `templates/chest/en/chest.npy`; Portuguese `BAÚ`, `templates/chest/pt/bau.npy`; best match wins); event when the score rises above 0.75, re-arming after it stays below 0.5 for 0.3 s, never twice within 1 s, and also when the matched word jumps 8+ px while high (a second chest's popup replacing the first, as at 70.2 s -> 72.2 s).
- Other XP popups never score above about 0.65; the chests score 0.79-0.91. Thresholds 0.65-0.80 all find every chest; 0.85 loses some.
- It survives editing that removes the opening itself, camera angle, chest model and loot covering the chest, because it reads the game's own confirmation.
- The template comes from one of the test chests and thresholds were chosen on this one clip. Assumptions that may fail elsewhere: the same HUD layout and language, XP popups enabled, similar compression, and no stream overlay or chat box over the popup region.

### Visual: the sprite tag (`sprite_detector.py`)

Opening a container makes the equipped sprite gain XP; a `+75 CONTAINER OPENED` tag appears beside the sprite badge (right edge) for about 2 s, with level-up chevrons.

- **Consistent when it exists:** it appeared on both chests where the sprite was below max (37 s, 51 s). At 51 s the badge changed from Lv. 4 to MAX.
- **Conditional:** once the badge reads `MAX` (the other four chests) the tag does not appear. A player with a maxed sprite gets no sprite clue at all.
- **Generic, not chest-specific:** it also fired at 334.3 s and 339.9 s, where there was no `CHEST` popup, so those were other containers (not visually identified). Combat, eliminations and gunfire did not trigger it: 4 events in 8.5 minutes.
- Template match is very clean (132x9 px of fixed white text), so the detector itself is reliable; the limitation is what the clue means.

## Evidence accumulation (`fusion.py`)

Popup events anchor the groups. Sprite and audio clues attach to the nearest popup within 1.5 s; clues with no popup are grouped among themselves. Each group scores the sum of its clue weights (popup 1.0, sprite 0.75, audio 0.35): >= 1.0 is counted, >= 0.5 is reported as a candidate.

On this clip it counts 6 (popup on every one, sprite on 2, a nearby audio burst on 3), reports the two non-chest container events as uncounted candidates, and ignores the 37 isolated audio clues. **The weights are priors, not fitted.** There is no chest without a popup in this clip, so the "no popup" branch (sprite + audio = 1.10, counted) is untested. Do not tune it on this clip.

## Confidence tiers

Every event gets an evidence tier, **not a probability**: `CERTAIN`, `HIGH`, `MEDIUM`, `LOW` (and `REJECT` for isolated weak evidence). The tier is only an interpretation layer in `fusion.py`: it changes neither detection, grouping nor the COUNT / CANDIDATE decision, and the raw scores (popup score, template/language, sprite and audio present) are always kept next to it. The cut-offs are provisional, set before looking at verified data, and were not tuned on any clip:

| Tier | Rule (first match wins) |
|---|---|
| CERTAIN | popup >= 0.90, or popup >= 0.85 plus a supporting clue (sprite or audio) |
| HIGH | popup >= 0.85, or popup >= 0.80 plus a supporting clue |
| MEDIUM | popup >= 0.75 (the fire threshold, so every popup event is at least MEDIUM), or sprite + audio together |
| LOW | a sprite clue alone |
| REJECT | an audio clue alone |

Raw scores do not necessarily mean the same in every language: the Portuguese `BAÚ` template is much shorter than `CHEST`, so the same cut-offs are used for now but the matched template is always recorded for per-language calibration later. On the English clip all six real chests are tiered 3 CERTAIN, 1 HIGH, 2 MEDIUM, which shows the cut-offs are conservative for English; they were deliberately not adjusted.

The prediction file has one row per event: `timestamp  decision  confidence  fused-score  popup-score  template  clues  VERIFIED=  # rule`. After watching the clip, edit `VERIFIED=` to `VERIFIED=YES` or `VERIFIED=NO`; those verified rows are then what makes it possible to measure how often each tier is actually right.

## Verified PS5 results and the second evidence layer

The 19 PS5 predictions were verified by hand (`samples/video tests/Fortnite-PS5-Pro-verified-predictions.txt`, a permanent copy; `predict.py` carries its labels forward by timestamp and never writes it):

| Base tier | Real chests |
|---|---|
| CERTAIN | 3 / 3 |
| HIGH | 7 / 7 |
| MEDIUM | 2 / 9 |
| all 19 events | 12 / 19 |

Every event now has a permanent id (`#001`, ...) shared by the prediction file, console output and review sheet names (`event_003_02-16.07_MEDIUM.png`). Ids are the chronological index, so they stay stable as long as the detections do.

`refine.py` adds evidence from `evidence.py` and keeps `base_tier` next to `adjusted_tier` (it never changes the popup detector, thresholds, base tier or labels; CERTAIN/HIGH are never adjusted). Output: `analysis_output/Fortnite-PS5-Pro_event_evidence.txt`.

**Player shooting (negative evidence).** The magazine-ammo number (bottom right) changes on every shot of the local player, unlike enemy gunfire. The region also contains sky and foam, so raw change is meaningless; a *step* (a jump right after a stable sample) is what a firing player produces. Rule: 2+ ammo steps in -1.0 s..+0.5 s around the popup means the player is shooting; shooting + no interaction cue lowers a MEDIUM event to LOW. This is a count of changes, not a reading of the digits, so `ammo_before/after` are not reported. Measured: 3 of the 7 false MEDIUM events are flagged (#009, #012, #019), 0 of the 2 real ones; but 2 of the 12 real chests also show shooting-like steps (#010, #011, both protected), and 20% of arbitrary windows do.

**Muzzle flash** (warm-bright pixel bursts) is much rarer in general (1% of arbitrary windows) and showed bursts of 5-6 at 3 false events and 0-1 at every real one. It also flags #008, which the ammo rule missed. This variant was not adopted because it was seen only after the labels; it is a candidate for validation.

**Interaction prompt (positive evidence).** The round button icon of the SEARCH / COLLECT prompt is language independent. Two versions were tried: a binary ring (noisy; 17% of arbitrary windows reach the level that all 12 real chests reach, 1 of 7 false events does) and a grayscale ring-on-dark-disc patch (selective: 3% of arbitrary windows; present before 10 of the 12 real chests and 0 of the 7 false events). The patch is cut from one frame, so it is unproven. Neither cue rescues the two real MEDIUM events: the patch scored 0.56 / 0.61 for them (background level), so they lack a detectable prompt. Gold-glow share and the binary ring did not separate them reliably either (small n).

**Effect on the 19 events (rules fixed in advance; labels only evaluate):**

| Tier | Before | After |
|---|---|---|
| CERTAIN | 3 / 3 | 3 / 3 |
| HIGH | 7 / 7 | 7 / 7 |
| MEDIUM | 2 / 9 | 2 / 6 |
| LOW | - | 0 / 3 |

Three false MEDIUM events were lowered, neither real MEDIUM event moved, all 10 CERTAIN/HIGH events are unchanged. Four false MEDIUM events remain (they show no ammo steps and no prompt), so this is a partial cleanup, not a fix.

**Missed-chest search.** Independently of the popup, prompt peaks not near any predicted event are listed in `Fortnite-PS5-Pro-missed-chest-candidates.txt` (ids `#M001`...; 5 candidates, review sheets `missed_Mxxx_*.png`). They are candidates only. The generator itself finds a prompt before 10 of the 12 verified chests, so it cannot find chests without a detectable prompt, and recall of the whole system on this clip is **still unknown** until those candidates are verified.

## Missed chests: what the popup path got wrong

Reviewing the five missed-chest candidates found **4 real chests that the popup detector never reported** (`#M001`-`#M004`; `#M005` is an ammo crate). Reviewed labels are kept in `Fortnite-PS5-Pro-verified-missed-candidates.txt` and are carried over by `refine.py` / `object_cue.py` (never written by them).

**Known recall of the popup path: 12 / 16 = 75 %** of the chests verified so far. This is a ceiling for "known" chests, not the final recall: other missed chests may exist.

`diagnose_misses.py` scores every template on every frame (-2 s..+4 s) around each miss. In all four cases the `BAÚ` popup **did appear on screen**; the detector scored it too low or missed it. No hysteresis, jump or duplicate-suppression rule caused any miss (no event was suppressed; the detector was armed).

| Chest | When the popup appeared | Best `BAÚ` score | Word pixels kept by the colour mask | Reason |
|---|---|---|---|---|
| M001 00:11.5 | about +3 s after the prompt | 0.7499 (a hair under 0.75) | 81 % | score just under the threshold; popup late, on foliage |
| M002 00:22.0 | +1.3 to +3 s | 0.55-0.63, brief 2-frame spike to 0.82 | 86 % | partly occluded by the chest model and foliage; the spike lasted 2 frames and the detector samples every 2nd frame |
| M003 00:36.0 | about +1.7 s | 0.52-0.56 | **53 %** (67 % with a looser mask) | text blends into the green bamboo, the colour mask loses a third of the word |
| M004 01:18.5 | about +3 s | 0.60-0.64 | 75-79 % | stacked popup: the chest is the 4th line, under "caixa de munição" / "nova fase da tempestade" (76 lit pixels in the line above) |

For comparison, four detected chests keep 93-100 % of the word's pixels with 0-4 extra lit pixels. So the misses form a subgroup: **degraded or crowded popups** (occlusion, green backgrounds, stacked lines) and, for M001, a popup just under the threshold. Lowering the global threshold is not a fix: the missed scores (0.52-0.64) overlap the false MEDIUM events and background (0.77-0.81 for false events), and at 0.65 the clip would already give 30 events instead of 19. Recall should come from another evidence path.

## Chest object vs. other containers (`object_cue.py`)

The interaction prompt is generic (chest, ammo crate, loot pickup, cannon...). The object it points to is not: chests are highlighted with a **gold outline and carry purple gems**; the ammo crate is an olive box with a white outline. In a fixed box on the object's side of the prompt, raw gold / gem / olive / white pixel shares are reported for every moment:

- 14 of the 16 known chests are "chest-like" (gold >= 0.4 % or gems >= 0.05 %); the other two (01:32.29, M001) are exactly the two where the prompt was barely found (0.56 / 0.52), so the box was in the wrong place.
- The ammo crate has exactly 0 % gold and 0 % gems.
- **Provisional only:** there is a single negative example, so the cut-offs are not calibrated. A lit yellow window can also read as gold (see below).

**Second independent search** (prompt >= 0.60 anywhere in the clip, not near a verified chest or the ammo crate): 5 new moments in `Fortnite-PS5-Pro-new-chest-candidates.txt` (`#N001`-`#N005`, sheets `new_Nxxx_*.png`), 1 flagged chest-like. A quick unverified look suggests these are generic prompts (item pickup, cannon, "ammo already full"), and the single chest-like flag appears to be a lit yellow window, so no new chest is expected from this search; verify them. The prompt generator has a prompt near 15 of the 16 known chests.

## Live-style estimator and OBS output

`estimator.py` consumes frames one at a time in order (no future frames, no rescans) and returns *finished* events, one per chest: popup events finish 1.0 s after the popup appears, prompt events 5.6 s after the prompt (the time the estimator waits to see whether a popup merges with it). A popup whose onset is from 1 s before to 4.5 s after a prompt is **merged with it**, so a chest seen by both paths counts once. `chest_counter.py` turns finished events into counts, writes the OBS files, logs every event and offers manual controls. The frame source is a one-method interface (`frames()` yielding `(seconds, 720p RGB frame)`); `Mp4FrameSource` is the only implementation today.

**Two counts** (all rules are constants at the top of `estimator.py`):

| Count | What it includes |
|---|---|
| `CERTAIN OPENED CHESTS` | popup events whose adjusted tier is CERTAIN or HIGH. Prompt/object events can never be CERTAIN (`INTERACTION_CAN_BE_CERTAIN = False`). |
| `APPROX. OPENED CHESTS` | CERTAIN + HIGH, plus MEDIUM popups of languages whose chest word is long enough (English `CHEST`: yes, Portuguese `BAÚ`: no), plus MEDIUM popups backed by a prompt + chest-object, plus prompt + chest-object events whose popup never fired. |

Never counted but always logged: LOW (a MEDIUM popup while the player is shooting), generic prompts (item pickups, ammo crates, cannons...), everything else. Two rules were set with knowledge of this data and are flagged as provisional in the code: the per-language MEDIUM rule (English MEDIUM popups were 6 of 6 real on one clip; Portuguese MEDIUM 2 of 9) and the 0.60 prompt level for MEDIUM support. The audio detector is not in the live path yet (it needs a streaming audio buffer and was the weakest clue).

**OBS files** (`obs_output/`, UTF-8, written atomically via a temp file + replace, with retries for Windows; labels are constants in `chest_counter.py`). In OBS: add a *Text (GDI+)* source, tick *Read from file*, and pick the file.

| File | Example contents |
|---|---|
| `certain_chests.txt` | `CERTAIN OPENED CHESTS: 10` |
| `approximate_chests.txt` | `APPROX. OPENED CHESTS: 15` |
| `chest_status.txt` | `10 certain • ~15 estimated` |
| `last_chest.txt` | `CHEST +1 • CERTAIN` (or `CHEST ~+1 • APPROX`) |

**State and log.** Counts persist in `state/chest_state.json` (atomic writes) and survive restarts; nothing resets unless you run `reset` (or `simulate --reset`). `simulate` refuses to run over a non-zero count unless you pass `--reset` or `--start SECONDS` (to continue a previous run). Every finished event, counted or not, is appended to `logs/session_<time>.jsonl` with its raw evidence, tier, source, increments and counts afterwards. `adjust --certain N --approx N` makes a logged manual correction. Run `reset` before a real stream: the files in `obs_output/` currently hold the result of the PS5 simulation.

**Offline regression (events produced chronologically, then compared with the verified data):**

| Recording | CERTAIN | APPROX | Known real | Counted but wrong | Known chests in the event stream |
|---|---|---|---|---|---|
| English clip | 3 (3 real) | 6 (6 real) | 6 | 0 | 6 / 6 |
| Portuguese PS5 clip | 10 (10 real) | 15 (15 real) | 16 | 0 | 16 / 16 |

On the PS5 clip, 10 chests are CERTAIN/HIGH popups, 4 are recovered by prompt + chest-object events (`#M001`-`#M004`, counted APPROX only), 1 true MEDIUM popup (07:10) is counted via prompt support, and 1 true MEDIUM popup (01:32) is represented but not counted, which is the only known real chest missing from the APPROX count (-1). All 7 verified-false popups are not counted (3 are lowered to LOW by the shooting cue) and the ammo crate is not counted. No chest was counted twice. "Counted but wrong" only covers what has been verified; undiscovered chests and unverified false positives are unknown, so recall is still not claimed. The English numbers use the same clip the English rules were set on.

Processing speed on this machine: about 2x real time (the 17-minute PS5 clip took about 8.5 minutes).

## Going live: OBS setup (single PC and dual PC)

The detector is a **passive pixel reader**. It does not touch Fortnite (no memory access, no injection, no input, no AutoHotkey) and nothing runs on a gaming PC. It reads a clean gameplay picture from OBS, so the same setup works for one PC and two PCs; only what feeds OBS differs.

```text
SINGLE PC:   Fortnite -> OBS Game Capture -> scene "ChestDetectorFeed" -> OBS Virtual Camera -> chest_counter.py live
DUAL PC:     Gaming PC -HDMI-> capture card -> Streaming-PC OBS (Capture Device) -> scene "ChestDetectorFeed" -> Virtual Camera -> chest_counter.py live
BOTH:        chest_counter.py -> obs_output/*.txt -> OBS Text sources in your stream scene
```

In a dual-PC setup run `chest_counter.py` on the **streaming PC** only; the gaming PC needs no detector software.

**1. Make the clean detector feed.** In OBS create a scene named `ChestDetectorFeed` containing ONLY the game picture (Game Capture for a single PC, Video Capture Device for the capture card). No webcam, alerts, chat, stream graphics, or the chest-counter text. The detector must never see its own overlay.

**2. Send that scene to the Virtual Camera.** Start the OBS Virtual Camera. In OBS 28 or newer open the Virtual Camera settings and set the output type to *Scene* (or *Source*) and pick `ChestDetectorFeed`, so the camera shows the clean scene instead of your finished stream with overlays (menu labels can differ between OBS versions). Use a 16:9 canvas (1920x1080 or 1280x720); the detector scales to 1280x720 itself.

**3. Run the detector:**

```cmd
python chest_counter.py devices                      REM check that "OBS Virtual Camera" is listed
python chest_counter.py live --source obs-camera
```

It prints the input resolution/fps, where the counter state is loaded from and where the text files go, then a compact status line every 5 s and a detail line for each chest. Counts are **never reset at startup**; use `--reset` or `python chest_counter.py reset` deliberately. Ctrl+C stops cleanly (final events are finished, files and state are saved, the session log gets a `session_end` record).

**4. Show the counts in your stream scene.** Add a *Text (GDI+)* source, tick *Read from file*, and choose `obs_output/certain_chests.txt` (and a second one for `approximate_chests.txt`, or `chest_status.txt` for one line). Run `reset` before your first real stream: the folder may still contain the PS5 test numbers.

**Other sources** (`--source`, or `source` in `[live]`):

| Source | Command | Notes |
|---|---|---|
| OBS Virtual Camera | `live --source obs-camera` | Recommended. Works for one or two PCs. |
| Capture card directly | `live --source device --device "NAME"` | Advanced. Some drivers refuse a second reader while OBS holds the card; if so use the OBS feed. |
| Desktop | `live --source desktop --monitor 1` | Fallback for single-PC users. Fragile: alt-tab, windows covering Fortnite, resolution changes and overlays all change what the detector sees. |
| Recorded file, in real time | `live --source file --video PATH --start 55 --duration 70` | For testing the live pipeline without a device. |

**How the live loop behaves.** ffmpeg (already required) opens the source, scales to 1280x720 and reduces it to the detector cadence (default 15 fps); a reader thread keeps only the newest frame, so a slow detector skips frames (counted as `dropped`) and latency never accumulates. No frames are written to disk and no Python packages were added (`tomllib` is in Python 3.11+).

**Measured here** (Windows, PS5 clip played in real time through the live loop, and the same clip captured from a full-screen player by the desktop backend): 15.0 detector fps, 0 dropped frames, about 4-8 ms per frame, about 42 % of one CPU core for the detector process (video decoding runs in a separate ffmpeg process). Latency from the moment a chest event starts to the updated text file: **about 1.0-1.1 s** for popup events and about **5.6-5.7 s** for prompt-only events (the estimator deliberately waits to see whether a popup merges in); writing the files takes about 15-20 ms. Ctrl+C and a restart without `--reset` were both tested live (the counts were kept). **Not tested here:** the OBS Virtual Camera path itself. OBS was not running and I did not launch OBS or touch its configuration; `devices` finds the camera and a missing/inactive camera gives a clear error. Desktop capture matters for setup: scaling the picture twice (full-screen playback, then capture) dropped a CERTAIN popup score from 1.00 to 0.85 (still counted), which is another reason to prefer the clean OBS feed at native resolution.

## Configuration (`config.toml`)

Copy `config.example.toml` to `config.toml` (next to `chest_counter.py`), or pass `--config PATH`. Precedence: built-in defaults, then the file, then command-line options (`--process-fps`, `--state`, `--obs-dir`, `--log-dir`, `--source`, `--device`, `--monitor`). A missing file is fine, a missing key uses its default, and a typo or invalid value prints a warning and falls back to the default for just that value (an unreadable file falls back to all defaults).

| Section | Key | Default | Meaning |
|---|---|---|---|
| `[detector]` | `process_fps` | 15 | detector cadence (5-30); 15 is what everything was tested at |
| | `languages` | `["en", "pt"]` | chest-word templates to use |
| | `certain_min_tier` | `"HIGH"` | `"HIGH"`: CERTAIN and HIGH popups are certain; `"CERTAIN"`: only CERTAIN |
| | `count_supported_medium_as_approx` | true | MEDIUM popup with a prompt + chest-like object counts as approximate |
| | `count_interaction_object_as_approx` | true | prompt + chest-like object without a popup counts as approximate |
| | `medium_counts_alone_languages` | `["en"]` | languages whose MEDIUM popups count as approximate on their own |
| `[display]` | `certain_label`, `approximate_label` | `CERTAIN OPENED CHESTS`, `APPROX. OPENED CHESTS` | text before the number |
| | `combined_status_format` | `{certain} certain • ~{approximate} estimated` | `chest_status.txt` line; placeholders `{certain}` `{approximate}` |
| | `use_thousands_separator` | true | `1,232` instead of `1232` |
| `[state]` | `persist`, `path`, `obs_dir` | true, `state/chest_state.json`, `obs_output` | counter state file and OBS text folder |
| `[logging]` | `enabled`, `log_candidates`, `dir` | true, true, `logs` | JSONL session log; `log_candidates` also records events that were not counted |
| `[live]` | `source`, `device`, `monitor`, `status_interval_seconds` | `obs-camera`, `OBS Virtual Camera`, 1, 5 | default live source and its options |

Detector internals (template thresholds, windows, weights) deliberately stay constants in the code.

**Number formatting.** Every user-facing count goes through one helper (`settings.format_count`): `0`, `999`, `1,000`, `1,232`, `1,234,567` (or plain integers when `use_thousands_separator = false`). That covers the OBS text files, `show`, `adjust`, `reset`, the live status line and the event lines. The state file always stores plain integers. `python test_basics.py` checks the formatting (0, 999, 1000, 1232, 1000000), missing / partial / invalid config, and CLI-over-config precedence.

**What remained before a live capture (now mostly done):** (1) run the OBS Virtual Camera path on a real session (see above; the frame source itself is built and tested on file and desktop sources); (2) a streaming audio buffer if the audio clue is wanted; (3) review the session log of a real game to collect verified data; (4) other languages (a chest-word template each) and other HUD layouts.

## Blind test on a second recording (PS5, Portuguese, no commentary)

`predict.py` runs every detector **unchanged** on a recording with no ground truth, groups the clues with `fusion.py`, writes `samples/video tests/<name>-predicted-chests.txt` (marked UNVERIFIED, never ground truth) and review contact sheets (`analysis_output/<name>_review/`, one per predicted event, frames every 0.25 s from -1.0 s to +2.0 s, plus `_overview_popup_region.png` showing the popup area of every event at once). The only compatibility change for the audio detector: its fingerprint comes from the first clip's labels (`templates/audio_fingerprint.npy`, built once), because the new clip has none.

Recording `Fortnite-PS5-Pro` (1029.2 s, 1280x720 HD + 640x360 low, 29.97 fps, stereo audio): the two files are the same recording and aligned (frame-image correlation 0.997, motion lag +0.00 s).

### Attempt 1: English template only

0 events from every clue. The recording is in Portuguese: the popup reads `+600 EXP` / `BAÚ` in the same place and colour, so the English word `CHEST` could not match (peak score 0.33).

### Attempt 2: English + Portuguese templates

Only change: a second chest-word template, `pt:BAÚ`, cut from the confirmed chest popup at 64.0 s of this recording (so the 01:02.40 event is in-sample). The detector scores every template on every frame and uses the best one. Same ROI, colour mask, correlation, thresholds, hysteresis, grouping window and fusion weights. The English clip was re-run first and is **unchanged: 6 / 6 chests, 0 false positives** (fused count also unchanged).

Blind result on the PS5 clip:

| Clue | Result |
|---|---|
| Popup events | **19**, all from `pt:BAÚ`, 0 from `en:CHEST` |
| Sprite tag | 0 (no sprite badge on this recording's HUD) |
| Audio | 0 accepted of 868 candidates (99th-percentile similarity 0.82, threshold 0.95) |
| Fusion | 19 COUNT (popup only, fused score 1.00 each), 0 CANDIDATE, 0 ignored; tiers: 3 CERTAIN, 7 HIGH, 9 MEDIUM, 0 LOW |

Popup score distribution on this clip (50/90/99/99.9 percentile): 0.00 / 0.44 / 0.79 / 0.98 (first clip, English: 0.00 / 0.40 / 0.77 / 0.91). The highest score peaks that did **not** become events were 0.80, 0.79, 0.75, 0.75, 0.75, 0.72, 0.72, 0.71, i.e. right at the 0.75 fire threshold. For the English `CHEST` word the gap between noise and chests was wide; for the short `BAÚ` glyph (14x7 px) noise reaches the threshold.

**Unverified preliminary read of the review overview (not ground truth):** about half of the 19 events show a clear `+600 EXP` / `BAÚ` popup (plus two popups with an extra line above `BAÚ`); several others show `ESCUDO QUEBRADO` (shield cracked) popups, and a few show no obvious popup at the sampled moment. The ten events scoring 0.86 or more all look like chest popups; most events scoring 0.82 or less do not. If verification confirms this, the English threshold of 0.75 does not transfer to the shorter template. **Nothing was tuned on this.** The predicted file stays as generated until it is reviewed.

Audio on clean, commentary-free sound did not become more useful: no candidate matched the first clip's fingerprint. The fingerprint is probably specific to the first clip's mix and platform.

## Limitations

- **Each game language needs its own chest-word template.** English (`CHEST`) and Portuguese (`BAÚ`) are supported; adding a language means adding a row to `CHEST_TEMPLATES` in `visual_detector.py`. Short words are less specific than long ones, so one threshold may not suit every language.
- The clues were developed on one clip. The blind test on a second recording first produced nothing (language) and, with a Portuguese template, 19 unverified events that appear to include false positives.
- The popup is a single point of failure for the strong decision. If the HUD is hidden, in another language, or covered by an overlay, only the weaker clues remain, and on this clip those cannot count a chest by themselves.
- The sprite clue needs a non-maxed sprite.
- The ammo cue counts changes of a fixed screen region (PS5 HUD layout); it misses shooting while the camera moves and cannot say how much ammo there is. The prompt cues were cut from one clip.

## Recommended next step

Connect a live frame source and run the estimator on a real play session, then review `logs/session_*.jsonl` against what really happened and save the verified events. That produces the verified data needed to check the counting rules (especially the two provisional ones), measure recall, and decide whether the tiers deserve calibrated probabilities. The 5 unverified candidates in `Fortnite-PS5-Pro-new-chest-candidates.txt` can be checked at any time.

## OBS output

A later version of the detector will write something like:

```text
Chests: 42
```

to:

```text
chest_count.txt
```

OBS can display this using:

1. Add a **Text (GDI+)** source.
2. Enable **Read from file**.
3. Select `chest_count.txt`.
4. Style and position the counter as desired.

The detector does not need to control OBS directly.

## Intended live architecture

For a two-PC streaming setup:

```text
Gaming PC
    ↓
Capture card
    ↓
Streaming PC
    ↓
Audio/video detector
    ↓
chest_count.txt
    ↓
OBS
```

The detector can therefore run entirely on the streaming computer.

## Development philosophy

The detector should operate only on captured audio/video.

It should not:

- read Fortnite process memory
- inject into Fortnite
- modify Fortnite
- automate player input
- control gameplay

The objective is passive event recognition from the same audio/video signal that a streamer or OBS already receives.