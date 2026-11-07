# Diagnostic capture and review

Goal: turn every live miss (or wrong count) into a **repeatable, labelled test case**, so detector changes - and later
Sprite Chests, rewards and match tracking - are measured on real footage instead of tuned on single examples.

```text
live session (app or console) --[capture on]--> captures/<session>/  video + every decision + marks
                                                      |
                     a person fills labels.csv ("truth") while watching the clips
                                                      |
             `review` replays every clip through the CURRENT detector -> review.txt / review.json
             (live vs replay vs labels: found, missed, wrongly counted)
```

## Using it

* App: Settings -> **Diagnostic recording** (Off / around detections and marks / whole session). While playing press
  **Ctrl+Alt+M** (global hotkey, works while Fortnite has the focus) or **Mark moment** when the counter misses a chest.
  Settings -> **Review captures...** runs the review over the captures folder.
* Console: `[capture] mode = "events"` (or `"session"`) in config.toml, key **M** to mark,
  `python -m fortnite_chest_counter review [folder] [--current-settings]`.
* Marks also work with recording off (written to the session log only).

## What is recorded

Exactly the frames the detector analysed: the normalized 1280x720 RGB picture at the detector cadence (15 fps), after
counting, through a bounded queue to a separate FFmpeg encoder. Counting never waits for the recording; a full queue
skips the frame for the recording only (`frames_not_recorded` in capture.json). Disk: refuses to start below 2 GB free,
stops recording below 1 GB. One folder per session (layout in `capture.py`'s docstring): `capture.json`, `video/`
(10-s segments, `clips.json`, an `.ffconcat` playlist per clip), `timeline.csv` (recording frame -> live time),
`events.jsonl`, `marks.jsonl`, `labels.csv`, `README.txt`.

Events mode keeps, per decision, `before_seconds` (10) / `after_seconds` (10) of video and, per mark,
`mark_before_seconds` (30) / `mark_after_seconds` (10) - a mark is pressed after the miss. Segments nothing claims are
deleted about 40 s after they were recorded.

## Format choice (measured)

FORMAT_RESULTS

## Labels and review

`labels.csv` (UTF-8 with BOM, opens in Excel): one row per decision and mark; fill `truth` with `chest`, `not_chest`,
`missed_chest`, `sprite_chest`, `reward`, `other`. For a mark, move `live_time` to the moment the chest really opened;
add `kind=missed` rows for chests nobody marked. `review` matches decisions within 0.6 s (as `research/regress.py`) and
reports, for the live run and for the replay: real chests found as CERTAIN / counted at all, and labelled not-a-chest
items that were counted. By default the detector settings recorded with the capture are used, so a review isolates
code changes; `--current-settings` uses config.toml instead.

Each clip is replayed from its first frame with a fresh estimator; events-mode clips start >= 10 s before a decision, so
the evidence windows (prompt history 2.5 s, popup look-ahead 1 s, prompt finish 5.6 s) are complete.

## Next: a dataset

Collect sessions from different sources (OBS feed, capture card, YouTube / Twitch VODs, low bitrates), label them, and keep
them outside Git (they are large). A future `research/` harness can then run `review` over the whole set and diff against
a stored result, the same way `regress.py` guards the two original recordings today.
