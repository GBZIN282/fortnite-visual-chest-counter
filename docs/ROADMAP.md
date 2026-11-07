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

## v0.2.0 - Desktop app (in development on branch `dev/v0.2.0`, not released)

No detection changes. Draft notes: [RELEASE_NOTES_v0.2.0.md](RELEASE_NOTES_v0.2.0.md). Trust/signing analysis:
[WINDOWS_TRUST.md](WINDOWS_TRUST.md).

Done (dev build): one PySide6 app replacing every `.bat` (Dashboard with source list + Start/Stop, optional activity panel
with Normal/Debug detail, optional live preview, Overlay page, Edit counts / Reset, Analyse a recording, Settings, Help &
diagnostics); counting stays in the separate `live --gui` worker; small reproducible launcher exe; trimmed signed Qt files;
signature report per build; tests in `tests/test_app.py`.

First hands-on test (user, 2026-11-07): counting chests from a heavily compressed YouTube VOD through the app. The earlier
Twitch/Switch source did not count; cause not yet known (input, HUD scale or pipeline - not compression alone).

Also done: **diagnostic capture** ([CAPTURE.md](CAPTURE.md)) - optional recording of exactly what the detector analysed
(around decisions/marks, or the whole session), Ctrl+Alt+M / Mark moment / console M, labels.csv, and the `review`
command that replays captures through the current detector. This is the data foundation for everything below.

Before release:
1. The user's hands-on test of the app with OBS (single PC), then the two-PC / Wi-Fi tests - with diagnostic recording on.
2. Smart App Control: read PC B's CodeIntegrity log (which file is refused); decide on signing (see WINDOWS_TRUST.md).
3. Final build + scan (the top-level `README.md` is rewritten for the app on this branch; review it before merging).
4. Optional, separate change: replace `scipy.signal.fftconvolve` with NumPy (-107 unsigned files, -30 MB) only if the
   regression harness shows identical events.

## After v0.2.0 - from chest counter to match analytics (user's direction, 2026-11-07)

Every step is built and measured on labelled captures (CAPTURE.md), never by tuning thresholds on a single example.
Order agreed with the user: capture -> better chest recognition -> match lifecycle -> Auto language -> analytics.

- **B. More loot types** - Sprite Chests and other chest variants whose pop-up word is not just "CHEST", as their own event
  types next to normal chests (one opening = one event, whatever clues fire).
- **C. Rewards** - the "YOU FOUND ..." animation and similar reward cues as their own events, de-duplicated across frames
  and linked to the chest they came from when the footage shows it.
- **D. Match lifecycle** - lobby / in match / eliminated / spectating / results from several on-screen cues (a small state
  machine, never one cue alone), so every chest and reward belongs to a match.
- **D2. Auto language** - only after D: identify English or Portuguese (Brazil) from the pop-ups at the start of each match,
  lock it for the match, reset at the lobby; while unsure keep checking both (never trade chests for a language guess).
  Until then the Settings choice is English / Portuguese (Brazil) / Both - "Both" is not automatic detection.
- **E. Analytics** - per match and per session: chests, Sprite Chests, rewards, rates, history. Observed frequencies are
  not Fortnite's drop odds: they need the right denominator (e.g. rewards per eligible Sprite Chest), mode/season
  separation and a known detection completeness before they mean anything.

## v0.1.2 candidates - video inputs (not implemented yet)

The source picker (item 1) is now part of the v0.2.0 app's video source list.

Input layer only; the detector stays frozen. Rationale and measurements: [INPUT_OPTIONS.md](INPUT_OPTIONS.md).

1. **Video source picker** - `Select Video Source.bat`: choose OBS Virtual Camera, an OBS projector window, a capture device
   or a monitor from a numbered list; writes `config.toml` so nobody has to edit it or type device names.
2. **OBS projector window capture** (Windows Graphics Capture via FFmpeg `gfxcapture`): uses gameplay OBS already captures,
   leaves the Virtual Camera free, opens the capture card only once (in OBS), needs no plugin or second monitor.
3. **Explicit capture format for capture cards**: prefer 1280x720 @ 30 fps, then 1920x1080 @ 30 fps, else the device
   default; user overrides `video_size` / `framerate`. Avoid 4K / 60 fps (the detector uses 1280x720 @ 15 fps).
4. **Clear "device in use" message** when OBS (or another app) already holds the capture card.
5. **Tell identical capture cards apart** (DirectShow alternative names).

Validation required before release: see the checklist at the end of [INPUT_OPTIONS.md](INPUT_OPTIONS.md).

## Later

- OBS WebSocket for source discovery (after measuring its cost on OBS).
- Own OBS plugin for a fully integrated "pick your gameplay source" experience, if users ask for it.
- More Fortnite languages (needs a pop-up word template per language).
- Accuracy: validate the blurred second trigger (see [ACCURACY_NOTES.md](ACCURACY_NOTES.md)) with labeled live sessions.
