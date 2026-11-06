## Fortnite Visual Chest Counter v0.1.0 — Public Beta

### ⬇️ [Download for Windows: Fortnite-Visual-Chest-Counter-v0.1.0.zip](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/download/v0.1.0/Fortnite-Visual-Chest-Counter-v0.1.0.zip) (107 MB)

Windows 10 / 11 · no Python or other installs needed · extract the zip and double-click **`Start Chest Counter.bat`**

---

**Visual chest detection for OBS, capture cards & video files.** A small tool for streamers that watches your gameplay
picture and keeps a running count of the chests you open, written to text files you show on stream with an OBS Text
source. It only looks at pixels: it does not read Fortnite's memory, modify the game, inject code or automate anything.

> **Public beta:** APPROX is an estimate, not a perfect count. Not affiliated with or endorsed by Epic Games.

### The two numbers

- **CERTAIN OPENED CHESTS** — chests detected with strong visual evidence.
- **APPROX. OPENED CHESTS** — the estimated **total**, **including** the certain ones. Do not add the two together.

### Choose how the counter sees your game

| Video input | Best for | Status |
|---|---|---|
| **OBS Virtual Camera** (default) | most OBS users, single PC or capture card | ✅ tested |
| **OBS projector on a second monitor** | your Virtual Camera is already used for something else | ⚠️ uses the tested desktop mode; projector setup not yet verified |
| **Capture card directly** | dual-PC setups where OBS does not need the card at the same time | ⚠️ advanced; not yet tested with physical capture cards; may conflict with OBS |
| **Recorded video** | counting chests in a gameplay file afterwards (drag it onto `Count Video File.bat`) | ✅ tested |

The two alternatives are switched on in a small settings file. Step-by-step instructions:
**[Choose your video input](https://github.com/GabrielGzS/fortnite-visual-chest-counter#choose-your-video-input)** ·
**[Virtual Camera already in use? Other video inputs](https://github.com/GabrielGzS/fortnite-visual-chest-counter#other-video-inputs-without-obs-virtual-camera)** ·
**[Troubleshooting](https://github.com/GabrielGzS/fortnite-visual-chest-counter#troubleshooting)**

### Quick start (OBS Virtual Camera)

1. Extract the zip to a normal folder (Desktop or Documents; not Program Files).
2. In OBS, create a scene `ChestDetectorFeed` with only your game in it (no webcam or overlays).
3. Set **Start Virtual Camera** to that scene and start it.
4. Double-click **`Start Chest Counter.bat`**.
5. Add OBS Text (GDI+) sources that read `obs_output\certain_chests.txt` and `obs_output\approximate_chests.txt`.

Full single-PC and dual-PC guides: [README](https://github.com/GabrielGzS/fortnite-visual-chest-counter#readme) (also
included in the zip as `README.html`).

### What's in v0.1.0

- English (CHEST) and Brazilian Portuguese (BAÚ) Fortnite.
- Counts persist across restarts; `Reset Counter.bat` works while the counter is running.
- Compression-tolerant confirmation, so chests in compressed streams can still reach CERTAIN.
- Stop it any way you like: press **Q**, Ctrl+C, or just **close the window**. Counts and the session report are saved.
- `Diagnostics.bat` support report; optional pop-up snapshots for reporting misses (`save_snapshots` in `config.toml`).

### Known limitations

- APPROX is an estimate and can be slightly high or low.
- Only English and Brazilian Portuguese pop-ups; normal HUD at a 16:9 picture. Audio is not used.
- No video-source picker yet: the alternative inputs are set in `config.toml`. Capture-card mode uses the card's default
  resolution. A picker and OBS projector-window capture are planned for v0.1.1.
- Tested on a limited set of recordings plus several hours of live Twitch/OBS sessions. Windows only.

### Files

| File | What it is |
|---|---|
| `Fortnite-Visual-Chest-Counter-v0.1.0.zip` | **The program — this is what you download.** |
| `SHA256SUMS.txt` | Checksums to verify the downloads. |
| `ffmpeg-source-db8537d8cc.tar.gz` | Source code of the bundled FFmpeg build (LGPL v3). Not needed to use the program. |

MIT licensed. Bundles FFmpeg (LGPL v3, unmodified build `N-128433-gdb8537d8cc-20261105`), Python, NumPy, SciPy and the
PyInstaller bootloader under their own licenses (see `LICENSE-NOTICE.txt` in the zip).

Found a missed or wrong chest, or tried a capture card? Please [open an issue](https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues)
with the `Diagnostics.bat` output and the session log from `logs\` (and, if you can, snapshots).
