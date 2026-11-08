# Setup guides

Every setup ends the same way: the app reads a video picture (usually **OBS Virtual Camera**) and writes the numbers to a
text file that an OBS Text source shows on stream. Pick the guide for how Fortnite reaches the app:

| Your setup | Guide | Tested |
|---|---|---|
| Fortnite and OBS on one PC | [Single PC](obs-single-pc.md) | Yes |
| Gaming PC + streaming PC on the same network, **no capture card** | [Dual PC over the network (SRT)](obs-dual-pc-srt.md) | **Yes** - 2026-11-07, v0.2.0 |
| Console or gaming PC + capture card + streaming PC | [Capture card](capture-card.md) | Counter side yes; not yet with a physical card |
| Capture card **owned by OBS** and **Virtual Camera used by another program** | [OBS projector window](obs-projector.md) | Window capture yes (stand-in window); not yet with a real OBS projector |
| A video file | [Recorded video](recorded-video.md) | Yes |

Then: [show the numbers on stream](obs-overlay.md) · [troubleshooting](troubleshooting.md).

Start with the [README](../../README.md) for what the app does, the two numbers and the download.
