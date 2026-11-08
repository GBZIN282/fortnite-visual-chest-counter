## Fortnite Visual Chest Counter v0.2.1 — Public Beta *(draft - not released)*

Windows 10 / 11 · nothing to install · extract the zip and open **`Fortnite Visual Chest Counter.exe`**

**An OBS compatibility update.** Fits setups where everything is already in use: the capture card belongs to OBS and the
Virtual Camera belongs to another program. Chest detection is unchanged.

### What's new at a glance

| New in v0.2.1 | Why it matters |
|---|---|
| **OBS projector input** | Count from an OBS "Windowed Projector (Source)" of your gameplay - no Virtual Camera, no second opening of the capture card, no plugin |
| **OBS WebSocket overlay (optional)** | The numbers go straight into your OBS Text source: instant updates, no file path. The text file is still written |
| **Pictures analysed per second** | Choose 15 (Recommended), 10 (Balanced) or 5 (Performance) in Settings, with the measured trade-off shown |

### OBS projector input

In OBS, right-click your gameplay source > **Windowed Projector (Source)**. In the app, click **Refresh** and pick
**OBS projector: ...** in the Video source list. The window can stay behind other windows; if it is minimized or closed,
the app says so. Black bars are cut off automatically. Guide:
[OBS projector window](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/obs-projector.md).

*Tested on our development PC with a stand-in window (15 pictures per second, nothing dropped, the same chests counted as
from the video file). Not yet tested with a real OBS projector and a physical capture card - feedback welcome.*

### OBS WebSocket overlay (optional, off by default)

**Overlay** page > **OBS WebSocket**: enable OBS's WebSocket server (**Tools > WebSocket Server Settings**), paste its
password, pick your Text source. The app copies exactly what `obs_output\chest_counter.txt` contains, so viewers see the
same text either way.

- Instant: OBS reads a text file only about once a second; a direct update shows at once.
- Safe by design: the password stays in Windows Credential Manager (never in a file or a report), and the app can only
  list inputs, read one source's settings and set that source's text.
- Calm when OBS is not there: OBS closed, restarting or on another PC - counting and the text file are never affected,
  and the app catches up with the current numbers when OBS is back. A renamed source is followed.
- A source with **Read from file** ticked is detected; the app only changes that setting when you click
  **Use direct updates**.

### Pictures analysed per second

**Settings** > **Pictures analysed per second**. Measured on our two labelled test recordings (22 chests) and our
development PC:

| Setting | Chests found | Extra estimated counts | Counter CPU |
|---|---|---|---|
| **15 (Recommended)** | 21 of 22 | - | about 45 % of one core |
| 10 (Balanced) | 21 of 22 | 2 | about 44 % of one core |
| 5 (Performance) | 18 of 22 | - | about 25 % of one core |

15 stays the default: it is what the detector was built and tested with. On our PC, 10 saved hardly any CPU; 5 halves it
but misses chests. Your PC may differ.

### Unchanged

Chest detection, the two numbers, the text files in `obs_output\`, your saved counts and settings. Updating: extract the
new zip and copy `state\` and `config.toml` from the old folder (see the README).
