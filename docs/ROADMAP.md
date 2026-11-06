# Roadmap

## v0.1.0 - Public Beta (released)

Detector frozen at the `rc1` baselines (`tests/baselines/*_rc1.json`).

## v0.1.1 - presentation (in preparation)

No detection changes. Notes: [RELEASE_NOTES_v0.1.1.md](RELEASE_NOTES_v0.1.1.md).

- Customisable overlay text (`certain_text`, `approx_text`, `{count}` / `{certain}` / `{approx}`), `show` mode, and the
  single `chest_counter.txt` overlay file. v0.1.0 settings and file names keep working.
- Colour-coded console with `minimal` / `normal` / `debug` verbosity.
- In-zip guide updated with the other video inputs.

## v0.1.2 candidates - video inputs (not implemented yet)

Input layer only; the detector stays frozen. Rationale and measurements: [INPUT_OPTIONS.md](INPUT_OPTIONS.md).

1. **Video source picker** - `Select Video Source.bat`: choose OBS Virtual Camera, an OBS projector window, a capture device
   or a monitor from a numbered list; writes `config.toml` so nobody has to edit it or type device names.
2. **OBS projector window capture** (Windows Graphics Capture via FFmpeg `gfxcapture`): uses gameplay OBS already captures,
   leaves the Virtual Camera free, opens the capture card only once (in OBS), needs no plugin or second monitor.
3. **Explicit capture format for capture cards**: prefer 1280x720 @ 30 fps, then 1920x1080 @ 30 fps, else the device
   default; user overrides `video_size` / `framerate`. Avoid 4K / 60 fps (the detector uses 1280x720 @ 15 fps).
4. **Clear "device in use" message** when OBS (or another app) already holds the capture card.
5. **Tell identical capture cards apart** (DirectShow alternative names).

Validation required before release: see the checklist at the end of [INPUT_OPTIONS.md](INPUT_OPTIONS.md).

## Later

- OBS WebSocket for source discovery (after measuring its cost on OBS).
- Own OBS plugin for a fully integrated "pick your gameplay source" experience, if users ask for it.
- More Fortnite languages (needs a pop-up word template per language).
- Accuracy: validate the blurred second trigger (see [ACCURACY_NOTES.md](ACCURACY_NOTES.md)) with labeled live sessions.
