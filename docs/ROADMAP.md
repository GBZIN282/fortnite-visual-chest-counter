# Roadmap

## v0.1.0 - Public Beta (released)

Detector frozen at the `rc1` baselines (`tests/baselines/*_rc1.json`).

## v0.1.1 - usability (released; download refreshed 2026-11-06)

No detection changes. Notes: [RELEASE_NOTES_v0.1.1.md](RELEASE_NOTES_v0.1.1.md).

- Customisable overlay text (`certain_text`, `approx_text`, `{count}` / `{certain}` / `{approx}`), `show` mode, and the
  single `chest_counter.txt` overlay file. v0.1.0 settings and file names keep working.
- Colour-coded console with `minimal` / `normal` / `debug` verbosity.
- In-zip guide updated with the other video inputs.
- `Set Starting Count.bat` (`set-count`): start from the chests already opened (APPROX = total, CERTAIN = 0).
- `Configure Counter.bat` (`configure`): menu for what viewers see + wording (`#` = number), applied live; `show` also
  drives `chest_status.txt`; startup states what viewers see and which file OBS should read.
- Reset / Set Starting Count can no longer be overwritten by a chest counted in the same second.
- Release runs on the official python.org embeddable Python (signed), no self-built executable; reproducible zip,
  `runtime/PROVENANCE.txt`.

## v0.2.0 - Desktop app (released 2026-11-07, public beta)

One detection addition (scale-aware pop-ups, below); otherwise the v0.1.1 detector. Notes:
[RELEASE_NOTES_v0.2.0.md](RELEASE_NOTES_v0.2.0.md). Trust/signing analysis: [WINDOWS_TRUST.md](WINDOWS_TRUST.md).

Done: one PySide6 app replacing every `.bat` (Dashboard with source list + Start/Stop, optional activity panel with
Normal/Debug detail, optional live preview, Overlay page, Edit counts / Reset, Analyse a recording, Settings, Help &
diagnostics); counting stays in the separate `live --gui` worker; small reproducible launcher exe; trimmed signed Qt files;
signature report per build; tests in `tests/test_app.py`.

Also done: **diagnostic capture** ([CAPTURE.md](CAPTURE.md)) - optional recording of exactly what the detector analysed
(around decisions/marks, or the whole session), Ctrl+Alt+M / Mark moment / console M, labels.csv, and the `review`
command that replays captures through the current detector. This is the data foundation for everything below.

