# Single-PC setup (Fortnite and OBS on the same PC)

```text
Fortnite -> OBS Game Capture -> scene "ChestDetectorFeed" -> OBS Virtual Camera
         -> Fortnite Visual Chest Counter -> obs_output\chest_counter.txt -> OBS Text source on your stream scene
```

You need Windows 10 / 11, **OBS Studio 28 or newer** and the app extracted from its ZIP ([download](../../README.md#download)).

> **Fair play:** this runs the counter on the same PC as Fortnite. That works, but its compatibility with Fortnite's
> anti-cheat has not been officially verified. With a second PC, the [dual-PC SRT setup](obs-dual-pc-srt.md) keeps the
> counter off the gaming PC; counting a [recorded video](recorded-video.md) is the other conservative option.
> Details: [Fair play and compatibility](../../README.md#fair-play-and-compatibility).

## 1. Create the detector scene

1. Open OBS Studio.
2. In the **Scenes** box click **+** and name the scene `ChestDetectorFeed`.
3. In the **Sources** box click **+** -> **Game Capture** -> OK. Set **Mode** to **Capture specific window** and choose
   Fortnite (start Fortnite first so it appears in the list). If the preview is black, use **Display Capture** instead.
4. Make Fortnite fill the whole scene: select the source and press `Ctrl+F` (Fit to screen).

Do **not** add to this scene: webcam, alerts, chat, the counter's own text or other stream graphics. Use a 16:9 canvas
(1920x1080 is ideal). Your stream scene is not affected - the counter only sees `ChestDetectorFeed`.

## 2. Start the Virtual Camera from that scene

1. In the **Controls** box (bottom right) click the **gear** next to **Start Virtual Camera**.
2. Set **Output Type** = **Scene** and **Output Selection** = **ChestDetectorFeed**. Close the dialog.
3. Click **Start Virtual Camera**.

## 3. Start counting

1. Open **Fortnite Visual Chest Counter.exe**.
2. On the **Dashboard** the video source is already **OBS Virtual Camera**. Click **Start counting**.
3. The status turns to **Counting**; the line under the source shows the picture size and how many pictures per second are
   analysed (about 15).
4. Turn on **Live preview** once to check that the counter sees the full game picture with the HUD.

Leave the app open (minimised is fine). Stop with **Stop counting** or by closing the app (it asks first). Numbers are saved
after every chest and kept between sessions. If a red message says `OBS Virtual Camera was not found`, follow the steps it
shows.

## 4. Show the numbers on stream

Add one OBS Text source that reads `obs_output\chest_counter.txt`: [OBS overlay guide](obs-overlay.md).

## Counting a stream or video you are watching

The counter only needs the picture, so it can also count chests in someone else's livestream or a video playing in your
browser. Easiest, without OBS: paste the stream's link ([Livestream URL](livestream-url.md)) or play it fullscreen and pick
that [screen](screen-capture.md). Through OBS:

- In `ChestDetectorFeed`, use **Display Capture** with the video playing full screen, or **Window Capture** of the browser
  cropped to just the video (hold `Alt` while dragging the source's edges).
- The counter must see only the 16:9 gameplay: no chat, page, player controls or other windows on top.
- If a browser Window Capture is black, set its **Capture Method** to **Windows 10 (1903 and up)**.

Have the video as a file? [Analyse it directly](recorded-video.md) - faster than real time, no OBS needed.

## Virtual Camera already used by another program?

Use an **OBS projector window** instead: in OBS right-click the gameplay source -> **Windowed Projector (Source)**, then
pick **OBS projector: ...** in the app's **Video source** list (click **Refresh** first). The window may stay behind other
windows, but not minimized. Full steps: [OBS projector window](obs-projector.md). OBS keeps the Virtual Camera for the
other program.

Alternative: **Fullscreen Projector (Source)** on a spare 16:9 monitor, then pick that **Screen** in the Video source list
(keep other windows off that monitor). *(Not yet tested.)*

Problems: [troubleshooting](troubleshooting.md).
