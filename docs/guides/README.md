# Setup guides

Every setup ends the same way: the app reads a video picture and keeps the count (and writes it to a text file that an OBS
Text source can show on stream). Most people need one of the first two guides - no OBS needed:

| What you want to count | Guide | Tested |
|---|---|---|
| **A Twitch or YouTube livestream** (yours or anyone's) - paste the link | [Livestream URL](livestream-url.md) | **Yes** - incl. a 3-hour session, 2026-11-08 |
| **Anything on a screen** - a stream or video playing fullscreen, or your own game | [Screen](screen-capture.md) | **Yes** - 2026-11-08 |
| Your own stream: Fortnite and OBS on one PC | [Single PC with OBS](obs-single-pc.md) | Yes |
| Gaming PC + streaming PC on the same network, **no capture card** | [Dual PC over the network (SRT)](obs-dual-pc-srt.md) | **Yes** - 2026-11-07, v0.2.0 |
| A video file | [Recorded video](recorded-video.md) | Yes |
| Console or gaming PC + capture card + streaming PC | [Capture card](capture-card.md) | *Less tested:* counter side yes; not yet with a physical card |
| Capture card **owned by OBS** and **Virtual Camera used by another program** | [OBS projector window](obs-projector.md) | *Less tested:* window capture yes (stand-in window); not yet with a real OBS projector |

Then: [show the numbers on stream](obs-overlay.md) · [troubleshooting](troubleshooting.md).

Start with the [README](../../README.md) for what the app does, the two numbers and the download.
