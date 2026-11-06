## Fortnite Visual Chest Counter v0.1.1 — Public Beta

### ⬇️ [Download for Windows: Fortnite-Visual-Chest-Counter-v0.1.1.zip](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/download/v0.1.1/Fortnite-Visual-Chest-Counter-v0.1.1.zip) (118 MB)

Windows 10 / 11 · nothing to install · extract the zip and double-click **`Start Chest Counter.bat`**

A quality-of-life update: **start from your own total**, **your overlay, your words**, and a **colour-coded counter
window**. Chest detection is exactly the same as in v0.1.0 (verified event by event on the test recordings).

### New: start from the chests you already opened

Double-click **`Set Starting Count.bat`**, type how many chests you have already opened (e.g. `150`) and press Enter.
APPROX starts at 150 and new chests are added on top; CERTAIN starts at 0, because the counter did not see those earlier
chests. Works while the counter is running. Wrong entries are refused without changing anything.
**`Reset Counter.bat`** still sets everything back to 0.

### New: customize what viewers see

- **One easy file for OBS:** `obs_output\chest_counter.txt` shows both numbers, or only one.
- **Show only what you want:** `show = "both"`, `"certain"` or `"approx"` (the estimated total).
- **Your own wording:** `approx_text = "Chest Hunt: {count}/500"`, `certain_text = "Confirmed: {count}"`. Any text, symbols
  and emoji; `\n` for a second line.
- A typo never breaks the counter: you get a `WARNING` and the default text.
- Your existing OBS sources keep working: the file names did not change, and v0.1.0 settings still apply.

Examples: [Customize what viewers see](https://github.com/GabrielGzS/fortnite-visual-chest-counter#customize-what-viewers-see).
Tip: paste your `config.toml` into an AI assistant and ask it to make the change for you.

### New: a readable counter window

- **Green** `[CERTAIN]` certain chest · **yellow** `[APPROX ]` counted in APPROX only · **red** `[REJECT ]` not counted ·
  **white on red** errors · **cyan** status.
- Each line says why: `match 0.78 (MEDIUM)`, `shooting at the same moment`, `confirmed by compression check`.
  `match` is the pop-up word match score, not a percentage.
- `verbosity = "minimal" | "normal" | "debug"` and `colors = false` under `[console]`.

Details: [The counter window](https://github.com/GabrielGzS/fortnite-visual-chest-counter#the-counter-window-colours-and-detail).

### Improved

- **Reset and Set Starting Count always win**, even if a chest is detected in the very same second.
- **Lighter package:** the app now runs on the official Python runtime from python.org, included in the zip; launchers
  start it directly (there is no separate `.exe` any more).
- The guide inside the zip now covers the other video inputs (OBS projector on a second monitor, capture card directly),
  the new settings and the starting count.

### Upgrading from v0.1.0

1. Close the counter.
2. Extract the new zip **into your existing folder** and replace the files. Your counts (`state\`), settings (`config.toml`),
   logs and OBS Text sources are kept.
3. Delete the old `Fortnite Visual Chest Counter.exe` from the folder (v0.1.1 starts from the `.bat` files).
4. Double-click `Show Counter.bat` once.

### Fortnite compatibility

Developed and live-tested during **Fortnite Chapter 7 Season 5** (November 2026). The counter reads Fortnite's on-screen
chest pop-up and HUD, which future Fortnite updates may change; if counting stops working after an update, please
[open an issue](https://github.com/GabrielGzS/fortnite-visual-chest-counter/issues).

### Known limitations

APPROX is an estimate. English and Brazilian Portuguese only; normal HUD at 16:9. No video-source picker yet;
capture-card mode is untested on physical cards.

### Files

| File | What it is |
|---|---|
| `Fortnite-Visual-Chest-Counter-v0.1.1.zip` | **The program — this is what you download.** |
| `SHA256SUMS.txt` | Checksums to verify the downloads. |
| `ffmpeg-source-db8537d8cc.tar.gz` | Source code of the bundled FFmpeg build (LGPL v3). Not needed to use the program. |

MIT licensed. Includes the official Python runtime (PSF License), NumPy, SciPy and FFmpeg (LGPL v3) under their own licenses;
`runtime\PROVENANCE.txt` lists where each component comes from.
