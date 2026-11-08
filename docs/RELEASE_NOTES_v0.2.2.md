## Fortnite Visual Chest Counter v0.2.2 — Public Beta

### ⬇️ [Download for Windows: Fortnite-Visual-Chest-Counter-v0.2.2.zip](https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/download/v0.2.2/Fortnite-Visual-Chest-Counter-v0.2.2.zip) (about 156 MB)

Windows 10 / 11 · nothing to install · extract the zip and open **`Fortnite Visual Chest Counter.exe`**

**Better chest detection, separate counts per person, and chest types.** v0.2.2 counts the chests v0.2.1 missed on
streams with a smaller HUD and when several chests are opened in a row, stops counting some chests twice, keeps one
counter per streamer, and tells you how many of the counted chests were normal, rare or sprite chests.

### What's new at a glance

| New in v0.2.2 | Why it matters |
|---|---|
| **Chests opened in a row** | Fortnite adds the next chest to the pop-up already on screen ("RARE CHEST X2", "X3", another "... CHEST" line). v0.2.2 counts those steps; v0.2.1 counted only the first chest |
| **Smaller HUD** | Streams with a smaller HUD (about 0.8x, e.g. Thiefs) are counted - v0.2.1 counted none of their chests |
| **Fewer double counts** | A pop-up that only moved (a non-chest line such as SPRITE LEVEL or WEAKPOINT STREAK added, or its scale-in animation) is no longer counted again |
| **Profiles** | One counter per person: each profile keeps its own counts, chest types and video source (e.g. a streamer's Twitch link). One counts at a time; OBS always shows the selected one |
| **Chest types** | The line under the numbers splits the total into Chest / Rare chest / Sprite chest / unknown type. A label only - the two counts and OBS are unchanged |
| **Livestream URL and screens first** | The Video source list now starts with the two inputs most people use - a livestream link and a screen - followed by OBS Virtual Camera. Livestream URL is no longer marked experimental |

### Detection, measured

Every chest the user marked as missed in v0.2.1 recordings became a permanent test case (11 real cases, 28 chests checked
by eye, from three streams). On those cases v0.2.1 found 20 of 28 chests and counted 3 chests twice; v0.2.2 finds all 28,
with no double count and nothing false. On the reference recordings (English and PS5 Portuguese, original and at
streaming bitrates) every decision is unchanged. Replaying a 25-minute stream session with both versions: 3 double counts
removed, 1 missed chest found, every difference checked on the video. Cost: about 1 ms more per analysed picture.

Chests found only on a smaller or larger HUD, and the X2 / X3 steps of a pop-up, count in **APPROX only** (never CERTAIN).
A new "... CHEST" line added to a pop-up counts like any chest pop-up.

### Profiles

Dashboard > **Profile**: **New profile...**, **Rename...**, **Delete...**. Your existing counts become the **Default** profile -
nothing to do. Switching is possible while not counting; the OBS text file then shows that profile's numbers (the OBS
source itself never changes). A deleted profile's counts are kept as a backup in `state\profiles\deleted\`.

### Chest types

Read from each counted chest's own pop-up line: **Chest**, **Rare chest**, **Sprite chest**, or **unknown type** when the
line could not be read reliably - an unreadable chest is never assumed to be a normal one. On the test cases every typed
chest was right (28 of 28); on the English reference clip 5 of 6 were typed and 1 stayed unknown. Chests counted before
v0.2.2, or set with Edit counts, show as *not classified* - no history is made up. English pop-ups only. Per profile;
Reset clears it. OBS shows only the two totals, as before.

### Choosing the video source

| Video source | Good to know |
|---|---|
| **Livestream URL** (Twitch / YouTube) | Paste the link. Tested for hours (a 3-hour session counted about 500 chests). Video can arrive in bursts or buffer; the app reconnects by itself and keeps the counts |
| **Screen 1 / Screen 2** | Play the stream, video or game **fullscreen** there. A small player inside a web page is too small to read |
| **OBS Virtual Camera** | Your own stream's OBS scene, on one PC or a second PC fed over SRT - fully supported |
| Capture device / OBS projector | Marked *less tested*: not yet tried with a physical capture card or a real OBS projector |

### Known limitations

- APPROX is an estimate; CERTAIN is the conservative number.
- HUD sizes other than normal, about 1.3x larger and about 0.8x smaller are untested; Portuguese pop-ups are recognised on a
  normal HUD only, and Portuguese stacked pop-ups are untested.
- Chest types: English only; the rare / sprite split is based on a small number of streams.
- Livestream URL counts what viewers get - video the platform never delivered (outages, ad breaks) cannot be counted.
- **Fair play:** the app only analyses video pixels and never touches Fortnite. In one developer session it analysed a
  livestream on the same PC while Fortnite was being played without a BattlEye interruption - one observation, not a
  guarantee; anti-cheat compatibility has not been officially verified. See the README's *Fair play and compatibility*.

### Updating from v0.2.1

Close the app, extract the new zip **into the same folder** and replace the files - counts, settings, profiles and OBS
sources keep working (or copy `state\` and `config.toml` to a new folder). Detection, profiles and types need nothing set up.

**Full details:** [README](https://github.com/GabrielGzS/fortnite-visual-chest-counter#readme) ·
[investigation and measurements](https://github.com/GabrielGzS/fortnite-visual-chest-counter/blob/main/docs/INVESTIGATION_2026-11-08.md)

Independent, unofficial project: not affiliated with, endorsed by or approved by Epic Games. "Fortnite" is a trademark of
Epic Games, Inc. MIT licence. Developed and tested during Fortnite Chapter 7 Season 5 (November 2026).
