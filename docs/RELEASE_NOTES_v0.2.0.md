## Fortnite Visual Chest Counter v0.2.0 — Public Beta

### ⬇️ [Download for Windows: Fortnite-Visual-Chest-Counter-v0.2.0.zip](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/download/v0.2.0/Fortnite-Visual-Chest-Counter-v0.2.0.zip) (134 MB)

Windows 10 / 11 · nothing to install · extract the zip and open **`Fortnite Visual Chest Counter.exe`**

> ✅ **Tested after release (2026-11-07): dual-PC over your local network with SRT, no capture card.** The counter runs on
> the streaming PC; nothing from this project runs on the gaming PC. Many chests counted, no noticeable lag.
> **[Step-by-step SRT setup guide](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/obs-dual-pc-srt.md)** ·
> [all setup guides](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/README.md).
> This is a documented compatibility test, not a software change: same download, same SHA-256.

**The biggest update so far: a real Windows desktop app.** No more console windows or `.bat` files - one app to start
and stop counting, see both numbers, watch what the counter sees, choose what viewers see, fix the count and get help.

Fortnite Visual Chest Counter counts the chest-opening pop-ups visible in Fortnite gameplay video. Use it on **your own
stream** (single-PC or dual-PC, through OBS), on **a livestream you are watching**, or on **a recorded video** - it works
from the picture alone.

### What's new at a glance

| New in v0.2.0 | Why it matters |
|---|---|
| **Windows desktop app** | No command line, no batch files: one window for everything |
| **Live preview and Activity panel** | See the picture the counter analyses and every chest the moment it is counted, with the reason |
| **Diagnostic recording, marks and review** | Keep the video around a missed chest (Ctrl+Alt+M) and replay it later |
| **Larger-HUD recognition** | Counts chests on streams whose HUD is drawn larger, which v0.1.x missed |
| **OBS overlay customization** | Choose what viewers see and your own wording, applied instantly |
| **Edit counts and Reset** | Start from the chests you already opened, or correct a count - also while counting |
| **Language selection** | English, Portuguese (Brazil) or Both, picked in Settings |
| **Window size and position memory** | The app reopens the way you left it (on by default) |

### The desktop app

- **Dashboard:** both numbers (CERTAIN and the estimated total APPROX), the video source picked from a list (OBS Virtual
  Camera, a capture device or a screen - no device names to type) and one **Start counting** button.
- **Activity panel:** every decision as it happens - green = certain, yellow = estimated only, red = looked like a chest
  pop-up but was not counted - with a short reason. **Debug detail** shows every candidate and the full reasoning.
- **Live preview (optional):** the exact picture the counter analyses, to check it sees the game with the HUD. Hiding it,
  closing the panels or minimising the app never affects counting.
- **Overlay page:** both numbers on two lines or one line, estimated total only, or confirmed only; your own words (`#` = the
  number); a live preview of the text; the exact OBS file path with a Copy button. Changes apply instantly, even while counting.
- **Edit counts / Reset** on the Dashboard, also while counting.
- **Analyse a recording:** count the chests in a video file, with progress and time left; never changes your live counter.
- **Settings:** Fortnite language, session logs and pop-up pictures, lossless recording, and **Remember window size and
  position** (on by default; maximised or not; a window whose monitor is gone is moved back onto a screen).
- **Help & diagnostics:** setup steps, the full guide, and a one-click diagnostics report with Copy.
- Counting runs in a separate process from the window: a busy or closed window can never cost a frame, and closing the app
  still stops the counter cleanly and saves. Opening the app writes your saved numbers back into the OBS text files.

### Help improve accuracy: marks, diagnostic recording and review (optional)

- **Diagnostic recording** on the Dashboard (off by default), switchable while counting without touching the counts: only
  around your marks (smallest), around every chest decision and mark, or the whole session.
- Missed a chest? Press **Ctrl+Alt+M** while you play (or **Mark moment**): the video around it is kept and confirmed with a
  green "Marked" line. Each recording gets a folder with the video, every decision and a `labels.csv`.
- **Review captures** replays recordings through the current counter and compares with what was counted live and with your
  labels - with progress and time left - so every miss becomes a repeatable test for future versions.

### Better detection: chests on a larger HUD (English)

Some streams draw the Fortnite HUD about 1.2x larger, and v0.1.x missed nearly every chest there. The counter now also
recognises the English "CHEST" pop-up drawn up to about 1.3x larger. These chests count in the estimated total
(**APPROX only**, never CERTAIN), and a pop-up the normal match already found is never counted again. On three recordings of
such streams it found 11 of 11 checked chests (v0.1.1: 3), with no chest counted twice and nothing counted that was not a
chest. On normal-HUD footage every decision is the same as in v0.1.1 (verified event by event on the test recordings).

### Video inputs and setup guides

