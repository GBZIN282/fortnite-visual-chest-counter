# Video input options for professional streamers (feasibility audit, Nov 2026)

> **Update (v0.2.1, 2026-11-08):** option **A is implemented** as the `window` source ("OBS projector" in the app's Video
> source list): `gfxcapture=hwnd=...:capture_cursor=0:max_framerate=30:resize_mode=scale_aspect,hwdownload,format=bgra`
> plus a centred 16:9 crop (an OBS projector letterboxes non-16:9 windows). Measured with a stand-in window (ffplay playing
> the PS5 test clip) through the real `live --gui` worker and the shipped FFmpeg: 1280x720, 15.0 pictures per second,
> 0 dropped, every chest the file pipeline counted on that segment also counted; a window behind other windows keeps
> working; a **minimized** window gives black pictures (no FFmpeg error - the worker watches the window and warns); a
> **closed** window can leave FFmpeg waiting without frames (the worker stops itself with a message). Still open: a real
> OBS projector with a physical capture card, OBS running as administrator, OBS's main window minimized, 125-150 % scaling.
> Option **C** (WebSocket screenshots) was measured offline and deferred - see [ROADMAP.md](ROADMAP.md) v0.2.1.

Requirement: a streamer can connect the counter to gameplay **OBS already captures**, without disturbing OBS, without
occupying OBS Virtual Camera, and without opening the capture card a second time. Detector and v0.1.0 release unchanged.

**Proven** = run on the development PC (Windows 11, OBS 33.0.1). **Theoretical** = from documentation / design, not run.

## What was measured

- The counter's `device` mode opens any DirectShow video device by name without OBS. Elgato Virtual Camera: connected,
  15 fps, 0 dropped. It came up at its **default 960x540** although the device offers 1920x1080, because v0.1.0 does not
  request a format. *(proven, virtual camera only - no physical capture card was available)*
- Device names can contain look-alike characters (Elgato: `EƖgato`, U+0196); copy-paste works, typing does not. *(proven)*
- FFmpeg's `gfxcapture` source (Windows Graphics Capture: one window, no cursor, no yellow border, any GPU-rendered app) is
  present in the FFmpeg bundled with v0.1.0 and captured a GPU-rendered window on this PC (62 frames, real content).
  A **minimized** window cannot be captured (`Capture window is iconic, no client area`). *(proven)*
- OBS 33 ships obs-websocket; on this PC the server is **disabled** (default) and requires a password. *(observed)*

## Comparison

| | Approach | Setup for users | Extra software | Virtual Camera stays free | OBS + counter together | Overhead | Quality / latency | Survives OBS updates | Fits FFmpeg/DirectShow pipeline | Work to build | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | **OBS Windowed Projector + Windows Graphics Capture** | 2 steps: open a projector of the gameplay source, pick it in the counter | none | yes | yes - OBS keeps the card | low (OBS draws one extra view; GPU copy) | full quality, ~1-2 frames | projector feature unchanged for years | yes: one new FFmpeg input (`gfxcapture`) | small | mechanism proven; with an OBS projector not yet tested |
| B | Fullscreen projector on a 2nd monitor + desktop capture | 2 steps | none | yes | yes | low-moderate (gdigrab; `ddagrab` would be lighter) | full quality | yes | yes - **works in v0.1.0** (`source = "desktop"`) | none | desktop mode proven; projector not tested |
| C | OBS WebSocket `GetSourceScreenshot` polling | enable WebSocket server in OBS + password; pick a source by name (best UX) | none (built into OBS 28+) | yes | yes | **unknown, likely significant**: OBS renders + encodes every frame on request (PNG slow, JPG lossy, BMP ~3.7 MB/frame base64) | JPG artifacts unless PNG/BMP | API stable (v5) | no - needs a WebSocket client | medium | theoretical; designed for screenshots, not 15 fps streams |
| D | Capture card directly (`source = "device"`) | edit `config.toml` | none | yes | **often no**: many drivers allow one program | low | device default format (can be < 720p) | n/a | yes - **works in v0.1.0** | none (picker + format: small) | proven with virtual cameras only |
| E | OBS plugins: NDI (DistroAV), Spout2 + SpoutCam, or our own plugin | install plugin(s) + configure | yes | yes | yes | NDI: encode CPU; Spout: very low | high | depends on 3rd-party plugin; own plugin must track OBS releases | Spout2+SpoutCam: yes (it is a DirectShow camera); NDI: no (SDK licence); own plugin: new IPC | high (own plugin) | theoretical |
| F | Capture the Fortnite window directly (single PC, `gfxcapture`) | pick the game window | none | yes | yes - OBS not involved | low | game's own pixels | n/a | yes | small | theoretical; fails for exclusive fullscreen, sees in-game overlays |

## Recommendation

**Primary for v0.1.1: A - capture an OBS Windowed Projector with Windows Graphics Capture.**
It is the only option that meets every requirement with no extra software, no second monitor, the Virtual Camera left
free and the card opened only by OBS, and it slots into the existing FFmpeg pipeline (one new input type). The projector can
sit behind other windows; it must not be minimized.

**Fallback: B (fullscreen projector on a second monitor)** - already works in v0.1.0 and is documented in the README. Keep
**OBS Virtual Camera** as the simplest default, and **D** as the advanced no-OBS path.

**Later, only if needed:** C for *discovering* sources by name (not for frames) once its OBS-side cost is measured; E (own
plugin) if users ask for a fully integrated experience.

## v0.1.1 implementation plan (input layer only; detector stays frozen)

1. **`window` source**: `gfxcapture` by window handle (`capture_cursor=0`, `max_framerate=30`) -> existing scaling and
   latest-frame reader. Match OBS projectors by executable + window class, not by title (OBS titles are translated).
   Friendly messages for "projector closed" and "projector minimized"; reconnect automatically when it reappears.
2. **`Select Video Source.bat`**: numbered list - OBS Virtual Camera, open OBS projector windows, capture devices (with their
   best mode), monitors. Writes the choice into `config.toml` (creating it, keeping other settings).
   `Start Chest Counter.bat` then just works.
3. **Device format request** for `device` mode: prefer 1280x720 @ 30 fps, then 1920x1080 @ 30 fps, else the device default;
   optional `video_size` / `framerate` overrides. Never request 4K or 60 fps by default (the detector uses 1280x720 @ 15 fps).
4. **"Device in use" message**: recognise FFmpeg's busy-device errors and explain that OBS holds the card, with option A/B.
5. **Validation before calling it supported**: projector covered / on another monitor / 125-150 % display scaling;
   Windows 10 and 11; one USB (UVC) and one PCIe capture card, alone and while OBS uses them; CPU/GPU cost vs v0.1.0;
   rc1 detector baselines unchanged.
