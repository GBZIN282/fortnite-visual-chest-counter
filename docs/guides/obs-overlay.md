# Show the numbers on stream (OBS overlay)

The counter writes its numbers to a text file; an OBS **Text** source shows that file on your stream. You style the text
in OBS as you like. Same steps for every setup - on a dual-PC setup, do this in OBS on the streaming PC.

## Add the Text source

1. Open the scene your **viewers** see (not `ChestDetectorFeed`).
2. **Sources** -> **+** -> **Text (GDI+)** -> name it -> OK.
3. Tick **Read from file**, click **Browse** and choose **`obs_output\chest_counter.txt`** in the app's folder. The app's
   **Overlay** page shows the exact path; **Copy path** puts it on the clipboard.
4. Choose font, size and colour -> OK.

That is the only file you ever point OBS at. It updates within a second of every counted chest.

## Choose what viewers see

The app's **Overlay** page:

- **What OBS shows:** both numbers on two lines, both on one line, the estimated total only, or confirmed chests only - each
  with an example using your current numbers.
- **Wording:** `#` is where the number goes (`Chests opened: #`, `Chest Hunt: #/500`). For one line, `#C` = confirmed and
  `#A` = estimated total. **Original wording** restores the defaults. Any text, symbols and emoji work (with an OBS font that
  has them).
- **Preview** shows exactly what the file will contain; **Apply** updates OBS at once, even while counting.

The app cannot hide a Text source you already added in OBS: if a number on stream looks wrong, that source probably reads
another file.

## Advanced: `config.toml` and the other files

In `config.toml`, section `[display]`: `show = "both" | "certain" | "approx"`, `both_layout = "stacked" | "inline"`,
`certain_text`, `approx_text`, `combined_status_format` (`{count}` = the number; `{certain}` / `{approx}` anywhere; `\n` = new
line; `{{` / `}}` = literal braces), `use_thousands_separator`.

For separately styled sources the counter also writes:

| File in `obs_output\` | Contains |
|---|---|
| `chest_counter.txt` | **the one to use:** whatever the Overlay page chose |
| `chest_status.txt` | legacy: one line with both numbers (or the single number chosen) |
| `certain_chests.txt` | always the confirmed number |
| `approximate_chests.txt` | always the estimated total |
| `last_chest.txt` | the most recent chest, e.g. `CHEST +1 • HIGH` |

Opening the app writes your saved numbers back into these files, so the overlay is right before you start counting.
