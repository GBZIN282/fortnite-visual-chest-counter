# Fortnite Visual Chest Counter

**Automatically count Fortnite chests from gameplay video.**

A free, open-source Windows app that recognises the chest-opening pop-ups visible in Fortnite gameplay and keeps a running
count - from a Twitch or YouTube livestream link, anything shown on a screen, your own stream's OBS feed (single-PC or
dual-PC), a capture card, or a recorded video. The numbers go to a text file that an OBS Text source can show on stream, so
nobody has to count by hand.

The app works entirely through video analysis, without directly interacting with Fortnite. It does not access game memory
or files, inject code, modify the game, or simulate player inputs. It simply analyses what is already visible on screen,
without revealing hidden information or providing gameplay assistance. See
[Fair play and compatibility](#fair-play-and-compatibility).

> **Two PCs, no capture card required — tested.** Use OBS's built-in SRT support to send gameplay video from your gaming
> PC to a second PC running Fortnite Visual Chest Counter. Successfully tested with v0.2.0 on November 7, 2026, with
> numerous chests counted and no noticeable lag. **[Dual-PC SRT setup guide](docs/guides/obs-dual-pc-srt.md)**

> Independent, unofficial project: not affiliated with, endorsed by or approved by Epic Games. "Fortnite" is a trademark of
> Epic Games, Inc.
> Status: **v0.2.3 public beta** (desktop app). Developed and tested during Fortnite Chapter 7 Season 5 (November 2026) -
> see [Fortnite compatibility](#fortnite-compatibility). Windows 10 / 11. Nothing to install.

**Contents:** [The two numbers](#the-two-numbers-read-this-first) · [Download](#download) · [Choose your setup](#choose-your-setup) ·
[Quick start](#quick-start) · [Show it on stream](#show-it-on-stream) · [Using the app](#using-the-app) ·
[Fair play](#fair-play-and-compatibility) · [Updating](#updating) · [Troubleshooting](#troubleshooting) ·
[Known limitations](#known-limitations) · [Setup help from AI](#getting-setup-help-from-ai) · [How it works](#how-it-works) ·
[Development](#development)

## The two numbers (read this first)

| Counter | Meaning |
|---|---|
| **CERTAIN OPENED CHESTS** | Chest openings detected with strong visual evidence. The conservative number. |
| **APPROX. OPENED CHESTS** | Estimated **TOTAL** chest openings, **including** the certain ones. |

Example: `CERTAIN: 42` and `APPROX: 51` means *about 51 chests were opened, 42 of them strongly confirmed*.
**Do NOT add them together** (that would be 93, which is wrong). APPROX is always greater than or equal to CERTAIN.

APPROX is an estimate, not an exact count. See [Known limitations](#known-limitations).

## Download

1. Open the [**Releases** page](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases) and download the latest
   `Fortnite-Visual-Chest-Counter-v….zip` (about 155 MB; it includes everything it needs). `SHA256SUMS.txt` lets you verify
   it, and `ffmpeg-source-*.tar.gz` is the source code of the bundled video helper (licence requirement).
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

## Choose your setup

Pick what you want to count - most people need one of the first two, which need no OBS at all. Step-by-step guides:

| What you want to count | Guide | Tested |
|---|---|---|
| A **Twitch or YouTube livestream** - paste the link | [Livestream URL](docs/guides/livestream-url.md) | **Yes** - incl. a 3-hour session (~500 chests), 2026-11-08 |
| Anything **on a screen** - a stream or video playing fullscreen, or your own game | [Screen](docs/guides/screen-capture.md) | **Yes** - 2026-11-08 |
| **Your own stream**, Fortnite and OBS on one PC | [Single PC with OBS](docs/guides/obs-single-pc.md) | Yes |
| **Gaming PC + streaming PC** on the same network, no capture card | [Dual PC over the network (SRT)](docs/guides/obs-dual-pc-srt.md) | **Yes** - 2026-11-07, v0.2.0 |
| A **video file** | [Recorded video](docs/guides/recorded-video.md) | Yes |
| **Console or gaming PC + capture card** + streaming PC | [Capture card](docs/guides/capture-card.md) | *Less tested:* counter side yes; not yet with a physical card |
| Capture card **owned by OBS** and **Virtual Camera used by another program** | [OBS projector window](docs/guides/obs-projector.md) | *Less tested:* window capture yes; not yet with a real OBS projector |

Then [show the numbers on stream](docs/guides/obs-overlay.md) - from the text file, or instantly through OBS's built-in
WebSocket (optional). Virtual Camera already used by another program? Read your gameplay from an
[OBS projector window](docs/guides/obs-projector.md).

## Quick start

Open **`Fortnite Visual Chest Counter.exe`**, then pick the **Video source**:

```text
A livestream:   Livestream URL -> paste the link (https://www.twitch.tv/CHANNEL or a YouTube live link) -> Start counting
A screen:       play the stream, video or game FULLSCREEN -> pick that Screen -> Start counting
Your own OBS:   in OBS make a scene `ChestDetectorFeed` with only your game, Virtual Camera gear -> Output Type: Scene ->
                ChestDetectorFeed -> Start Virtual Camera; in the app pick "OBS Virtual Camera" -> Start counting
```

Want the numbers on stream? In OBS add a Text (GDI+) source (Read from file) pointing at `obs_output\chest_counter.txt` (the
app's Overlay page shows the exact path and lets you choose what it says).

The counter needs **clean Fortnite gameplay**: 16:9, HUD visible, nothing covering the chest pop-up right of the crosshair.
Every click explained: [setup guides](docs/guides/README.md).

## Show it on stream

In the scene your viewers see: **Sources → + → Text (GDI+)** → tick **Read from file** → choose
**`obs_output\chest_counter.txt`** (the app's **Overlay** page shows the exact path, with **Copy path**). That is the only file
OBS ever needs. The Overlay page chooses what it says - both numbers on two lines or one line, estimated total only, or
confirmed only - and your own wording; changes apply within a second, even while counting.
Details and the other files: [overlay guide](docs/guides/obs-overlay.md).

## Using the app

- **Dashboard:** both numbers, the video source list (OBS Virtual Camera, capture devices, screens; **Refresh** after
  plugging something in) and **Start counting** / **Stop counting**. Counts are saved after every chest and kept between
  sessions.
- **Activity and Live preview** (optional, only for you): every decision as it happens - **green** = certain chest,
  **yellow** = counted in APPROX only, **red** = looked like a chest pop-up but not counted - with the reason, and the
  picture the counter analyses. Showing, hiding or minimising them never changes counting.
- **Edit counts... / Reset...:** already opened chests? Enter the number as APPROX with CERTAIN `0`; new chests are added on
  top. Reset sets both to 0. Both work while counting; closing the app never resets anything.
- **Profiles** (v0.2.2): one per person you count, for example one per streamer. Each profile keeps its own counts and its
  own video source (such as that streamer's Twitch link). **New profile...**, **Rename...** and **Delete...** sit above the
  numbers; a deleted profile's counts are kept in `state\profiles\deleted\`. One profile counts at a time, and the OBS text
  file always shows the selected profile. Counts from earlier versions become the **Default** profile.
- **Chest types** (v0.2.2): the line under the numbers splits the APPROX total by the pop-up's wording - **Chest**, **Rare
  chest**, **Sprite chest**, or **Unknown type** when the line could not be read reliably (a chest is never guessed to be a
  normal one). It is a label only: CERTAIN and APPROX are counted exactly as before, and OBS still shows only the two
  totals. Chests counted before v0.2.2, or set with **Edit counts...**, are listed as *not classified*. Each profile keeps its
  own split; **Reset...** clears it.
- **Analyse a recording...:** count a video file, faster than real time; never changes the live counter
  ([guide](docs/guides/recorded-video.md)).
- **Diagnostic recording and Ctrl+Alt+M:** optional - keep the video around a missed chest (press **Ctrl+Alt+M** or **Mark
  moment** right after it), then **Review captures** (Settings) replays it through the current counter. Recording never
  slows counting; it needs 2 GB free and stops by itself below 1 GB. Details: [docs/CAPTURE.md](docs/CAPTURE.md).
- **Settings:** Fortnite language (English / Portuguese (Brazil) / Both - pick the one your game uses; "Both" is not
  automatic detection), session logs, diagnostic recording, **Remember window size and position**. Everything else is in
  `config.toml` (Settings → Open config.toml; every option is explained inside).
- **Help & diagnostics:** setup steps, the offline guide and a one-click diagnostics report.

## Fair play and compatibility

The counter is built for statistics and stream presentation: it counts chest openings that are **already visible on
screen**. It gives no competitive information - it does not locate hidden chests, reveal enemies, aim, move or play for you.
It has no connection to Fortnite: it only reads video frames (a livestream, a screen capture, OBS Virtual Camera, a capture
device or a video file). It connects to the internet only to fetch a public livestream you paste (Livestream URL), and its one
keyboard shortcut (Ctrl+Alt+M, mark a missed chest) is a standard Windows hotkey that sends nothing to the game.

Epic Games' rules prohibit tools that use real-time gameplay information to gain a competitive advantage. This app is
designed for counting, not for competitive assistance - but Epic does not certify individual third-party applications, and
this one has not been reviewed or approved by Epic. The most conservative ways to use it:

- **Count recorded video** (Dashboard -> Analyse a recording), or
- **run the counter on a separate streaming PC** (dual-PC setup, [over the network with SRT](docs/guides/obs-dual-pc-srt.md)
  or [with a capture card](docs/guides/capture-card.md)), so the counter and the game run on different PCs.

Running the counter on the same PC as Fortnite works technically. In one developer session (2026-11-08) the app analysed a
livestream on the same PC while Fortnite was being played, and BattlEye did not interrupt the game. That is one observation,
not a verification: the app's compatibility with Fortnite's anti-cheat has not been officially verified, and anti-cheat
behaviour can change at any time. A dual-PC setup is not a compliance guarantee either; it simply keeps the counter away from
the game. Tournament or event rules can be stricter than normal play - check them if you compete.

## Updating

**From v0.2.3 on, the app has a built-in updater (experimental).** Shortly after opening it checks for a new version and, if there is
one, shows a small **Update available** link in the sidebar. Choose **Download & Install**: counting keeps running while the update is
downloaded and prepared, and **Restart & Install** finishes it. It is built to keep your counts, profiles, settings and OBS sources, and
to return to the previous version by itself if a new one does not start properly. Nothing is downloaded or installed unless you choose
to. The automatic check and the download speed are in **Settings > Updates**.

The updater has not installed a real update yet: v0.2.4 will be the first. If it does not work, install that version by hand as
described below.

**Getting v0.2.3 takes a manual download**, because older versions have no updater. Download it only from the official
[GitHub releases page](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases).

Your data is stored next to, not inside, the program files: `state\` (counts of every profile), `config.toml` (settings), `logs\`,
`captures\`, `obs_output\` (re-created automatically). Easiest: close the app, extract the new ZIP **into the same folder** and
replace files; opening the app writes your real numbers back into the OBS text files. If you extract to a new folder, copy
`state\` and `config.toml` and re-point the OBS Text source.

**Coming from v0.1.x:** delete the old `.bat` and `.cmd` files after extracting. Counts, settings and OBS sources keep working.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OBS Virtual Camera was not found` | Open OBS Studio 28+, click **Start Virtual Camera**, click **Start counting** again. |
| Number never changes | Turn on **Live preview**: 16:9, full screen, HUD visible? Does the chest pop-up ("CHEST" / "BAÚ") appear? Screen source: the stream must play **fullscreen** - a small player inside a web page is too small. |
| Livestream URL: "Buffering" / video in bursts | Normal for a live stream; the counter catches up and keeps counting. Keep **Stream stability: Maximum stability** for long sessions. |
| SRT picture black on the streaming PC | Address, port, Media Source settings and Windows Firewall: [SRT troubleshooting](docs/guides/obs-dual-pc-srt.md#troubleshooting). |
| OBS text blank / not updating | The Text source must have **Read from file** ticked and point at the file shown on the Overlay page. |
| Anything else | Help & diagnostics → **Run diagnostics** → **Copy report**; include any `logs\crash_*.txt` in an [issue](https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues). |

More: [full troubleshooting guide](docs/guides/troubleshooting.md).

## Fortnite compatibility

The chest detection in v0.2.2 was developed and live-tested during **Fortnite Chapter 7 Season 5** (November 2026);
its automated tests also use recordings of earlier gameplay. It recognises Fortnite's on-screen chest pop-up and HUD
elements, which Epic Games can change in any update. If chests stop being counted after an update, please
[open an issue](https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues) with the diagnostics report and, if you
can, a diagnostic capture.

## Known limitations

- **APPROX is an estimate** and can be slightly high or low. CERTAIN is the conservative number.
- **Language-specific:** chest detection reads the word in the pop-up: English (CHEST, incl. RARE CHEST and SPRITE CHEST)
  and Portuguese (Brazil) (BAÚ) only. Chest **types** (normal / rare / sprite) are read for English pop-ups only and are
  shown as "unknown type" when the line cannot be read reliably; types are a label, never a count.
- **HUD layout/scale:** assumes a 16:9 picture with the HUD in its usual place. For **English** pop-ups a HUD drawn larger
  (up to about 1.3x) or smaller (about 0.8x, tested on one stream) is recognised; those chests count in **APPROX only**,
  never CERTAIN. Other HUD sizes, a moved or hidden HUD, Portuguese pop-ups on a non-standard HUD, and 4:3 / vertical
  video will not work well.
- **Chests opened in quick succession** are ADDED to the pop-up on screen ("RARE CHEST X2", "X3", another "... CHEST"
  line). v0.2.2 counts those steps (multiplier steps in APPROX only); two chests within a fraction of a second can count as
  one - never as two for one chest. Portuguese stacked pop-ups are not tested.
- **Livestream URL:** video arrives as viewers get it - in bursts, with buffering, ad breaks and reconnects; footage the
  platform never delivered cannot be counted (the app says when that happens).
- **Screen source:** the gameplay must fill the screen; a small player inside a web page is not counted.
- **Clean gameplay feed recommended:** overlays on top of the HUD can hide the clues.
- **Audio is not used**; only the picture is analysed.
- **No per-match statistics yet:** the counter keeps one running total. Match tracking is planned
  ([roadmap](docs/ROADMAP.md)).
- Tested on a limited set of recordings (PC English, PS5 Portuguese, their stream-compressed versions, diagnostic
  recordings of streams with a larger and a smaller HUD, 11 labelled real-world cases), live sessions (incl. a 3-hour
  livestream) and one dual-PC SRT setup. Physical capture cards and real OBS projectors are untested. Windows only.

## Getting setup help from AI

If you are unfamiliar with OBS, give this README - and the [guide for your setup](docs/guides/README.md) - to ChatGPT,
Claude, Gemini or another assistant and ask it to guide you through the setup one step at a time.

Facts for assistants (please do not contradict these):

- The app is **`Fortnite Visual Chest Counter.exe`** in the extracted ZIP folder. It is the only thing the user opens.
  **Python is not required.** There are no `.bat` files any more (v0.1.x had them; v0.2.0 users can delete leftovers).
- Inputs, in the app's **Video source** list from most to least used: **Livestream URL** (paste a Twitch / YouTube link;
  the default for new installs), **screens** ("Screen 2 · 1920 x 1080" - the stream or game must play fullscreen),
  **OBS Virtual Camera** (for a streamer's own OBS scene named `ChestDetectorFeed`; Virtual Camera gear: Output Type
  **Scene** → **ChestDetectorFeed**), then capture devices and OBS projector windows (marked "less tested"). None of them is
  "the" recommended one: pick by setup.
- **Profiles** (Dashboard, above the numbers): one per person counted; each keeps its own counts, video source and chest-type
  split; one profile counts at a time; OBS shows the selected one.
- **Chest types** (line under the numbers): the APPROX total split into Chest / Rare chest / Sprite chest / unknown type /
  not classified. A label only: it never changes the two counts, and OBS shows only the totals.
- For OBS setups, `ChestDetectorFeed` must contain **clean Fortnite gameplay only**: no webcam, alerts, chat, or the
  counter's own text.
- Single-PC users capture Fortnite with OBS **Game Capture** (or Display Capture if Game Capture is black).
- Dual-PC users run the app on the **streaming PC** only; **nothing** from this project runs on the gaming PC or console.
  The gameplay reaches `ChestDetectorFeed` on the streaming PC in one of two ways:
  - **Over the network with SRT (tested 2026-11-07):** gaming PC OBS → Settings → Stream → Service **Custom...**, Server
    `srt://<streaming-PC-IPv4>:9000?mode=caller`, Stream Key empty, then **Start Streaming** (this only sends to the
    streaming PC). Streaming PC OBS → **Media Source**, **Local File** unticked, Input `srt://0.0.0.0:9000?mode=listener`,
    Input Format `mpegts`. Suggested start: NVENC H.264, 1280x720, 30 fps, 4000 Kbps. The receiving scene must be live in
    **Program** (Studio Mode: click Transition). Black picture → wrong IPv4 (`ipconfig` on the streaming PC), sender not
    streaming, or Windows Firewall blocking **UDP 9000** (network must be **Private**). Full guide:
    `docs/guides/obs-dual-pc-srt.md`.
  - **Capture card:** a **Video Capture Device** source inside `ChestDetectorFeed` (not yet tested with physical cards).
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
  about 1.3x larger or about 0.8x smaller is recognised for English pop-ups; those chests count in APPROX only.
- There are no per-match statistics yet (one running total); they are planned, not available.
- Problems: Help & diagnostics → **Run diagnostics** → **Copy report**. Missed chests: Dashboard → **Diagnostic recording** →
  "Only around my marks", then press **Ctrl+Alt+M** right after each miss.
- Advanced settings live in `config.toml` next to the app (Settings → Open config.toml); a wrong value only shows a warning
  and uses the default. Every command also works from a terminal: `runtime\python\python.exe -m fortnite_chest_counter --help`.
- The app only analyses video pixels; it never connects to Fortnite, and it uses the internet only to fetch a pasted
  livestream. It is **not** approved by Epic Games: never call it "ban-safe" or "BattlEye safe" (one developer session ran
  it next to Fortnite without a BattlEye interruption - one observation, not a guarantee). Most conservative setups:
  counting recorded video, or the counter on a separate PC.
- v0.2.2's detection was developed and tested during Fortnite Chapter 7 Season 5 (November 2026). A later Fortnite update can
  change the HUD cues it relies on; then the user should open an issue: https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues

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
`docs/` (`docs/guides/` = user setup guides), `research/`. Large recordings (`samples/`) are intentionally not in Git. See
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md); plans: [docs/ROADMAP.md](docs/ROADMAP.md).

## License

[MIT](LICENSE) - free to use, modify and share. The Windows download also bundles FFmpeg (LGPL v3, unmodified; its exact
source is attached to each GitHub release), Qt for Python / Qt (LGPL v3, unmodified), the official python.org Python runtime,
NumPy and SciPy under their own licenses; see `packaging/LICENSE-NOTICE.txt`.

Not affiliated with or endorsed by Epic Games. "Fortnite" is a trademark of Epic Games, Inc.
