## Fortnite Visual Chest Counter v0.2.0 — Public Beta (DRAFT, not released)

### ⬇️ Download for Windows: Fortnite-Visual-Chest-Counter-v0.2.0.zip (about 134 MB)

Windows 10 / 11 · nothing to install · extract the zip and open **`Fortnite Visual Chest Counter.exe`**

**A real desktop app.** No more console windows or `.bat` files: one app to start and stop counting, see both numbers,
choose what viewers see, set or reset the count and get help. Chest detection is exactly the same as in v0.1.1 (the app
runs the same counting engine; verified event by event on the test recordings).

### New: one app

- **Dashboard:** both numbers (CERTAIN and the estimated total APPROX), the video source (OBS Virtual Camera, a capture
  device or a screen - picked from a list, no device names to type) and one **Start counting** button.
- **Activity panel:** every chest the moment it is counted - green = certain, yellow = estimated only, red = looked like a
  chest pop-up but was not counted - with the reason. **Debug detail** shows every candidate and the full reasoning.
- **Live preview (optional):** see the picture the counter analyses, to check it sees the game with the HUD.
  Hiding it, closing the panels or minimising the app never affects counting.
- **Overlay page:** choose what viewers see (both numbers, one line, total only, confirmed only), your own words (`#` =
  the number), a live preview of the text, and the exact OBS file path with a Copy button. Applies instantly while counting.
- **Edit counts / Reset** on the Dashboard (start from the chests you already opened, or fix a count), also while counting.
- **Analyse a recording:** count the chests in a video file with a progress bar; never changes your live counter.
- **Settings** (Fortnite language, session logs and pop-up pictures) and **Help & diagnostics** (setup steps, one-click
  diagnostics report with Copy).

### New: help improve accuracy - marks and diagnostic recording (optional)

- **Diagnostic recording** on the Dashboard (off by default), switchable while counting without touching the counts:
  only around your marks (smallest), around chest decisions and marks, or the whole session.
- Missed a chest? Press **Ctrl+Alt+M** while you play (or **Mark moment**): the video around it is kept, confirmed with a
  green "Marked" line. Each recording gets a folder with the video, every decision and a `labels.csv`.
- **Review captures** replays them through the current version of the counter and compares with what was counted live
  and with your labels - with progress and time left - so every miss becomes a repeatable test for future versions.
- **Analyse a recording** shows the time left.

### Improved

- Opening the app writes your saved numbers back into the OBS text files (after an update, no extra step).
- Counting runs separately from the window: a busy or closed window can never cost a frame, and if the app is closed the
  counter still stops cleanly and saves.

### Updating from v0.1.x

Close the counter, extract the new zip into the same folder (replace files), then delete the old `.bat` and `.cmd`
files. Your counts, settings and OBS text source keep working.

### Under the hood

- The `.exe` is a small launcher (source in `packaging/launcher/launcher.c`) that starts the app with the bundled official
  python.org runtime. The window uses Qt for Python (PySide6, LGPL v3, unmodified official files).
- Every command-line command still works: `runtime\python\python.exe -m fortnite_chest_counter <command>`.