Release items (status 2026-11-07):
1. Done: hands-on tests of the app with OBS on one PC (YouTube VOD and streamers' VODs, diagnostic recording on). The
   earlier Twitch/Switch source that did not count: cause not confirmed.
2. Done: the **scale-aware pop-up channel** (`estimator.SCALE_AWARE_POPUPS`, user's decision to ship it in v0.2.0) -
   event-identical on all references, recovers every verified miss on 1.2x-HUD streams (APPROX only). Evidence, cost and
   limits: [INVESTIGATION_2026-11-07.md](INVESTIGATION_2026-11-07.md).
3. Done after release (2026-11-07): **dual-PC SRT test with the public v0.2.0 download.** Gaming PC (i9 13th gen, RTX 4080)
   OBS SRT caller -> local network -> streaming PC (i5 13th gen, RTX 4070) OBS Media Source (SRT listener, MPEG-TS) ->
   OBS Virtual Camera -> app. Video: a Fortnite stream playing on the gaming PC. Numerous chests counted, no noticeable
   lag. Documentation only: [guides/obs-dual-pc-srt.md](guides/obs-dual-pc-srt.md), the v0.2.0 release notes and the
   GitHub release description were updated; zip, checksums and tag unchanged.
4. Open: Smart App Control on the second PC (CodeIntegrity log: which file is refused); signing decision
   ([WINDOWS_TRUST.md](WINDOWS_TRUST.md)).
5. Open: a physical capture card (through OBS and directly) and the OBS projector / Screen input.
6. Optional, separate change: replace `scipy.signal.fftconvolve` with NumPy (-107 unsigned files, -30 MB) only if the
   regression harness shows identical events.

## Next milestones (agreed with the user, 2026-11-07)

v0.2.0 showed that automatic chest counting works, including on a real two-PC streaming setup. The next challenge is not
recognition but turning detections into gameplay statistics:

| Version | Milestone |
|---|---|
| v0.2.0 | Automatic chest counting and a usable desktop app (released) |
| **v0.3.0** | **Match Tracking & Statistics Foundation** - the backend that makes statistics possible |
| **v0.4.0** | **Statistics & Performance Analytics** - records, history and trends on top of v0.3.0 |

These are **planning milestones, not implementation authorization**: each one starts with an investigation and a design
the user approves before any code changes.

### v0.3.0 - Match Tracking & Statistics Foundation (planned)

Goal: turn the continuous stream of counted chests into organised, reliable, match-specific data. Today the app knows that
a chest was opened; v0.3.0 should also know **which match** it belongs to, and keep that information.

```text
video recognition -> chest event -> match lifecycle (which match, which state) -> attribution
                  -> persistent history -> (v0.4.0) statistics
```

| Component | Objective |
|---|---|
| Match lifecycle | Identify when a match starts and ends |
| Match attribution | Assign each counted chest to the correct match |
| Match counters | CERTAIN and APPROX per match (APPROX includes CERTAIN, as today) |
| Event history | Keep every individual detection with its evidence |
| Persistence | Restore the history after restarting the app |
| Manual correction | Start / end a match by hand; correct a wrong boundary afterwards |
| Internal statistics API | One clean, read-only interface over stored matches and events for v0.4.0 |
| Regression safety | Detection and overlay behaviour unchanged (`regress.py` event-identical; same `obs_output` files) |

Design principles:

- **Immutable chest events.** Every counted chest is stored once, append-only (time, tier, CERTAIN/APPROX contribution,
  evidence, source). Match boundaries are separate records that can be corrected; per-match totals are always derived from
  events + boundaries, never the only stored copy. A wrong boundary is then fixed without losing any detection, and v0.4.0
  can recompute every statistic.
- **Uncertain boundaries never silently corrupt history.** A match whose start or end is not confirmed is marked as such,
  so statistics can include or exclude it - never guess quietly.
- **Manual actions are recorded, not mixed in.** Edit counts / Reset and manual match start/end are stored as corrections,
  so a starting count of 150 never appears as the chests of one match.
- **Room for more event types** (Sprite Chests, rewards - items B and C below) without changing the format.
- **Recordings stay separate.** Analyse a recording / Review captures do not write into the live history unless the user
  asks.
- **Same architecture and fair-play position:** video-only (no game memory, files, network or Fortnite API), counting in
  the separate worker, the running total and OBS overlay working exactly as in v0.2.0. Data stays local in the app folder.

Investigate match boundaries **before** implementing them - the biggest technical risk. Recognising a chest pop-up is one
thing; recognising a match boundary across lobby, matchmaking / loading screens, the bus, own gameplay, elimination,
spectating, victory / results, replays, streams and different HUD settings is another. No assumption that a universal
visual cue exists:

1. Collect labelled whole-session captures ([CAPTURE.md](CAPTURE.md)) covering those situations, from more than one
   streamer and HUD scale.
2. Measure each candidate cue on them (hit rate, false triggers, delay) before relying on it.
3. Combine cues in an **explicit state machine** (for example unknown / lobby / in match / spectating / post-match, with
   "unknown" as a real state), never one cue alone.
4. Automatic transitions only where measured as reliable; everywhere else manual start / end in the app, with automatic
   suggestions at most. Chests seen while spectating someone else must not be credited to the user's match.

Also in v0.3.0: ship the setup guides (`docs/guides/`) inside the ZIP's offline `README.html`.

Not in v0.3.0: the statistics dashboard (v0.4.0), Auto language (D2, needs match tracking first), detection changes beyond
what match tracking needs (any change must keep chest events identical in `regress.py`).

### v0.4.0 - Statistics & Performance Analytics (planned)

Goal: a statistics view built only on the v0.3.0 backend, to benchmark performance over time.

- Total chests, matches analysed, average chests per match, **personal record** (most chests in one match), match history,
  performance over time; **chests per minute** only if match timing proves reliable.
- **CERTAIN and APPROX stay separate** in every statistic and record: a record based on estimated (APPROX) chests is labelled
  as estimated and never shown as equally verified as one made of CERTAIN chests.
- Matches with unconfirmed boundaries are shown as such and left out of records by default.
- Everything is recomputed from the stored events, so a corrected boundary updates every number.
- Later analytics (rates, Sprite Chests, rewards) need the right denominator, mode / season separation and a known detection
  completeness before they mean anything; observed frequencies are not Fortnite's drop odds.

## Unscheduled ideas (still valid; after or between the milestones above)

Every step is built and measured on labelled captures (CAPTURE.md), never by tuning thresholds on a single example.

- **A2. HUD scale** - scale-aware English pop-ups shipped in v0.2.0 (APPROX only). Next, with more labelled large-HUD
  captures: scale the sprite-tag and prompt clue boxes with the same estimate, re-check the locked scale when the HUD
  changes, decide whether any scaled pop-up may be CERTAIN. No user-facing "algorithm" setting - one adaptive detector.
- **B. More loot types** - Sprite Chests and other chest variants whose pop-up word is not just "CHEST", as their own event
  types next to normal chests (one opening = one event, whatever clues fire).
- **C. Rewards** - the "YOU FOUND ..." animation and similar reward cues as their own events, de-duplicated across frames
  and linked to the chest they came from when the footage shows it.
- **D2. Auto language** - after v0.3.0: identify English or Portuguese (Brazil) from the pop-ups at the start of each match,
  lock it for the match, reset at the lobby; while unsure keep checking both (never trade chests for a language guess).
  Until then the Settings choice is English / Portuguese (Brazil) / Both - "Both" is not automatic detection.

### Video input candidates

The source picker is part of the v0.2.0 app's video source list. Input layer only; the detector stays frozen. Rationale and
measurements: [INPUT_OPTIONS.md](INPUT_OPTIONS.md).

1. **OBS projector window capture** (Windows Graphics Capture via FFmpeg `gfxcapture`): uses gameplay OBS already captures,
   leaves the Virtual Camera free, opens the capture card only once (in OBS), needs no plugin or second monitor.
2. **Explicit capture format for capture cards**: prefer 1280x720 @ 30 fps, then 1920x1080 @ 30 fps, else the device
   default; user overrides `video_size` / `framerate`. Avoid 4K / 60 fps (the detector uses 1280x720 @ 15 fps).
3. **Clear "device in use" message** when OBS (or another app) already holds the capture card.
4. **Tell identical capture cards apart** (DirectShow alternative names).

Validation required before release: see the checklist at the end of [INPUT_OPTIONS.md](INPUT_OPTIONS.md).

## Later

- OBS WebSocket for source discovery (after measuring its cost on OBS).
- Own OBS plugin for a fully integrated "pick your gameplay source" experience, if users ask for it.
- More Fortnite languages (needs a pop-up word template per language).
- Accuracy: validate the blurred second trigger (see [ACCURACY_NOTES.md](ACCURACY_NOTES.md)) with labeled live sessions.
