# Count a recorded video

Count the chests in a video file with the same detector as live counting. It runs faster than real time and **never changes
your live counter or OBS overlay**. Counting a recording after the match is also the most conservative way to use the
counter ([fair play](../../README.md#fair-play-and-compatibility)).

## Steps

1. Open **Fortnite Visual Chest Counter.exe**.
2. Dashboard -> **Analyse a recording...** -> **Browse...** and choose the video (`.mp4`, `.mkv`, `.mov`, `.avi`, `.flv`,
   `.ts`, `.webm`).
3. Click **Start**. The window shows progress, the time left and every counted chest; you can stop at any time.
4. At the end you get **CERTAIN** and **APPROX** (APPROX is the estimated total and already includes CERTAIN - do not add
   them). **Open results folder** shows the result text files in `video_output\`.

Your Settings (for example **Fortnite language**) apply as in live counting.

## Which videos work well

- Fortnite gameplay filling a **16:9** picture, with the HUD visible in its usual place.
- English or Portuguese (Brazil) pop-ups. A HUD drawn up to about 1.3x larger is recognised for English pop-ups; those chests
  count in APPROX only.
- A clean recording is best (for example an OBS recording of your gameplay scene). Stream recordings work too, but strong
  compression blurs the small pop-up text, so more chests end up in APPROX only.
- No overlays covering the HUD; no 4:3 or vertical video.

## From a terminal

```text
runtime\python\python.exe -m fortnite_chest_counter video "C:\path\to\recording.mp4"
runtime\python\python.exe -m fortnite_chest_counter video "C:\path\to\recording.mp4" --start 120 --until 900
```

`--start` / `--until` limit the analysis to that part of the video (in seconds). Run the commands in the app's folder.

Not the same as **Review captures** (Settings), which replays the app's own diagnostic recordings to improve accuracy:
see [CAPTURE.md](../CAPTURE.md).
