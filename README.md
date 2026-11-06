# Fortnite Visual Chest Counter

**Visual chest detection for OBS, capture cards & video files.**

Computer-vision Fortnite chest counter for live OBS / capture-card feeds and prerecorded gameplay. It watches gameplay
**pixels** and estimates how many chests have been opened, then writes the numbers to text files that an OBS Text source can
show on stream.

It does **not** read Fortnite memory, use any Fortnite API, modify the game, inject code or automate gameplay.

> Not affiliated with or endorsed by Epic Games. "Fortnite" is a trademark of Epic Games, Inc.
> Status: **v0.1.0 public beta**. Windows only. No Python needed for the downloadable release.

## The two numbers (read this first)

| Counter | Meaning |
|---|---|
| **CERTAIN OPENED CHESTS** | Chest openings detected with strong visual evidence. The conservative number. |
| **APPROX. OPENED CHESTS** | Estimated **TOTAL** chest openings, **including** the certain ones. |

Example: `CERTAIN: 42` and `APPROX: 51` means *about 51 chests were opened, 42 of them strongly confirmed*.
**Do NOT add them together** (that would be 93, which is wrong). APPROX is always greater than or equal to CERTAIN.

APPROX is an estimate, not an exact count. See [Known limitations](#known-limitations).

## Getting setup help from AI

If you are unfamiliar with OBS, give this README to ChatGPT, Claude, Gemini or another assistant and ask it to guide you through
the setup one step at a time.

Facts for assistants (please do not contradict these):

- The recommended input is **OBS Virtual Camera**, fed by a scene named `ChestDetectorFeed`.
- `ChestDetectorFeed` must contain **clean Fortnite gameplay only**: no webcam, alerts, chat, or the counter's own text.
- Single-PC users capture Fortnite with OBS **Game Capture** (or Display Capture if Game Capture is black).
- Dual-PC users add their **capture-card source** inside `ChestDetectorFeed` on the **streaming PC**.
- The counter runs on the **streaming / OBS PC**. **Nothing** from this project runs on the gaming PC or console.
- The counter writes text files into its `obs_output` folder; the user adds OBS **Text (GDI+)** sources with **Read from file**.
- **APPROX is the estimated total and already includes CERTAIN.** Never tell the user to add them together.
- The Windows release is a ZIP; the user double-clicks `Start Chest Counter.bat`. **Python is not required** for it.
- Supported Fortnite languages: English and Brazilian Portuguese. Picture must be 16:9 with the normal HUD visible.
- To count a recorded video, drag it onto `Count Video File.bat`. This never changes the live counter.
- Reset with `Reset Counter.bat`. It works while the counter window is open.

## Contents

[Download](#download) · [Quick start](#quick-start) · [Single-PC setup](#single-pc-setup) · [Dual-PC setup](#dual-pc-setup) ·
[Show it on stream](#show-it-on-stream-obs-text-sources) · [Recorded video](#counting-a-recorded-video) ·
[Reset](#reset-and-show) · [Configuration](#configuration-optional) · [Updating](#updating) ·
[Troubleshooting](#troubleshooting) · [Known limitations](#known-limitations) · [How it works](#how-it-works) · [Development](#development)

## Download

1. Open this repository's **Releases** page and download `Fortnite-Visual-Chest-Counter-v0.1.0.zip` (about 107 MB; it includes the
   video helper FFmpeg, so there is nothing else to install). Only the zip is needed; `SHA256SUMS.txt` lets you verify it,
   and the `ffmpeg-source-*.tar.gz` file is the source code of the bundled FFmpeg (for licence compliance, not needed to run).
2. Right-click the ZIP → **Extract All**. Use a normal folder (Desktop or Documents). Do not run it from inside the ZIP or from Program Files.

Extracted folder:

```text
Fortnite Visual Chest Counter.exe   the program (you normally do not open this directly)
Start Chest Counter.bat             <- double-click to count a live OBS feed
Reset Counter.bat                   set both counts to 0
Show Counter.bat                    print the current counts
Count Video File.bat                drag a recorded video onto this file to count it
Diagnostics.bat                     support report if something does not work
README.html                         offline copy of the setup guide
config.example.toml                 optional settings
obs_output\                         text files that OBS reads
state\  logs\                       your counter and logs (kept when you update)
runtime\                            program files (do not touch)
```

Windows may show "Windows protected your PC" because the program is not code-signed: click **More info → Run anyway**.

## Quick start

```text
1. In OBS: create a scene `ChestDetectorFeed` containing only your game.
2. In OBS: set Virtual Camera to Scene -> ChestDetectorFeed, click Start Virtual Camera.
3. Double-click `Start Chest Counter.bat`. Leave the window open and play.
4. In OBS: add two Text (GDI+) sources (Read from file) that point at
   obs_output\certain_chests.txt and obs_output\approximate_chests.txt
```

Details follow.

## Single-PC setup

Data flow:

```text
Fortnite
  -> OBS Game Capture
  -> scene "ChestDetectorFeed"
  -> OBS Virtual Camera
  -> Fortnite Visual Chest Counter
  -> text files in obs_output\
  -> OBS Text sources on your stream scene
```

### Step 1 - Create the detector scene

1. Open OBS Studio (version 28 or newer).
2. In the **Scenes** box click **+** and name the scene exactly `ChestDetectorFeed`.
3. In the **Sources** box click **+** → **Game Capture** → OK. Set *Mode* to *Capture specific window* and choose Fortnite
   (start Fortnite first so it appears in the list). If the preview is black, use **Display Capture** instead.
4. Make Fortnite fill the whole scene: select the source and press `Ctrl+F` (Fit to screen).

Do NOT add to this scene: webcam, alerts, chat, the chest counter text, or other stream graphics.
The detector scene must contain clean Fortnite gameplay only. Use a 16:9 canvas (1920x1080 is ideal).

### Step 2 - Start the Virtual Camera from that scene

1. In OBS, in the **Controls** box (bottom right) click the **gear** next to **Start Virtual Camera**.
2. Set *Output Type* = **Scene** and *Output Selection* = **ChestDetectorFeed**. Close the dialog.
3. Click **Start Virtual Camera**. It now shows as running.

Your stream scene is unaffected. The counter only sees `ChestDetectorFeed`.

### Step 3 - Start the counter

Double-click `Start Chest Counter.bat`. Expected output:

```text
Connected: video 1920x1080 @ 30.0 fps -> analysed at 15 frames per second
Counting has started. Counts are kept when you stop and restart.
LIVE  15.0 detector fps | source 30.0 fps | CERTAIN 0 | APPROX 0 | dropped 0 | 6 ms/frame
```

Leave the window open while you play. Press `Q` in the window (or close it) to stop; numbers are saved after every chest.
If it says `OBS Virtual Camera was not found`, follow the three steps it prints.

### Step 4 - Show the numbers on stream

See [Show it on stream](#show-it-on-stream-obs-text-sources).

## Dual-PC setup

```text
Gaming PC / console
   | HDMI
Capture card
   |
Streaming PC -> OBS -> scene "ChestDetectorFeed" -> Virtual Camera -> Fortnite Visual Chest Counter
```

**Install and run the counter on the streaming PC only. Nothing from this project needs to run on the gaming PC.**

1. On the streaming PC, create the `ChestDetectorFeed` scene in OBS.
2. Add your capture card as a **Video Capture Device** source inside it and make it fill the scene (`Ctrl+F`). Nothing else goes in this scene.
3. Set Virtual Camera to **Scene → ChestDetectorFeed** and click **Start Virtual Camera** (same as Single-PC Step 2).
4. Double-click `Start Chest Counter.bat` (same launcher as everyone else).

**Advanced: direct capture-card mode.** Copy `config.example.toml` to `config.toml`, and under `[live]` set `source = "device"` and
`device = "exact device name"` (run `Diagnostics.bat` to list names). Many capture cards can be opened by only **one** program at a time,
so this usually fails while OBS is using the card; if it does, use the Virtual Camera method.

## Show it on stream (OBS Text sources)

The counter only writes the **text**. You choose font, size and colour in OBS.

1. Open the scene your **viewers** see (not `ChestDetectorFeed`).
2. **Sources → + → Text (GDI+)** → name it → OK.
3. Tick **Read from file**, click **Browse**, choose `obs_output\certain_chests.txt` → style it → OK.
4. Repeat with `obs_output\approximate_chests.txt`.

| File in `obs_output\` | Contains |
|---|---|
| `certain_chests.txt` | `CERTAIN OPENED CHESTS: 12` |
| `approximate_chests.txt` | `APPROX. OPENED CHESTS: 47` |
| `chest_status.txt` | one compact line: `12 certain • ~47 estimated` (use instead of the two above if you want one source) |
| `last_chest.txt` | the most recent chest, e.g. `CHEST +1 • HIGH` |

Numbers above 999 use a thousands separator (`1,232`). Only the counter should write these files.

## Counting a recorded video

Besides live feeds, the counter can analyse a prerecorded gameplay video (`.mp4`, `.mkv`, `.mov`, ...).

1. Drag the video file and drop it **onto** `Count Video File.bat`.
2. Wait. It analyses faster than real time and prints each counted chest plus a progress line every minute of video.
3. At the end it prints `CERTAIN OPENED CHESTS` and `APPROX. OPENED CHESTS` (APPROX includes CERTAIN).

This never touches your live counter. Result text files go to `video_output\`. Command-line equivalent:
`"Fortnite Visual Chest Counter.exe" video "C:\path\to\recording.mp4"`.
The recording should be clean 16:9 gameplay with the normal HUD, in English or Brazilian Portuguese.

## Reset and show

- `Reset Counter.bat` sets both counts to 0 and prints `Counter reset: CERTAIN: 0 / APPROX: 0`. It works while the counter window is open.
  Typical use: start stream → reset → begin challenge.
- `Show Counter.bat` prints the current counts. Closing and reopening the counter does **not** reset it.

## Configuration (optional)

Most people change nothing. To customise, copy `config.example.toml` to `config.toml` (same folder as the `.exe`), edit it in Notepad
(every option is explained inside) and restart the counter. A mistake only prints a warning and the default is used.
Common options: `languages` (`["en"]`, `["pt"]` or both), `certain_min_tier`, `certain_label`, `approximate_label`,
`use_thousands_separator`, `process_fps`, `[logging]`, `[live] source`.

## Updating

Your data is stored next to, not inside, the program files. Keep: `state\` (counts), `config.toml` (settings), `logs\` (optional),
`obs_output\` (re-created automatically). Easiest: close the counter, extract the new ZIP **into the same folder** and replace files.
The ZIP never contains your counts or `config.toml`. Afterwards run `Show Counter.bat` once so the OBS text files show your real numbers
(the ZIP contains blank placeholders). If you extract to a new folder, copy `state\` and `config.toml` and re-point the OBS text sources.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OBS Virtual Camera was not found` | Open OBS Studio 28+, click **Start Virtual Camera**, start the counter again. |
| `exists but is not sending video` | Click **Start Virtual Camera** again; check `ChestDetectorFeed` is not black. |
| Number never changes | Is the picture 16:9 with the HUD visible, and does the chest pop-up ("CHEST" / "BAÚ") appear in `ChestDetectorFeed`? Overlays hiding the HUD break detection. Run `Diagnostics.bat`. |
| `already running in another window` | Only one counter can run at a time; use the open window. |
| OBS text blank / not updating | Text source must have **Read from file** ticked and point at the `obs_output` of the counter you are running. |
| Wrong number | `Reset Counter.bat`, or `"Fortnite Visual Chest Counter.exe" adjust --certain 1 --approx 1` (negative numbers subtract). |
| Anything else | Run `Diagnostics.bat` and paste its output (also in `logs\diagnostics.txt`) when asking for help. A crash writes `logs\crash_*.txt`; include that too. |

## Reporting missed or wrong chests

Accuracy improves fastest with real examples. To help:

1. Copy `config.example.toml` to `config.toml` and set `save_snapshots = true` under `[logging]`.
2. Play or stream as usual. For every pop-up the counter considered, a small picture of the pop-up area is saved in
   `logs\snapshots\<session>\`, named like `E0012_10m48s26_LOW_notcounted.png` (event, time, tier, decision).
3. Note the times of chests it missed or wrongly counted, and send those pictures together with the session's
   `logs\session_*.jsonl` file and the `Diagnostics.bat` output.

Snapshots only contain the pop-up area to the right of the crosshair, not your whole screen. They stay on your PC unless you send them.

## Known limitations

- **APPROX is an estimate** and can be slightly high or low. CERTAIN is the conservative number.
- **Language-specific:** chest detection reads the word in the pop-up. English (CHEST) and Brazilian Portuguese (BAÚ) only for now.
- **HUD layout/scale:** assumes the normal HUD at a 16:9 picture. Moved/scaled/hidden HUD or 4:3 / vertical video will not work well.
- **Clean gameplay feed recommended:** overlays on top of the HUD can hide the clues.
- **Audio is not used** by the live estimator; only the picture is analysed.
- Tested on a limited set of recordings (PC English, PS5 Portuguese, plus a ~20-minute live OBS session). Windows only.

## How it works

The counter samples 15 frames per second (rescaled to 1280x720) and looks for visual clues: the "CHEST"/"BAÚ" XP pop-up, the
"CONTAINER OPENED" tag, the interaction-button prompt with chest-coloured objects near it, and ammo-counter changes that indicate
shooting (which downgrades ambiguous pop-ups of short, less specific words). Clues are merged into one event per chest, each
event gets a confidence tier, and the tier decides whether it adds to CERTAIN + APPROX or to APPROX only. Because stream
compression slightly smears the small pop-up text, a medium-confidence pop-up is also checked with a compression-tolerant
(blurred) glyph match; if that match is strong it is promoted to CERTAIN. Measurements: [docs/ACCURACY_NOTES.md](docs/ACCURACY_NOTES.md). Full research history: [docs/DETECTOR_NOTES.md](docs/DETECTOR_NOTES.md).
All frames are processed in memory with a latest-frame policy (no growing queue); nothing is sent over the network.

## Development

Python 3.11+, FFmpeg on PATH when running from source.

```text
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m fortnite_chest_counter --version
.venv\Scripts\python -m pytest            # or: python tests\test_release.py
```

Layout: `src/fortnite_chest_counter/` (program: `counter.py`, `estimator.py`, `detection/`, `input/`, `templates/`), `tests/`,
`packaging/` (PyInstaller release builder), `docs/`, `research/`. Large recordings (`samples/`) are intentionally not in Git.
See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

[MIT](LICENSE) - free to use, modify and share. The Windows download also bundles FFmpeg (LGPL v3, unmodified; its exact
source is attached to each GitHub release), Python, NumPy, SciPy and the PyInstaller bootloader under their own licenses;
see `packaging/LICENSE-NOTICE.txt`.

Not affiliated with or endorsed by Epic Games. "Fortnite" is a trademark of Epic Games, Inc.
