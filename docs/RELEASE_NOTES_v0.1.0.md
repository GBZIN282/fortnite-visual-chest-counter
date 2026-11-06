## Fortnite Visual Chest Counter v0.1.0 — Public Beta

**Visual chest detection for OBS, capture cards & video files.**

A small Windows tool for streamers that watches your gameplay picture and keeps a running count of the chests you open,
written to text files you show on stream with a normal OBS Text source. It only looks at pixels: it does not read
Fortnite's memory, modify the game, inject code or automate anything.

> This is a **public beta**. APPROX is an estimate, not a perfect count. Not affiliated with or endorsed by Epic Games.

### The two numbers

- **CERTAIN OPENED CHESTS** — chests detected with strong visual evidence.
- **APPROX. OPENED CHESTS** — the estimated **total**, **including** the certain ones. Do not add the two together.

### Download and run (no Python needed)

1. Download **`Fortnite-Visual-Chest-Counter-v0.1.0.zip`** below.
2. Right-click it → **Extract All** (Desktop or Documents is fine; not Program Files).
3. In OBS: make a scene `ChestDetectorFeed` with only your game, set **Start Virtual Camera** to that scene and start it.
4. Double-click **`Start Chest Counter.bat`**. Add OBS Text sources reading `obs_output\certain_chests.txt` and
   `obs_output\approximate_chests.txt`.

Full single-PC, dual-PC (capture card) and recorded-video instructions are in the README and in `README.html` inside the zip.
Windows may warn that the program is not code-signed: **More info → Run anyway**.

### What's in this release

- Live counting from **OBS Virtual Camera** (recommended, single- and dual-PC), a capture card directly, or the desktop.
- **Recorded videos**: drag a gameplay file onto `Count Video File.bat` (never touches your live counter).
- English (CHEST) and Brazilian Portuguese (BAÚ) Fortnite.
- Counts persist across restarts; `Reset Counter.bat` works while the counter is running.
- Compression-tolerant confirmation, so chests in compressed streams can still reach CERTAIN.
- Stop it any way you like: press **Q**, Ctrl+C, or just **close the window** — counts and the session report are saved.
- `Diagnostics.bat` support report; optional pop-up snapshots for reporting misses (`save_snapshots` in `config.toml`).

### Known limitations

- APPROX is an estimate and can be slightly high or low.
- Only English and Brazilian Portuguese pop-ups; normal HUD at a 16:9 picture.
- A clean gameplay feed (no overlays over the HUD) works best. Audio is not used.
- Tested on a limited set of recordings plus multi-hour live Twitch/OBS sessions. Windows only.

### Files

| File | What it is |
|---|---|
| `Fortnite-Visual-Chest-Counter-v0.1.0.zip` | The program — this is what you download. |
| `SHA256SUMS.txt` | Checksums to verify the downloads. |
| `ffmpeg-source-db8537d8cc.tar.gz` | Source code of the bundled FFmpeg build (LGPL v3). You do not need this to use the program. |

Licensed under MIT. Bundles FFmpeg (LGPL v3, unmodified build `N-128433-gdb8537d8cc-20261105`), Python, NumPy, SciPy and the
PyInstaller bootloader under their own licenses (see `LICENSE-NOTICE.txt` in the zip).

Found a missed or wrong chest? Please open an issue with the `Diagnostics.bat` output, the session log from `logs\`, and,
if you can, snapshots (`save_snapshots = true`).
