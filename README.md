# Fortnite Visual Chest Counter

**Automatically count Fortnite chests from gameplay video.**

A free, open-source Windows app that recognises the chest-opening pop-ups visible in Fortnite gameplay and keeps a running
count - from your own stream's OBS feed (single-PC or dual-PC), a capture card, a livestream you watch, or a recorded video.
The numbers go to a text file that an OBS Text source shows on stream, so nobody has to count by hand.

It works only with the picture: it does not need the Fortnite process, read game memory or files, inject code, modify the
game, send input or automate gameplay, and it never reveals anything that is not already on screen (no hidden chests, no
enemy information). See [Fair play and compatibility](#fair-play-and-compatibility).

> Independent, unofficial project: not affiliated with, endorsed by or approved by Epic Games. "Fortnite" is a trademark of
> Epic Games, Inc.
> Status: **v0.2.0 public beta** (desktop app). Chest detection as in v0.1.1, plus English chest pop-ups on streams whose
> HUD is drawn larger (counted in the estimated total). Developed and tested during Fortnite Chapter 7 Season 5 (November
> 2026) - see [Fortnite compatibility](#fortnite-compatibility). Windows 10 / 11. Nothing to install.

## The two numbers (read this first)

| Counter | Meaning |
|---|---|
| **CERTAIN OPENED CHESTS** | Chest openings detected with strong visual evidence. The conservative number. |
| **APPROX. OPENED CHESTS** | Estimated **TOTAL** chest openings, **including** the certain ones. |

Example: `CERTAIN: 42` and `APPROX: 51` means *about 51 chests were opened, 42 of them strongly confirmed*.
**Do NOT add them together** (that would be 93, which is wrong). APPROX is always greater than or equal to CERTAIN.

APPROX is an estimate, not an exact count. See [Known limitations](#known-limitations).

## Fair play and compatibility

The counter is built for statistics and stream presentation: it counts chest openings that are **already visible on
screen**. It gives no competitive information - it does not locate hidden chests, reveal enemies, aim, move or play for you.
It has no connection to Fortnite: it only reads video frames (OBS Virtual Camera, a capture device, a screen capture or a
video file), makes no internet connection, and its one keyboard shortcut (Ctrl+Alt+M, mark a missed chest) is a standard
Windows hotkey that sends nothing to the game.

Epic Games' rules prohibit tools that use real-time gameplay information to gain a competitive advantage. This app is
designed for counting, not for competitive assistance - but Epic does not certify individual third-party applications, and
this one has not been reviewed or approved by Epic. The most conservative ways to use it:

- **Count recorded video** (Dashboard -> Analyse a recording), or
- **run the counter on a separate streaming PC** (dual-PC setup), so nothing from this project runs where Fortnite runs.

Running the counter on the same PC as Fortnite (single-PC OBS setup) works technically, but its compatibility with
Fortnite's anti-cheat has not been officially verified. A dual-PC setup is not a compliance guarantee either; it simply keeps
the counter away from the game. Tournament or event rules can be stricter than normal play - check them if you compete.

## Getting setup help from AI

If you are unfamiliar with OBS, give this README to ChatGPT, Claude, Gemini or another assistant and ask it to guide you through
the setup one step at a time.

Facts for assistants (please do not contradict these):

- The app is **`Fortnite Visual Chest Counter.exe`** in the extracted ZIP folder. It is the only thing the user opens.
  **Python is not required.** There are no `.bat` files any more (v0.1.x had them; v0.2.0 users can delete leftovers).
- The recommended input is **OBS Virtual Camera**, fed by a scene named `ChestDetectorFeed`, chosen in the app's
  **Video source** list (the default). Other entries: capture devices by name and screens ("Screen 2 · 1920 x 1080").
- `ChestDetectorFeed` must contain **clean Fortnite gameplay only**: no webcam, alerts, chat, or the counter's own text.
- Single-PC users capture Fortnite with OBS **Game Capture** (or Display Capture if Game Capture is black).
- Dual-PC users add their **capture-card source** inside `ChestDetectorFeed` on the **streaming PC**.
- The app runs on the **streaming / OBS PC**. **Nothing** from this project runs on the gaming PC or console.
- **Start counting** / **Stop counting** are on the Dashboard. Counts are saved after every chest and kept between sessions.
- OBS shows the numbers with a **Text (GDI+)** source, **Read from file** = `obs_output\chest_counter.txt`. The app's
  **Overlay** page shows that exact path (Copy path button) and chooses what the file says: both numbers on two lines,
  both on one line, estimated total only, or confirmed only; wording with `#` = the number (`#C` / `#A` for one line).
  Changes apply within a second, even while counting. OBS never needs a different file.
- **APPROX is the estimated total and already includes CERTAIN.** Never tell the user to add them together.
- Already opened chests before starting? Dashboard → **Edit counts...** → APPROX = that number, CERTAIN = 0. Reset → 0 / 0.
  Both work while counting.
- Count a recorded video: Dashboard → **Analyse a recording...** (never changes the live counter; results in `video_output\`).
- Supported Fortnite languages: English and Portuguese (Brazil); Settings → **Fortnite language** (English / Portuguese
  (Brazil) / Both; "Both" is not automatic detection). Picture must be 16:9 with the HUD visible. A HUD drawn up to
  about 1.3x larger is recognised for English pop-ups; those chests count in APPROX only.
- Problems: Help & diagnostics → **Run diagnostics** → **Copy report**. Missed chests: Dashboard → **Diagnostic recording** →
  "Only around my marks", then press **Ctrl+Alt+M** right after each miss.
- Advanced settings live in `config.toml` next to the app (Settings → Open config.toml); a wrong value only shows a warning
  and uses the default. Every command also works from a terminal: `runtime\python\python.exe -m fortnite_chest_counter --help`.
- The app only analyses video pixels; it never connects to Fortnite or the internet. It is **not** approved by Epic Games:
  never call it "ban-safe". Most conservative setups: counting recorded video, or the counter on a separate streaming PC.
  Same-PC use works but its anti-cheat compatibility is not officially verified (see Fair play and compatibility).
- v0.2.0's detection was developed and tested during Fortnite Chapter 7 Season 5 (November 2026). A later Fortnite update can
  change the HUD cues it relies on; then the user should open an issue: https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues

## Contents

[Fair play](#fair-play-and-compatibility) · [Download](#download) · [Quick start](#quick-start) · [Single-PC setup](#single-pc-setup) · [Dual-PC setup](#dual-pc-setup) ·
[Other video inputs](#other-video-inputs) · [Show it on stream](#show-it-on-stream-obs-text-source) ·
[Customize what viewers see](#customize-what-viewers-see) · [Activity & live preview](#activity-panel-and-live-preview) ·
[Recorded video](#counting-a-recorded-video) · [Starting count & reset](#starting-count-and-reset) ·
[Help improve accuracy](#help-improve-accuracy-marks-and-diagnostic-recording) · [Settings](#settings) · [Updating](#updating) ·
[Troubleshooting](#troubleshooting) · [Known limitations](#known-limitations) · [How it works](#how-it-works) · [Development](#development)

## Download

1. Open this repository's **Releases** page and download the latest `Fortnite-Visual-Chest-Counter-v….zip` (about 135 MB;
   it includes everything it needs). `SHA256SUMS.txt` lets you verify it, and `ffmpeg-source-*.tar.gz` is the source code of
   the bundled video helper (licence requirement).
2. Right-click the ZIP → **Extract All**. Use a normal folder (Desktop or Documents). Do not run it from inside the ZIP or
   from Program Files.

```text
Fortnite Visual Chest Counter.exe   <- the app: the only thing you open
README.html                         offline copy of the setup guide
config.example.toml                 optional advanced settings
obs_output\                         the text files OBS reads
state\  logs\                       your counter and logs (kept when you update)
runtime\                            program files (official python.org Python, FFmpeg, Qt) - do not touch
```

## Quick start

```text
1. In OBS: create a scene `ChestDetectorFeed` containing only your game.
2. In OBS: set Virtual Camera to Scene -> ChestDetectorFeed, click Start Virtual Camera.
3. Open "Fortnite Visual Chest Counter.exe", keep "OBS Virtual Camera" as the video source, click Start counting.
4. In OBS: add a Text (GDI+) source (Read from file) pointing at obs_output\chest_counter.txt
   (the app's Overlay page shows the exact path and lets you choose what it says).
```

## Single-PC setup

```text
Fortnite -> OBS Game Capture -> scene "ChestDetectorFeed" -> OBS Virtual Camera
         -> Fortnite Visual Chest Counter -> obs_output\chest_counter.txt -> OBS Text source on your stream scene
```

### Step 1 - Create the detector scene

1. Open OBS Studio (version 28 or newer).
2. In the **Scenes** box click **+** and name the scene exactly `ChestDetectorFeed`.
3. In the **Sources** box click **+** → **Game Capture** → OK. Set *Mode* to *Capture specific window* and choose Fortnite
   (start Fortnite first so it appears in the list). If the preview is black, use **Display Capture** instead.
4. Make Fortnite fill the whole scene: select the source and press `Ctrl+F` (Fit to screen).

Do NOT add to this scene: webcam, alerts, chat, the chest counter text, or other stream graphics. Use a 16:9 canvas
(1920x1080 is ideal).

### Step 2 - Start the Virtual Camera from that scene

1. In OBS, in the **Controls** box (bottom right) click the **gear** next to **Start Virtual Camera**.
2. Set *Output Type* = **Scene** and *Output Selection* = **ChestDetectorFeed**. Close the dialog.
3. Click **Start Virtual Camera**. It now shows as running.

Your stream scene is unaffected. The counter only sees `ChestDetectorFeed`.

### Step 3 - Start counting

Open **Fortnite Visual Chest Counter.exe**. On the **Dashboard** the video source is already **OBS Virtual Camera**; click
**Start counting**. The status turns to **Counting** and the line below the source shows the picture size and how many
pictures per second are analysed (about 15). Leave the app open (minimised is fine). Stop with **Stop counting** or by
closing the app (it asks first); numbers are saved after every chest.

If a red message says `OBS Virtual Camera was not found`, follow the steps it shows.

## Dual-PC setup

```text
Gaming PC / console -> HDMI -> capture card -> streaming PC -> OBS -> scene "ChestDetectorFeed" -> Virtual Camera -> the app
```

**Run the app on the streaming PC only. Nothing from this project runs on the gaming PC.**

1. On the streaming PC, create the `ChestDetectorFeed` scene in OBS.
2. Add your capture card as a **Video Capture Device** source inside it and make it fill the scene (`Ctrl+F`).
3. Set Virtual Camera to **Scene → ChestDetectorFeed** and click **Start Virtual Camera** (as in Single-PC Step 2).
4. In the app, keep **OBS Virtual Camera** and click **Start counting**.

## Other video inputs

OBS Virtual Camera is the default, not the only option. Pick another entry in the app's **Video source** list (**Refresh**
after plugging something in); the choice is remembered:

| In the list | Good to know |
|---|---|
| **Screen N** with an **OBS projector**: in OBS right-click your gameplay source → **Fullscreen Projector (Source)** → that monitor | OBS keeps the capture card and the Virtual Camera. Needs a spare **16:9** monitor; keep other windows off it. Projector setup not yet tested. |
| **Capture device: …** (the card directly, no OBS) | Many cards work with only **one** program at a time: close OBS or remove the card from it. Uses the card's default resolution. Not yet tested with physical cards. |

Turn on **Live preview** on the Dashboard to check that the counter sees the game, full screen, with the HUD.

## Show it on stream (OBS Text source)

1. Open the scene your **viewers** see (not `ChestDetectorFeed`).
2. **Sources → + → Text (GDI+)** → name it → OK.
3. Tick **Read from file**, click **Browse**, choose **`obs_output\chest_counter.txt`** (the app's Overlay page shows the exact
   path; **Copy path** puts it on the clipboard) → style it → OK.

That is the only file you ever point OBS at.

## Customize what viewers see

The app's **Overlay** page:

- **What OBS shows:** both numbers on two lines, both on one line, estimated total only, or confirmed chests only - each with
  an example using your current numbers.
- **Wording:** `#` is where the number goes (`Chests opened: #`, `Chest Hunt: #/500`); for one line, `#C` = confirmed and
  `#A` = estimated total. **Original wording** restores the defaults. Any text, symbols and emoji (with an OBS font that has them).
- **Preview** shows exactly what the file will contain; **Apply** updates OBS at once, even while counting.

The app cannot hide a Text source you already added in OBS: if a viewer-facing number looks wrong, that source reads another file.

**Advanced (`config.toml`, `[display]`):** `show = "both" | "certain" | "approx"`, `both_layout = "stacked" | "inline"`,
`certain_text`, `approx_text`, `combined_status_format` (`{count}` = the number; `{certain}`/`{approx}` anywhere; `\n` = new
line; `{{`/`}}` = literal braces), `use_thousands_separator`. For separately styled sources the counter also writes:

| File in `obs_output\` | Contains |
|---|---|
| `chest_counter.txt` | **the one to use:** whatever the Overlay page chose (all four layouts) |
| `chest_status.txt` | legacy: one line with both numbers (or the single number chosen) |
| `certain_chests.txt` | always the confirmed number |
| `approximate_chests.txt` | always the estimated total |
| `last_chest.txt` | the most recent chest, e.g. `CHEST +1 • HIGH` |

## Activity panel and live preview

Both are optional, on the Dashboard, and only for you - showing, hiding or minimising them never changes counting.

- **Activity:** every decision as it happens - **green** = certain chest, **yellow** = counted in APPROX only, **red** = looked
  like a chest pop-up but not counted - with the evidence (`match 0.94 (HIGH)` is the pop-up word match score, not a
  probability) and the reason. **Debug detail** adds every candidate, the full reasoning and status lines.
- **Live preview:** the picture the counter analyses, a few times per second. Off by default; costs nothing while hidden.

Everything is also written to the session log in `logs\`.

## Counting a recorded video

Dashboard → **Analyse a recording...** → choose a `.mp4` / `.mkv` / `.mov` ... → **Start**. It runs faster than real time,
shows progress and every counted chest, and ends with CERTAIN and APPROX (APPROX includes CERTAIN). It never touches your live
counter; result text files go to `video_output\`. Terminal: `runtime\python\python.exe -m fortnite_chest_counter video "C:\path\to\recording.mp4"`.

## Starting count and reset

- **Edit counts...** (Dashboard): already opened chests? Enter the number as APPROX (e.g. `150`) with CERTAIN `0` - the
  counter did not see the earlier chests - and new chests are added on top. Also fixes a wrong count.
- **Reset...** sets both counts to 0. Closing and reopening the app does **not** reset anything.

Both work while counting (the counter picks up the change within a second).

## Help improve accuracy: marks and diagnostic recording

- **Diagnostic recording** (Dashboard, off by default; change it any time, also while counting): **Only around my marks**
  (smallest: a rolling recording, keeps 30 s before / 10 s after each mark), **Around chest decisions and my marks**, or
  **Whole session** (about 10 GB per hour; Settings → **Lossless** = exact replay, about twice that). Each recording gets a
  folder in `captures\` with the video, every decision and a `labels.csv` to note what really happened.
- **Mark a miss:** press **Ctrl+Alt+M** right after it (works while Fortnite has the focus) or click **Mark moment**; a green
  "Marked" line confirms it. Marking needs a recording running, so the button is grey while recording is off.
- **Review captures...** (Settings) replays every capture through the current version of the counter and compares it with the
  live decisions and your labels - so misses become repeatable tests. It shows the capture it is on, the video done and the
  time left. Details: [docs/CAPTURE.md](docs/CAPTURE.md).

Recording never slows down or changes counting; it needs 2 GB of free disk space and stops by itself below 1 GB.

## Settings

The **Settings** page: Fortnite language (English / Portuguese (Brazil) / Both - pick the one your game uses; "Both" checks
both words all the time and is only useful for mixed footage), session logs (and pop-up pictures), diagnostic recording,
and **Remember window size and position** (on by default: the app reopens with the size, place and maximised state it was
closed with; if that place is no longer on any screen it is moved back).
Everything else is in `config.toml` (Settings → Open config.toml; every option is explained inside): `certain_min_tier`,
`count_*_as_approx`, `process_fps`, `[capture]` details. Changes apply the next time you start counting.

## Updating

Your data is stored next to, not inside, the program files: `state\` (counts), `config.toml` (settings), `logs\`,
`captures\`, `obs_output\` (re-created automatically). Easiest: close the app, extract the new ZIP **into the same folder** and
replace files; opening the app writes your real numbers back into the OBS text files. If you extract to a new folder, copy
`state\` and `config.toml` and re-point the OBS Text source.

**Coming from v0.1.x:** delete the old `.bat` and `.cmd` files after extracting. Counts, settings and OBS sources keep working.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OBS Virtual Camera was not found` | Open OBS Studio 28+, click **Start Virtual Camera**, click **Start counting** again. |
| `exists but is not sending video` | Click **Start Virtual Camera** again; check `ChestDetectorFeed` is not black. |
| Number never changes | Turn on **Live preview**: 16:9, full screen, HUD visible? Does the chest pop-up ("CHEST" / "BAÚ") appear in `ChestDetectorFeed`? |
| Virtual Camera already used by something else | Use a **Screen** with an OBS projector, or the capture card directly ([Other video inputs](#other-video-inputs)). |
| `Could not open the video device` | The card is probably in use by OBS: close OBS or remove the card from it, or use the Virtual Camera / a projector. |
| `already running` / `already open` | Only one counter runs at a time; use the open one (taskbar). |
| OBS text blank / not updating | The Text source must have **Read from file** ticked and point at the file shown on the Overlay page. |
| It missed / miscounted chests | Diagnostic recording + **Ctrl+Alt+M** ([Help improve accuracy](#help-improve-accuracy-marks-and-diagnostic-recording)); share the `captures\` folder of that session. |
| Anything else | Help & diagnostics → **Run diagnostics** → **Copy report** (also saved to `logs\diagnostics.txt`); include any `logs\crash_*.txt`. |

## Fortnite compatibility

The chest detection in v0.2.0 is the one developed and live-tested during **Fortnite Chapter 7 Season 5** (November 2026);
its automated tests also use recordings of earlier gameplay. It recognises Fortnite's on-screen chest pop-up and HUD
elements, which Epic Games can change in any update. If chests stop being counted after an update, please
[open an issue](https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues) with the diagnostics report and, if you
can, a diagnostic capture.

## Known limitations

- **APPROX is an estimate** and can be slightly high or low. CERTAIN is the conservative number.
- **Language-specific:** chest detection reads the word in the pop-up: English (CHEST) and Portuguese (Brazil) (BAÚ) only.
  Special chests whose pop-up says something else (e.g. Sprite Chests) are not counted as chests yet.
- **HUD layout/scale:** assumes a 16:9 picture with the HUD in its usual place. A HUD drawn larger (up to about 1.3x) is
  recognised for **English** pop-ups only, and those chests count in **APPROX only**, never CERTAIN. A smaller, moved or
  hidden HUD, Portuguese pop-ups on a larger HUD, and 4:3 / vertical video will not work well.
- **Back-to-back chests on a larger-HUD stream** (the second opened while the first pop-up is still showing) can count
  as one - never as two for one chest.
- **Clean gameplay feed recommended:** overlays on top of the HUD can hide the clues.
- **Audio is not used**; only the picture is analysed.
- Tested on a limited set of recordings (PC English, PS5 Portuguese, their stream-compressed versions, three diagnostic
  recordings of streams with a larger HUD) plus live sessions.
  Direct capture-card input is untested on physical cards. Windows only.

## How it works

The app is a window around a separate counting process (the same engine the console version runs), so the window can never
slow counting down. The counter samples 15 frames per second (rescaled to 1280x720) and looks for visual clues: the
"CHEST"/"BAÚ" XP pop-up, the "CONTAINER OPENED" tag, the interaction-button prompt with chest-coloured objects near it, and
ammo-counter changes that indicate shooting (which downgrades ambiguous pop-ups of short, less specific words). Clues are
merged into one event per chest, each event gets a confidence tier, and the tier decides whether it adds to CERTAIN + APPROX
or to APPROX only. Because stream compression slightly smears the small pop-up text, a medium-confidence pop-up is also
checked with a compression-tolerant (blurred) glyph match; if that match is strong it is promoted to CERTAIN. Some streams
draw the HUD larger, so the English word no longer matches at its normal size: when the pop-up area is lit but the normal
match finds nothing, the counter also tries the blurred match at a few smaller picture scales. Such a chest counts in
APPROX only, and never when the normal match already found that pop-up. Measurements:
[docs/ACCURACY_NOTES.md](docs/ACCURACY_NOTES.md). Research history: [docs/DETECTOR_NOTES.md](docs/DETECTOR_NOTES.md).
All frames are processed in memory with a latest-frame policy (no growing queue); nothing is sent over the network.

## Development

Python 3.11+, FFmpeg on PATH when running from source.

```text
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m fortnite_chest_counter.gui      # the app
.venv\Scripts\python -m fortnite_chest_counter --help   # the command line (live, video, review, configure, ...)
.venv\Scripts\python tests\test_release.py ; .venv\Scripts\python tests\test_app.py
```

Layout: `src/fortnite_chest_counter/` (`counter.py` engine + commands, `estimator.py`, `detection/`, `input/`, `gui/` app,
`capture.py` + `review.py` diagnostic capture, `templates/`), `tests/`, `packaging/` (release builder + launcher source),
`docs/`, `research/`. Large recordings (`samples/`) are intentionally not in Git. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md);
plans: [docs/ROADMAP.md](docs/ROADMAP.md).

## License

[MIT](LICENSE) - free to use, modify and share. The Windows download also bundles FFmpeg (LGPL v3, unmodified; its exact
source is attached to each GitHub release), Qt for Python / Qt (LGPL v3, unmodified), the official python.org Python runtime,
NumPy and SciPy under their own licenses; see `packaging/LICENSE-NOTICE.txt`.

Not affiliated with or endorsed by Epic Games. "Fortnite" is a trademark of Epic Games, Inc.
