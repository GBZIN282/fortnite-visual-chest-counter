## Fortnite Visual Chest Counter v0.2.1 — Public Beta

> ⚠️ **Important — Fortnite HUD scale.** For the best chest detection, use a **normal or medium-sized Fortnite HUD**
> (Fortnite's HUD Scale setting) and avoid very small HUD scales. The counter currently works best with HUD sizes like
> the ones used during development and testing; a smaller HUD makes the chest XP pop-ups smaller (and can move them),
> which can cause missed chests. Support for more HUD scales is planned for **v0.2.2**.
> This also applies to **Livestream URL** counting (Twitch / YouTube, experimental): accuracy depends on the streamer's
> HUD settings.

### ⬇️ [Download for Windows: Fortnite-Visual-Chest-Counter-v0.2.1.zip](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/download/v0.2.1/Fortnite-Visual-Chest-Counter-v0.2.1.zip) (156 MB)

Windows 10 / 11 · nothing to install · extract the zip and open **`Fortnite Visual Chest Counter.exe`**

**Count chests from a Twitch or YouTube livestream link - no OBS, no capture card, no browser.** Plus OBS compatibility
for setups where everything is already in use. Chest detection is unchanged.

### What's new at a glance

| New in v0.2.1 | Why it matters |
|---|---|
| **Livestream URL** (experimental) | Paste a Twitch or YouTube live link and press Start: the counter reads the public stream directly |
| **OBS projector input** | Count from an OBS "Windowed Projector (Source)" of your gameplay - no Virtual Camera, no second opening of the capture card, no plugin |
| **OBS WebSocket overlay (optional)** | The numbers go straight into your OBS Text source: instant updates, no file path. The text file is still written |
| **Pictures analysed per second** | Choose 15 (Recommended), 10 (Balanced) or 5 (Performance) in Settings, with the measured trade-off shown |

### Livestream URL (Twitch / YouTube) - experimental

**Video source** > **Livestream URL**, paste `https://www.twitch.tv/CHANNEL` or a YouTube live link, keep
**Stream stability: Maximum stability (recommended)**, **Start counting**.
The counter reads the stream as viewers get it (a few seconds behind) and analyses every picture in order, so nothing is
skipped when the platform delivers video in bursts. If the connection drops, the app reconnects by itself, keeps your
counts, and says so clearly - red *Reconnecting* in the status, the Activity log and over the Live preview - plus how many
seconds of the stream could not be seen (chests in that part are missing from the count). Guide:
[Livestream URL](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/guides/livestream-url.md).

**Stream stability:** *Maximum stability* (recommended) = lowest buffering risk and the most delay, best for long
sessions; *Balanced* = moderate buffering risk; *Low latency* = higher buffering risk, not recommended when complete counts
matter. A bigger buffer cannot bring back video the platform never delivered.

> **Experimental - please read:** network interruptions, ad breaks and stream restarts can make the counter miss chests
> (the app tells you when and for how long). Multi-hour reliability is not verified yet, and Twitch and YouTube have not
> been compared over long sessions - neither is recommended over the other yet. How many chests a compressed stream makes
> it miss is not measured yet. Tested on a live Fortnite stream simulcast on Twitch and YouTube (both counted the same
> chests; every counted chest checked was a real pop-up) and in a manual session (13 chests counted).

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

Chest detection, the two numbers, the text files in `obs_output\`, your saved counts and settings. Fixed: the taskbar
sometimes showed a generic icon instead of the app's own icon while the app was starting. Updating: extract the
new zip and copy `state\` and `config.toml` from the old folder (see the README).
