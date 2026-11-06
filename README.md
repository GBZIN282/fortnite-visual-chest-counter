# Fortnite Visual Chest Counter

**Visual chest detection for OBS, capture cards & video files.**

Computer-vision Fortnite chest counter for live OBS / capture-card feeds and prerecorded gameplay. It watches gameplay
**pixels** and estimates how many chests have been opened, then writes the numbers to text files that an OBS Text source can
show on stream.

It does **not** read Fortnite memory, use any Fortnite API, modify the game, inject code or automate gameplay.

> Not affiliated with or endorsed by Epic Games. "Fortnite" is a trademark of Epic Games, Inc.
> Status: **v0.1.1 public beta**, developed and tested during Fortnite Chapter 7 Season 5 (November 2026) -
> see [Fortnite compatibility](#fortnite-compatibility). Windows only. Nothing to install.

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
  `chest_counter.txt` is the single easiest file; `certain_chests.txt` / `approximate_chests.txt` hold one number each.
- **APPROX is the estimated total and already includes CERTAIN.** Never tell the user to add them together.
- The Windows release is a ZIP; the user double-clicks `Start Chest Counter.bat`. **Python is not required** for it.
- Supported Fortnite languages: English and Brazilian Portuguese. Picture must be 16:9 with the normal HUD visible.
- v0.1.1 was developed and tested during Fortnite Chapter 7 Season 5 (November 2026). A later Fortnite update can change
  the HUD cues it relies on; if counting stops working after an update, the user should open an issue: https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues
- To count a recorded video, drag it onto `Count Video File.bat`. This never changes the live counter.
- Reset with `Reset Counter.bat`. It works while the counter window is open.
- Already opened chests before starting? `Set Starting Count.bat` asks "How many chests have you already opened?" and sets
  APPROX to that number with CERTAIN = 0 (earlier chests were not seen by the detector); new chests are added on top. Reset
  always means 0 / 0. Command line: `"Fortnite Visual Chest Counter.cmd" set-count 150`.
- All settings are optional and go in `config.toml` (a copy of `config.example.toml`, next to the `.exe`). Restart the
  counter after saving. A wrong value only prints a `WARNING` and uses the default; nothing can break the counting.
- What viewers see (`[display]`, v0.1.1+): `show = "both" | "certain" | "approx"` decides what `chest_counter.txt` shows;
  `certain_text` / `approx_text` are free text where `{count}` is the number (`{certain}` and `{approx}` also work);
  `\n` makes a new line; `{{` / `}}` are literal braces. Example: `approx_text = "Chest Hunt: {count}/500"`.
  The counter cannot hide a Text source the user added in OBS: to stop showing a number, hide that source in OBS or use
  `chest_counter.txt` with `show`. Deleting the changed lines restores the defaults.
- The counter window (`[console]`, v0.1.1+): `verbosity = "minimal" | "normal" | "debug"`, `colors = true | false`.
  Green = certain chest, yellow = APPROX-only chest, red = not counted, white on red = error. `match 0.94` is the pop-up word
  match score, not a probability. These settings never change counting or the logs.
- OBS Virtual Camera is the default, **not** the only option. If the user's Virtual Camera is already used for something else,
  use the [other video inputs](#other-video-inputs-without-obs-virtual-camera): an OBS fullscreen projector on a second
  monitor (`source = "desktop"`) or the capture card directly (`source = "device"`). Both are set in `config.toml`; there is
  no source picker yet. Direct capture-card mode has not yet been tested with physical capture hardware.

## Choose your video input

The counter needs to *see* your gameplay. Pick the first option that fits you:

| | Option | Best for | Needs | Status |
|---|---|---|---|---|
| 1 | **OBS Virtual Camera** (default) | most OBS users, single PC or capture card | OBS 28+, Virtual Camera free to use | tested, recommended |
| 2 | **OBS projector on a second monitor** | your Virtual Camera is already used for something else | a spare 16:9 monitor | uses the tested desktop mode; projector setup not yet tested |
| 3 | **Capture card directly** | dual-PC setups where OBS does not need the card at the same time | your capture card | advanced, not yet tested on real cards |
| 4 | **Recorded video** | counting chests in a video file afterwards | the video file | tested |

- Options 1 and 2 never open your capture card a second time, so they cannot disturb OBS.
- Option 3 can conflict with OBS: many capture cards work with only **one** program at a time.
- Options 2 and 3 are switched on by editing one small settings file (steps below). A one-click source picker is planned
  for the next version.

Setup: option 1 → [Single-PC setup](#single-pc-setup) / [Dual-PC setup](#dual-pc-setup) · options 2 and 3 →
[Other video inputs](#other-video-inputs-without-obs-virtual-camera) · option 4 → [Recorded video](#counting-a-recorded-video).

## Contents

[Download](#download) · [Quick start](#quick-start) · [Single-PC setup](#single-pc-setup) · [Dual-PC setup](#dual-pc-setup) ·
[Other video inputs](#other-video-inputs-without-obs-virtual-camera) ·
[Customize what viewers see](#customize-what-viewers-see) · [The counter window](#the-counter-window-colours-and-detail) ·
[Show it on stream](#show-it-on-stream-obs-text-sources) · [Recorded video](#counting-a-recorded-video) ·
[Starting count & reset](#starting-count-reset-and-show) · [Configuration](#configuration-optional) · [Updating](#updating) ·
[Troubleshooting](#troubleshooting) · [Known limitations](#known-limitations) · [How it works](#how-it-works) · [Development](#development)

## Download

1. Open this repository's **Releases** page and download the latest `Fortnite-Visual-Chest-Counter-v….zip` (about 120 MB;
   it includes everything it needs, so there is nothing else to install). Only the zip is needed: `SHA256SUMS.txt` lets you
   verify it, and `ffmpeg-source-*.tar.gz` is the source code of the bundled video helper (licence requirement).
2. Right-click the ZIP → **Extract All**. Use a normal folder (Desktop or Documents). Do not run it from inside the ZIP or from Program Files.

Extracted folder:

```text
Start Chest Counter.bat             <- double-click to count a live OBS feed
Set Starting Count.bat              enter the chests you have already opened
Reset Counter.bat                   set both counts to 0
Show Counter.bat                    print the current counts
Count Video File.bat                drag a recorded video onto this file to count it
Diagnostics.bat                     support report if something does not work
Fortnite Visual Chest Counter.cmd   command-line entry for advanced use (you normally do not need it)
README.html                         offline copy of the setup guide
config.example.toml                 optional settings
obs_output\                         text files that OBS reads
state\  logs\                       your counter and logs (kept when you update)
runtime\                            program files (do not touch)
```

The program runs on the official Python runtime from python.org, included in `runtime\` (nothing to install).

## Quick start

```text
1. In OBS: create a scene `ChestDetectorFeed` containing only your game.
2. In OBS: set Virtual Camera to Scene -> ChestDetectorFeed, click Start Virtual Camera.
3. Double-click `Start Chest Counter.bat`. Leave the window open and play.
4. In OBS: add a Text (GDI+) source (Read from file) that points at
   obs_output\chest_counter.txt   (shows both numbers; one number or your own words: see "Customize")
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

Is your Virtual Camera already used for something else, or do you want the counter to read the card without OBS? See
[Other video inputs](#other-video-inputs-without-obs-virtual-camera).

## Other video inputs (without OBS Virtual Camera)

Both options below are chosen in a small settings file, `config.toml`. Creating it takes a minute:

1. In the counter folder, copy `config.example.toml` and rename the copy to **`config.toml`**.
   (If Windows hides file extensions, the copy may show as `config.example - Copy`; rename it to `config` and check it is a
   "TOML file".)
2. Open `config.toml` with **Notepad**. Near the bottom, find the `[live]` section.
3. Change the lines shown below, save, and start the counter with `Start Chest Counter.bat` as usual.

The counter prints what it connected to (for example `Connected: video 1920x1080 @ 30.0 fps`), so you can see at once
whether it worked. To go back to the Virtual Camera, set `source = "obs-camera"` again (or delete `config.toml`).

### Option 2: OBS projector on a second monitor

Uses the gameplay OBS already shows. OBS keeps the capture card and the Virtual Camera; nothing is opened twice.

1. In OBS, in the **Sources** list of your stream scene, right-click your **gameplay source** (Game Capture or Video Capture
   Device) → **Fullscreen Projector (Source)** → choose your second monitor. That monitor now shows only the gameplay.
2. Run `Diagnostics.bat`. The `Monitors:` line lists your monitors in the counter's order, e.g. `2560x1440, 1920x1080`:
   the first one is monitor `1`, the second is `2`.
3. In `config.toml`, under `[live]`:

   ```toml
   [live]
   source = "desktop"
   monitor = 2
   ```

- Use a **16:9 monitor** (1920x1080, 2560x1440, ...). An ultrawide monitor would squash the picture.
- The counter reads exactly what that monitor shows: keep other windows and notifications off it. The mouse pointer is ignored.
- Close the projector with `Esc` (or right-click → Close) when you are done.

### Option 3: Capture card directly

The counter opens the capture card itself, without OBS. **Not yet tested with physical capture cards** - please report how it
works with yours.

1. Connect the card and check that Windows recognises it (for example it appears in the Windows Camera app or in OBS).
2. **Close OBS, or remove the card from OBS** (see the warning below).
3. Run `Diagnostics.bat`. The `Video devices:` line lists the device names, e.g. `OBS Virtual Camera, Elgato HD60 X`.
   It is also saved in `logs\diagnostics.txt`: **copy the name from there** rather than typing it (some names contain
   look-alike letters).
4. In `config.toml`, under `[live]`:

   ```toml
   [live]
   source = "device"
   device = "Elgato HD60 X"
   ```

   Replace `Elgato HD60 X` with your exact device name, keeping the quotes.

Good to know:

- **OBS and the counter usually cannot use the same capture card at the same time.** Whether a card can be shared depends on
  the card and its driver. If OBS already uses the card, the counter reports `Could not open the video device`; if the counter
  opened it first, OBS may show a black picture. If you need the card in OBS while streaming, use option 1 or 2 instead.
- The counter uses the card's **default resolution and frame rate**; it cannot choose them yet. If it reports a resolution
  below 1280x720 (`WARNING: the video is only ...`), detection may be weaker; option 1 or 2 avoids this because OBS sets the
  resolution.
- Two identical cards show the same name and cannot be told apart yet.

## Show it on stream (OBS Text sources)

The counter only writes the **text**. You choose font, size and colour in OBS.

1. Open the scene your **viewers** see (not `ChestDetectorFeed`).
2. **Sources → + → Text (GDI+)** → name it → OK.
3. Tick **Read from file**, click **Browse**, choose `obs_output\chest_counter.txt` → style it → OK.

That one source shows both numbers on two lines. Want only one number, or different words? See
[Customize what viewers see](#customize-what-viewers-see). You can also use one source per number:

| File in `obs_output\` | Contains (default text) |
|---|---|
| `chest_counter.txt` | **the easiest choice:** both numbers, or only one ([`show`](#customize-what-viewers-see) setting) |
| `certain_chests.txt` | `CERTAIN OPENED CHESTS: 12` |
| `approximate_chests.txt` | `APPROX. OPENED CHESTS: 47` |
| `chest_status.txt` | one compact line: `12 certain • ~47 estimated` |
| `last_chest.txt` | the most recent chest, e.g. `CHEST +1 • HIGH` |

Numbers above 999 use a thousands separator (`1,232`). Only the counter should write these files; their names never change,
so OBS sources you add keep working after updates.

## Customize what viewers see

All of this is optional and lives in `config.toml` under `[display]` (copy `config.example.toml` to `config.toml` first;
see [Other video inputs](#other-video-inputs-without-obs-virtual-camera) for how). Save the file and restart the counter.

- `show` decides what `chest_counter.txt` shows: `"both"` (default), `"certain"` or `"approx"`.
- `certain_text` and `approx_text` are your own wording. `{count}` is where the number goes. `{certain}` and `{approx}`
  also work anywhere. Any text, symbols and emoji are allowed (emoji need a font in OBS that has them).
- **The counter cannot hide a Text source you already added in OBS.** To stop showing a number, hide or delete that source
  in OBS, or use `chest_counter.txt` and change `show`.

| I want... | Put this under `[display]` |
|---|---|
| Only the estimated total | `show = "approx"` |
| Only the confirmed chests | `show = "certain"` |
| My own words | `approx_text = "Chests opened: {count}"` |
| A goal | `approx_text = "Chest Hunt: {count}/500"` |
| Both numbers in one line | `show = "approx"` and `approx_text = "Chests: ~{approx} ({certain} confirmed)"` |
| The word and the number on separate lines | `approx_text = "CHESTS\n{count}"` |
| No thousands separator (1232) | `use_thousands_separator = false` |
| The original text back | delete the lines you changed (or the whole `config.toml`) |

A typo never breaks the counter: it prints a `WARNING` naming the setting and uses the default text instead.
For a literal `{` or `}` write `{{` or `}}`. (Settings from v0.1.0, `certain_label` / `approximate_label`, still work.)

**Ask your AI assistant:** paste your `config.toml` and say, for example, *"Show only the estimated chests and call it
My Chest Hunt"*. The facts in [Getting setup help from AI](#getting-setup-help-from-ai) tell it which settings exist.

## The counter window (colours and detail)

The black window shows each decision as it happens:

```text
21:42:11  [CERTAIN] chest +1    CERTAIN   20 | APPROX  231  match 0.94 (HIGH)
21:42:19  [APPROX ] chest ~+1   CERTAIN   20 | APPROX  232  match 0.78 (MEDIUM)
21:42:26  [REJECT ] not counted CERTAIN   20 | APPROX  232  match 0.77 (LOW) - shooting at the same moment
21:42:30  [STATUS ]  15.0 fps (source 30.0) | dropped 0 | 6 ms/frame | CERTAIN 20 | APPROX 232
```

**Green** = certain chest · **yellow** = counted in APPROX only · **red** = looked at but not counted ·
**white on red** = an error that needs your attention · **cyan** = status. `match` is how closely the pop-up word matched
(0 to 1); it is evidence, not a percentage or a probability.

| Under `[console]` | Effect |
|---|---|
| `verbosity = "minimal"` | only counted chests, warnings and errors |
| `verbosity = "normal"` | default: also rejected pop-ups and a status line every few seconds |
| `verbosity = "debug"` | everything, with the full reason for each decision (handy when reporting a problem) |
| `colors = false` | plain white text (colours also switch off by themselves if the window cannot show them) |

These settings only change the window. Counting and the logs in `logs\` are always the same.

## Counting a recorded video

Besides live feeds, the counter can analyse a prerecorded gameplay video (`.mp4`, `.mkv`, `.mov`, ...).

1. Drag the video file and drop it **onto** `Count Video File.bat`.
2. Wait. It analyses faster than real time and prints each counted chest plus a progress line every minute of video.
3. At the end it prints `CERTAIN OPENED CHESTS` and `APPROX. OPENED CHESTS` (APPROX includes CERTAIN).

This never touches your live counter. Result text files go to `video_output\`. Command-line equivalent:
`"Fortnite Visual Chest Counter.cmd" video "C:\path\to\recording.mp4"`.
The recording should be clean 16:9 gameplay with the normal HUD, in English or Brazilian Portuguese.

## Starting count, reset and show

- **`Set Starting Count.bat`** - already opened chests before using the counter? Double-click it, type the number
  (for example `150`) and press Enter. APPROX becomes 150 and new chests are added on top. CERTAIN starts at 0, because the
  counter did not see those earlier chests. A wrong entry (negative, decimals, letters, more than 1,000,000) is refused and
  nothing changes; pressing Enter on an empty line cancels. It works while the counter window is open.
- **`Reset Counter.bat`** - sets both counts to 0. Typical use: start stream → reset → begin challenge. It works while the
  counter window is open.
- **`Show Counter.bat`** - prints the current counts. Closing and reopening the counter does **not** reset it.

Command-line equivalents (for scripts or an AI assistant): `"Fortnite Visual Chest Counter.cmd" set-count 150`,
`... reset`, `... show`.

## Configuration (optional)

Most people change nothing. To customise, copy `config.example.toml` to `config.toml` (same folder as the `.exe`), edit it in Notepad
(every option is explained inside) and restart the counter. A mistake only prints a warning and the default is used.
Common options: `[display]` wording and what to show ([details](#customize-what-viewers-see)), `[console]` colours and
detail ([details](#the-counter-window-colours-and-detail)), `[live] source` ([video inputs](#choose-your-video-input)),
`languages` (`["en"]`, `["pt"]` or both), `certain_min_tier`, `process_fps`, `[logging]`.

## Updating

Your data is stored next to, not inside, the program files. Keep: `state\` (counts), `config.toml` (settings), `logs\` (optional),
`obs_output\` (re-created automatically). Easiest: close the counter, extract the new ZIP **into the same folder** and replace files.
The ZIP never contains your counts or `config.toml`. Afterwards run `Show Counter.bat` once so the OBS text files show your real numbers
(the ZIP contains blank placeholders). If you extract to a new folder, copy `state\` and `config.toml` and re-point the OBS text sources.

**Coming from v0.1.0:** after extracting, delete the old `Fortnite Visual Chest Counter.exe` from the folder (v0.1.1 starts
from the `.bat` files and no longer has an `.exe`). Your counts, settings and OBS sources keep working.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OBS Virtual Camera was not found` | Open OBS Studio 28+, click **Start Virtual Camera**, start the counter again. |
| `exists but is not sending video` | Click **Start Virtual Camera** again; check `ChestDetectorFeed` is not black. |
| Number never changes | Is the picture 16:9 with the HUD visible, and does the chest pop-up ("CHEST" / "BAÚ") appear in `ChestDetectorFeed`? Overlays hiding the HUD break detection. Run `Diagnostics.bat`. |
| My Virtual Camera is already used by something else | Use the [OBS projector on a second monitor](#option-2-obs-projector-on-a-second-monitor) or the [capture card directly](#option-3-capture-card-directly). |
| `Could not open the video device` (capture card mode) | The name must match `Diagnostics.bat` exactly (copy it from `logs\diagnostics.txt`). Most often the card is **in use by OBS**: close OBS or remove the card from it, or use option 1 or 2. Also check the card is plugged in and shows a picture in the Windows Camera app. |
| Capture card is missing from `Video devices:` | Reconnect it, install the maker's driver if it needs one, restart the PC, and run `Diagnostics.bat` again. |
| OBS shows a black picture from the card while the counter runs | The counter has the card. Stop the counter, or switch the counter to option 1 or 2 so only OBS opens the card. |
| `WARNING: the video is only 960x540` (or another size below 1280x720) | The capture card's default mode is low; the counter cannot change it yet. Use option 1 or 2, where OBS sets the resolution. |
| `WARNING: ... not 16:9` | The picture is the wrong shape (e.g. an ultrawide monitor in option 2). Use a 16:9 monitor or scene. |
| `monitor 3 not found` | Use a number from the `Monitors:` line of `Diagnostics.bat` (1 = first entry). |
| `already running in another window` | Only one counter can run at a time; use the open window. |
| OBS text blank / not updating | Text source must have **Read from file** ticked and point at the `obs_output` of the counter you are running. |
| Wrong number | `Set Starting Count.bat` to enter the right total, `Reset Counter.bat` for 0, or for small fixes `"Fortnite Visual Chest Counter.cmd" adjust --certain 1 --approx 1` (negative numbers subtract). |
| Anything else | Run `Diagnostics.bat` and paste its output (also in `logs\diagnostics.txt`) when asking for help. A crash writes `logs\crash_*.txt`; include that too. |

## Reporting missed or wrong chests

Accuracy improves fastest with real examples. To help:

1. Copy `config.example.toml` to `config.toml` and set `save_snapshots = true` under `[logging]`.
2. Play or stream as usual. For every pop-up the counter considered, a small picture of the pop-up area is saved in
   `logs\snapshots\<session>\`, named like `E0012_10m48s26_LOW_notcounted.png` (event, time, tier, decision).
3. Note the times of chests it missed or wrongly counted, and send those pictures together with the session's
   `logs\session_*.jsonl` file and the `Diagnostics.bat` output.

Snapshots only contain the pop-up area to the right of the crosshair, not your whole screen. They stay on your PC unless you send them.

## Fortnite compatibility

Fortnite Visual Chest Counter v0.1.1 was developed and live-tested during **Fortnite Chapter 7 Season 5** (November 2026);
its automated tests also use recordings of earlier gameplay. It recognises Fortnite's on-screen chest pop-up and HUD
elements, which Epic Games can change in any update. If chests stop being counted after a Fortnite update, please
[open an issue](https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues) with the `Diagnostics.bat` output and, if you can, a snapshot (`save_snapshots = true`).

## Known limitations

- **APPROX is an estimate** and can be slightly high or low. CERTAIN is the conservative number.
- **Language-specific:** chest detection reads the word in the pop-up. English (CHEST) and Brazilian Portuguese (BAÚ) only for now.
- **HUD layout/scale:** assumes the normal HUD at a 16:9 picture. Moved/scaled/hidden HUD or 4:3 / vertical video will not work well.
- **Clean gameplay feed recommended:** overlays on top of the HUD can hide the clues.
- **Audio is not used** by the live estimator; only the picture is analysed.
- Tested on a limited set of recordings (PC English, PS5 Portuguese) plus several hours of live Twitch/OBS sessions. Windows only.
- **Video inputs:** no source picker yet (options 2 and 3 are set in `config.toml`); direct capture-card mode is untested on
  physical cards, uses the card's default resolution, and may not work while OBS uses the same card.

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
`packaging/` (release builder), `docs/`, `research/`. Large recordings (`samples/`) are intentionally not in Git.
See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Planned work: [docs/ROADMAP.md](docs/ROADMAP.md); video-input research:
[docs/INPUT_OPTIONS.md](docs/INPUT_OPTIONS.md).

## License

[MIT](LICENSE) - free to use, modify and share. The Windows download also bundles FFmpeg (LGPL v3, unmodified; its exact
source is attached to each GitHub release), the official python.org Python runtime, NumPy and SciPy under their own licenses;
see `packaging/LICENSE-NOTICE.txt`.

Not affiliated with or endorsed by Epic Games. "Fortnite" is a trademark of Epic Games, Inc.
