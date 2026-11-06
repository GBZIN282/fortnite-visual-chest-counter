## Fortnite Visual Chest Counter v0.1.1 — Public Beta

### ⬇️ [Download for Windows: Fortnite-Visual-Chest-Counter-v0.1.1.zip](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/download/v0.1.1/Fortnite-Visual-Chest-Counter-v0.1.1.zip)

Windows 10 / 11 · no Python or other installs needed · extract the zip and double-click **`Start Chest Counter.bat`**

A quality-of-life update: **your overlay, your words**, and a **colour-coded counter window**. Chest detection is
exactly the same as in v0.1.0 (verified event-by-event on the regression recordings).

### New: customize what viewers see

- **One easy file for OBS:** `obs_output\chest_counter.txt` shows both numbers, or only one.
- **Show only what you want:** `show = "both"`, `"certain"` or `"approx"` (the estimated total).
- **Your own wording:** `approx_text = "Chest Hunt: {count}/500"`, `certain_text = "Confirmed: {count}"`. Any text,
  symbols and emoji; `\n` for a second line.
- A typo can never break the counter: you get a `WARNING` and the default text.
- Existing OBS sources keep working: the file names did not change, and v0.1.0 settings (`certain_label`,
  `approximate_label`) still apply.

Examples and the full list: [Customize what viewers see](https://github.com/GabrielGzS/fortnite-visual-chest-counter#customize-what-viewers-see).
Tip: paste your `config.toml` into an AI assistant and ask it to make the change for you.

### New: a readable counter window

- **Green** `[CERTAIN]` certain chest · **yellow** `[APPROX ]` counted in APPROX only · **red** `[REJECT ]` not counted ·
  **white on red** errors · **cyan** status.
- Each line says why: `match 0.78 (MEDIUM)`, `shooting at the same moment`, `confirmed by the compression-tolerant check`.
  `match` is the pop-up word match score, not a probability.
- `verbosity = "minimal" | "normal" | "debug"` and `colors = false` under `[console]`.

Details: [The counter window](https://github.com/GabrielGzS/fortnite-visual-chest-counter#the-counter-window-colours-and-detail).

### Also

- The guide inside the zip now explains the other video inputs (OBS projector on a second monitor, capture card directly).

### Upgrading from v0.1.0

Extract the new zip **into your existing folder** and replace the files. Your counts (`state\`), settings (`config.toml`) and
logs are kept; your OBS Text sources keep working. Then run `Show Counter.bat` once.

### Known limitations

Same as v0.1.0: APPROX is an estimate; English and Brazilian Portuguese only; normal HUD at 16:9; no video-source picker
yet; capture-card mode untested on physical cards.

### Files

| File | What it is |
|---|---|
| `Fortnite-Visual-Chest-Counter-v0.1.1.zip` | **The program — this is what you download.** |
| `SHA256SUMS.txt` | Checksums to verify the downloads. |
| `ffmpeg-source-db8537d8cc.tar.gz` | Source code of the bundled FFmpeg build (LGPL v3). Not needed to use the program. |

MIT licensed. Bundles FFmpeg (LGPL v3), Python, NumPy, SciPy and the PyInstaller bootloader under their own licenses.
