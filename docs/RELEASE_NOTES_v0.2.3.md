## Fortnite Visual Chest Counter v0.2.3 — Public Beta

### ⬇️ [Download for Windows: Fortnite-Visual-Chest-Counter-v0.2.3.zip](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/download/v0.2.3/Fortnite-Visual-Chest-Counter-v0.2.3.zip) (about 156 MB)

Windows 10 / 11 · nothing to install · extract the zip and open **`Fortnite Visual Chest Counter.exe`**

**A built-in updater, as an experimental feature.** v0.2.3 adds an updater: the app tells you when a new version is out, then
downloads and installs it when you choose to, keeping your counts, profiles and settings.

> **This should be the last manual download.** v0.2.2 and earlier have no updater, so they cannot update themselves to v0.2.3.
> Install this version by hand once, as described below. Future versions are meant to install from inside the app.
>
> **The updater is experimental.** There is no newer version for it to install yet, so a complete update and an automatic
> rollback have not been run on a real installation. v0.2.4 will be the first. If an update does not work, install that version by
> hand the same way as this one.

### What's new at a glance

| New in v0.2.3 | Why it matters |
|---|---|
| **Update notice** | Shortly after opening, the app checks for a new version. If there is one, a small **Update available** link appears in the sidebar. Nothing pops up |
| **You choose when** | Nothing is downloaded or installed unless you ask. **Download & Install** gets the update ready; **Restart & Install** finishes it |
| **Keeps counting** | Counting continues while an update downloads and is prepared. It only stops when you confirm the restart |
| **Your data stays** | Built to keep your counts, profiles, settings, OBS text files and your own files, and to back up your saved data before each update |
| **Automatic recovery** | Built to go back to the previous version by itself if a new version does not start properly, and to tell you what happened |
| **Signed updates** | The app only installs updates signed by this project. A changed or unofficial download is refused |
| **Download speed** | Settings > Updates: **Adaptive** (recommended, about 1 MB/s while counting and no limit otherwise), **Unlimited** or **Custom** |

### Settings > Updates

Turn the automatic check on or off, choose the download speed, or press **Check for updates** at any time. If you turn the
automatic check off, the app only looks for a new version when you press that button.

### Detection and counting

Unchanged from v0.2.2. This version only adds the updater.

### Known limitations

- The updater has not yet installed a real update or performed a real rollback. Automated tests cover it, but v0.2.4 will be its first real use.
- v0.2.3 itself has to be installed by hand, and it is only available from the official GitHub releases page.
- Checking for and downloading updates needs an internet connection and GitHub to be reachable. The app keeps working without them.
- APPROX is an estimate; CERTAIN is the conservative number.
- HUD sizes other than normal, about 1.3x larger and about 0.8x smaller are untested; Portuguese pop-ups are recognised on a
  normal HUD only, and Portuguese stacked pop-ups are untested.
- Chest types: English only; the rare / sprite split is based on a small number of streams.
- Livestream URL counts what viewers get - video the platform never delivered (outages, ad breaks) cannot be counted.
- **Fair play:** the app only analyses video pixels and never touches Fortnite. In one developer session it analysed a
  livestream on the same PC while Fortnite was being played without a BattlEye interruption - one observation, not a
  guarantee; anti-cheat compatibility has not been officially verified. See the README's *Fair play and compatibility*.

### Installing v0.2.3

Close the app, extract the new zip **into the same folder** and replace the files - counts, settings, profiles and OBS
sources keep working (or copy `state\` and `config.toml` to a new folder). Download it only from the official
[GitHub releases page](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases).

**Full details:** [README](https://github.com/GabrielGzS/fortnite-visual-chest-counter#readme)

Independent, unofficial project: not affiliated with, endorsed by or approved by Epic Games. "Fortnite" is a trademark of
Epic Games, Inc. MIT licence. Developed and tested during Fortnite Chapter 7 Season 5 (November 2026).