OBS Virtual Camera (recommended - single-PC, or the streaming PC of a dual-PC setup), capture devices, a screen, or a video
file. Step-by-step guides:

| Setup | Guide | Tested |
|---|---|---|
| Fortnite and OBS on one PC | [Single PC](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/obs-single-pc.md) | Yes |
| Gaming PC + streaming PC on the same network, no capture card | [Dual PC over the network (SRT)](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/obs-dual-pc-srt.md) | **Yes** - 2026-11-07 |
| Console or gaming PC + capture card + streaming PC | [Capture card](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/capture-card.md) | Counter side yes; not yet with a physical card |
| A video file | [Recorded video](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/recorded-video.md) | Yes |

Then: [show the numbers on stream](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/obs-overlay.md) ·
[troubleshooting](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/troubleshooting.md).

### Post-release validation: dual-PC over SRT (2026-11-07)

After publication we tested the public v0.2.0 download in a real two-PC setup:

| | Gaming PC (sender) | Streaming PC (receiver) |
|---|---|---|
| Hardware | Intel Core i9 13th gen, NVIDIA RTX 4080 | Intel Core i5 13th gen, NVIDIA RTX 4070 |
| Role | OBS captures the Fortnite picture and sends it over the local network with SRT (Custom service, caller) | OBS receives it (Media Source, SRT listener, MPEG-TS) → OBS Virtual Camera → Fortnite Visual Chest Counter v0.2.0 |

- **Video:** a Fortnite stream playing on the gaming PC, captured by its OBS. The video path is the same as for a match
  played live.
- **Result:** numerous chests detected and counted on the streaming PC, no noticeable lag or other significant problems.
  The counter did not run on the gaming PC.
- **Scope:** this validates SRT as a viable video path for the counter on the tested setup. It is not a guarantee for every
  network or configuration. The [guide](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/obs-dual-pc-srt.md)
  covers both PCs' OBS settings, suggested starting settings (NVENC H.264, 720p30, 4000 Kbps), Studio Mode, Windows Firewall
  (UDP port 9000) and black-screen troubleshooting.
- **No software change:** the v0.2.0 zip, its SHA-256 and the `v0.2.0` tag are unchanged; only the documentation was
  updated.

### Known limitations

- APPROX is an estimate; CERTAIN is the conservative number.
- English and Brazilian Portuguese only. A larger HUD is recognised for English pop-ups only, and those chests count in
  APPROX only. A smaller, moved or hidden HUD, or a 4:3 / vertical picture, will not work well.
- On a larger HUD, a second chest opened while the first pop-up is still showing counts as one.
- Other chest types whose pop-up does not say "CHEST" / "BAÚ" (e.g. Sprite Chests) are not counted yet.
- One running total; per-match statistics are planned, not included yet.
- Tested on a limited set of recordings, live sessions and one dual-PC SRT setup; capture-card input is untested on
  physical cards.

### Fair play and compatibility

The counter only analyses the video picture and counts chest openings that are already visible on screen. It does not
locate hidden chests, reveal enemies, aim, automate gameplay, read Fortnite's memory or files, inject code or modify the
game, and it makes no internet connection. It is an independent project - not affiliated with, endorsed by or approved by
Epic Games. Epic's rules prohibit tools that use real-time gameplay information to gain a competitive advantage; this app is
designed for counting, not for competitive assistance, but Epic does not certify individual third-party applications. The
most conservative setups are counting recorded video and running the counter on a separate streaming PC (for example with
the tested SRT setup above). Running it on the
same PC as Fortnite works, but its compatibility with Fortnite's anti-cheat has not been officially verified - and a dual-PC
setup is not a compliance guarantee either. Details: README, "Fair play and compatibility".

### Updating from v0.1.x

Close the counter, extract the new zip into the same folder (replace files), then delete the old `.bat` and `.cmd` files.
Your counts, settings and OBS text source keep working.

### Files

| File | What it is |
|---|---|
| `Fortnite-Visual-Chest-Counter-v0.2.0.zip` | **The program - this is what you download.** SHA-256 `d99ff0692cd6db4b240b8f727a92caaabba940bd951e001a4abeceb55f6f8b77` |
| `SHA256SUMS.txt` | Checksums to verify the downloads. |
| `ffmpeg-source-db8537d8cc.tar.gz` | Source code of the bundled FFmpeg build (LGPL v3). Not needed to use the program. |

MIT licensed. The `.exe` is a small launcher (source in `packaging/launcher/launcher.c`) that starts the app with the bundled
official python.org runtime (PSF License). Includes Qt for Python / Qt (PySide6, LGPL v3, unmodified official files), NumPy,
SciPy and FFmpeg (LGPL v3) under their own licenses; `runtime\PROVENANCE.txt` lists where each component comes from. Every
command-line command still works: `runtime\python\python.exe -m fortnite_chest_counter <command>`.
