# Development notes

End users: read the top-level [README.md](../README.md) and the setup guides in [guides/](guides/README.md). This file is
for contributors.
The original research log (how the detector was built and validated) is in [DETECTOR_NOTES.md](DETECTOR_NOTES.md).

## Repository layout

```text
src/fortnite_chest_counter/
  counter.py        command line + counting session, OBS text files, state, friendly errors   (entry: main())
  estimator.py      streaming estimator: frames in -> one event per chest, tiering and counting rules
  settings.py       config.toml loading with defaults and validation
  paths.py          where things live (source checkout vs packaged exe)
  version.py        the ONLY place the version is set
  detection/        the clue detectors (visual popup, "container opened" sprite, ammo/prompt evidence,
                    chest-object colour cue, tier fusion). audio.py/predict.py/refine.py are offline research code
                    that the live path imports only for constants.
  input/            video_sources.py: OBS Virtual Camera / capture device / desktop / file via ffmpeg
  gui/              the desktop app (v0.2.0, PySide6): app.py (window, pages, dialogs), worker.py (runs + observes the
                    counting worker), theme.py, assets/ (icon PNGs)
  preview.py        shared-memory picture for the app's optional live preview (no Qt)
  capture.py        optional diagnostic recording of the detector's input + decisions + marks ([capture], CAPTURE.md)
  review.py         `review` command: replay captures through the current detector, compare with live + labels
  progress.py       time-left estimates from measured throughput (Analyse a recording, Review captures)
  update/           built-in updater (v0.2.3): releases.py (GitHub discovery), authenticity.py + trust.py (signed manifest,
                    installed public keys), check.py (one background check). Keys: UPDATE_SIGNING.md
  templates/        runtime detector templates (.npy) - tracked in Git, REQUIRED at runtime
packaging/          build_release.py (embeddable Python + verified numpy/scipy/PySide6 + bundled ffmpeg + launcher + zip),
                    launcher/ (launcher.c, manifest, app.ico), make_icon.py, README.html, notices, licenses/ (LGPL/GPL texts),
                    sign_release.py (update-signing keys and release signatures; maintainer only, never shipped)
tests/              test_basics.py, test_release.py, test_app.py, test_obs.py, test_stream.py (no video or Qt needed; one app
                    test uses samples/ if present; test_obs.py runs a fake OBS WebSocket server, test_stream.py a fake
                    Streamlink, both in-process / local)
research/           offline experiment scripts (not shipped)
docs/               this file + the research log
samples/            LOCAL ONLY, git-ignored: recordings used for regression (~680 MB)
analysis_output/    LOCAL ONLY, git-ignored
```

## Setup

```text
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"      # numpy, scipy, PySide6-Essentials (+ pytest, pefile, pillow, research libs)
.venv\Scripts\python -m fortnite_chest_counter --version
.venv\Scripts\python -m fortnite_chest_counter.gui                 # the desktop app from source
.venv\Scripts\python tests\test_basics.py ; .venv\Scripts\python tests\test_release.py ; .venv\Scripts\python tests\test_app.py ; .venv\Scripts\python tests\test_obs.py ; .venv\Scripts\python tests\test_stream.py
```

Developer switches for the app: `FCC_HOME=<folder>` keeps config/state/logs out of the checkout; `FCC_DEV_VIDEO=<file.mp4>`
(+ `FCC_DEV_VIDEO_START=<seconds>`) adds a "Test video (real time)" entry to the video source list. `--self-test REPORT.json`
builds the real window without showing it, waits for the device scan, saves a screenshot next to the report and exits
(0 = ok) - the packaged `.exe` passes it through, so the whole start chain can be checked on any PC without a visible window.

Python 3.11+. FFmpeg must be on PATH when running from source (the packaged app bundles its own).
When running from source, user data (`config.toml`, `state/`, `logs/`, `obs_output/`) lives in the **current directory**
(or `FCC_HOME`), never inside `src/`.

## Regression on recordings

`samples/` is not in Git. With the recordings present locally (and, for the compressed variants, after
`sh research/make_variants.sh <clip.mp4> analysis_output/variants/<en|ps5>`):

```text
python research/regress.py compare --tag v0.1.0                                  # en + ps5
python research/regress.py compare --tag v0.1.0 --clips en ps5 en_tw6000 en_tw2500 ps5_tw6000 ps5_tw2500 --jobs 6
python research/regress.py compare --tag v0.1.0 --set ROBUST_PROMOTION=False      # try an experiment toggle
```

It diffs every event against the frozen snapshots in `tests/baselines/` (event lists of the original v0.1.0 detector) and exits 1
on a regression (lost real chest, real chest downgraded, verified non-chest newly counted). Current expected results and the
full experiment record: [ACCURACY_NOTES.md](ACCURACY_NOTES.md). **Compare event lists, not just totals. Never tune thresholds
during packaging or refactoring work.**

## Releasing

```text
python -m venv build-venv && build-venv\Scripts\pip install numpy scipy PySide6-Essentials
build-venv\Scripts\python packaging\build_release.py --python-embed python-3.13.17-embed-amd64.zip ^
    --ffmpeg-zip <ffmpeg-win64-lgpl.zip> --ffmpeg-source <ffmpeg-source-COMMIT.tar.gz> --mingw C:\MinGW\bin --out build_out\vX.Y.Z
```

On the development PC the exact inputs of the current builds are kept in `build_out\inputs\` (git-ignored):
`python-3.13.17-embed-amd64.zip` (same archive as v0.1.1, SHA-256 9e35319b...), `ffmpeg-v0.1.1-shipped-win64-lgpl.zip`
(the v0.1.1 ffmpeg.exe, SHA-256 7a1cc6f3...) and `ffmpeg-source-db8537d8cc.tar.gz`; the `.venv` has numpy, scipy and
PySide6-Essentials 6.12.0.

Since v0.2.0 the user opens **one app**, `Fortnite Visual Chest Counter.exe`: a ~70 KB launcher compiled by the build from
`packaging/launcher/launcher.c` (MinGW gcc + windres; icon, version info, asInvoker manifest; `--no-insert-timestamp`, so the
same source gives the same bytes). It only starts `runtime\python\pythonw.exe -m fortnite_chest_counter.gui` in its folder
and exits (missing runtime -> a message box: extract the whole zip). No `.bat`/`.cmd` files ship any more (the audit fails on
them); every command still works as `runtime\python\python.exe -m fortnite_chest_counter <command>`.

* `runtime/python/` - the official python.org *embeddable* distribution of the **same 3.x as the build venv**, unmodified
  except one line (`..\lib`) appended to `python3xx._pth`. Download it with its `.asc` and verify it with Steve Dower's
  Windows release key (fingerprint `7ED1 0B65 31D7 C8E1 BC29 6021 FC62 4643 4870 34E5`, published on python.org).
  The build refuses to continue unless every `.exe/.dll/.pyd` has a valid Authenticode signature (Python Software Foundation
  / Microsoft).
* `runtime/lib/` - our package (only the 5 runtime templates) + numpy + scipy copied from the build venv. Every file is checked
  against its wheel's `RECORD` hash first; `tests` folders are left out; everything is precompiled (`unchecked-hash` pycs).
  The window toolkit is the **PE import closure** of QtCore/QtGui/QtWidgets + the Windows platform plugin from the
  PySide6-Essentials and shiboken6 wheels (19 files, ~42 MB; `QT_FILES` in the build script), RECORD-verified, and the build
  fails unless each binary is signed (The Qt Company; `msvcp140.dll` by Microsoft). `vcruntime140*.dll` comes from the
  embeddable Python (newer than PySide6's). Licences: `runtime/licenses/Qt-NOTICE.txt` + LGPL-3.0/GPL-3.0 texts.
* `runtime/ffmpeg/` - unmodified LGPL FFmpeg; the build reads its id from the binary and checks it against the source archive.
* `runtime/PROVENANCE.txt` - versions, hashes and signers of all of the above, plus a count of signed / unsigned
  executable files. `SIGNATURES.txt` (next to the zip, not in it) lists the signature of every `.exe/.dll/.pyd`: the input
  for code-signing / Smart App Control work (see [WINDOWS_TRUST.md](WINDOWS_TRUST.md)).
* Zip entries are sorted and use a fixed timestamp, so the same inputs give a byte-identical zip. `SHA256SUMS.txt` covers the
  zip and the FFmpeg source archive.

v0.1.0 was built with PyInstaller (see git history); v0.1.1 shipped .bat launchers + the signed official runtime; v0.2.0 adds
the small launcher above (the PyInstaller bootloader was flagged by Defender's cloud ML in v0.1.1; this launcher scans clean
and contains no interpreter). Release checklist: scan the final zip and folder with
`MpCmdRun -Scan -ScanType 3 -File <path> -DisableRemediation`, then from a fresh extraction run
`"Fortnite Visual Chest Counter.exe" --self-test <abs path>\report.json` and open the app once for real.

Release history note: the v0.1.1 zip was refreshed on 2026-11-06 (Configure Counter.bat and clearer overlay setup); the
first v0.1.1 zip (SHA-256 `f7fb4129…`, source `9f90de7`) is kept privately in `build_out/v0.1.1-original/`, and the
`v0.1.1` tag was moved to the source of the refreshed zip.

The build runs a **release audit** that fails on samples, analysis output, logs, a saved counter, non-zero OBS files, script
launchers (.bat/.cmd/.ps1/.vbs/.lnk) or any executable other than the launcher, the official `python.exe`/`pythonw.exe` and
`ffmpeg.exe`. Bump the version only in `version.py`.
`packaging/README.html` (shipped in the zip) and the top-level `README.md` (GitHub) are separate files; keep them consistent.

### What ships

| Category | Files | In the zip? |
|---|---|---|
| Runtime | everything under `src/fortnite_chest_counter/` except unused templates; only 5 `.npy` templates | yes (in `runtime/`) |
| User-facing | the launcher (built from `packaging/launcher/`), `packaging/README.html`, `config.example.toml`, `packaging/LICENSE-NOTICE.txt` | yes |
| Dev / test | `tests/`, `research/`, `docs/`, `pyproject.toml`, `requirements*.txt`, `packaging/build_release.py` | no |
| Sample footage, analysis output, local state | `samples/`, `analysis_output/`, `state/`, `logs/`, `obs_output/` | no (git-ignored) |

## Design points worth knowing

* **The desktop app observes; the worker counts.** The app (`gui/`) never runs the detector. Start counting = it launches
  `python -m fortnite_chest_counter live --gui --preview <block>` (the same `live` command as the console version) with
  CREATE_NO_WINDOW and reads one JSON message per line from its stdout (`console.py` machine mode: `event`, `status`, `counts`,
  `connected`, `stopped`, `info`/`warn`/`error`, ...). Stop = the line `stop` on the worker's stdin; if the app dies, Windows
  closes the pipe and `AppControl` stops + saves the worker the same way. The GIL, a frozen window or a crashed window can never
  cost a frame. Reset / Edit counts write the state file through `set_counts` (same path and log record as the CLI), and the
  running worker adopts them via `sync_external_changes`; the Overlay page writes `config.toml`, which the worker's
  `DisplayConfigWatcher` applies within a second. `tests/test_app.py` proves the app's worker counts exactly the same events
  as the command line on a recording.
* **Diagnostic capture** (`capture.py`, [CAPTURE.md](CAPTURE.md)): off by default; when on, the live loop queues each
  analysed frame (non-blocking, bounded) for a separate FFmpeg encoder writing 10-s segments; events mode deletes segments
  no decision or mark claims. Marks: app `mark` line on the worker's stdin (Mark moment / Ctrl+Alt+M via RegisterHotKey),
  console key M. `review` replays clips with a fresh estimator and compares (MATCH_SECONDS 0.6, as regress.py).
* **Live preview** (`preview.py`): a named shared-memory block. The worker copies a 640x360 picture at most 5x/s, only while
  the app shows the preview (one flag read per frame otherwise), after counting the frame.
* **No console flashes:** a process without a console window (the app, its worker, its diagnostics run) starts ffmpeg with
  CREATE_NO_WINDOW (`paths.child_process_flags`). The console version keeps the v0.1.x behaviour.

* **Count semantics (public contract):** `approximate` is the estimated TOTAL and *contains* `certain`. `CounterSession.apply` adds a
  certain chest to both counts exactly once, an approx-only chest to `approximate` only, and repairs `approximate >= certain` if it were
  ever violated; `load_state` repairs a saved file and `adjust` clamps. Covered by `tests/test_release.py`.
* **User data vs program files:** `paths.APP_DIR` (config, state, logs, obs_output) is separate from `paths.RESOURCE_DIR`
  (templates, ffmpeg). In the packaged app that is the exe folder vs `runtime/`. Updates replace `runtime/` and the exe only.
* **Closing the window (X) is a supported way to stop.** `ConsoleCloseGuard` registers a real console control handler
  (`SetConsoleCtrlHandler`) for CTRL_CLOSE / LOGOFF / SHUTDOWN (and CTRL_BREAK): it stops the frame source, lets the live loop
  persist counts, OBS files and `session_end` (with the real reason, e.g. `window closed (X)`), releases the lock, and only then
  returns so Windows can end the process. Bounded: the handler waits at most 4.5 s (Windows allows ~5 s). Validated by posting
  WM_CLOSE to the launcher's console window, in both conhost and Windows Terminal: lock released ~0.3-0.4 s after the click.
  If Windows kills the process anyway, nothing breaks: counts are saved after every chest, a `status` record is logged every
  5 min, and leftovers (`.tmp`, v0.1.0 `live.lock`) are removed at the next start.
* **One counter per counter file:** `SingleInstance` is a Windows named mutex derived from the state file path. The kernel
  releases it when the process ends, however it ends, so a crash or kill can never block the next start (v0.1.0 used a
  `live.lock` PID file, which could go stale). `counter_is_running()` lets `reset` tell whether a counter window is open.
* **Reset while running:** the app's Reset / Edit counts (or the `reset` / `set-count` commands) are separate writers. The running counter polls the state file's mtime once a second
  (`CounterSession.sync_external_changes`) and adopts the new numbers.
* **Video files:** `video` command = same estimator as live, not persisted, writes to `video_output/`. `simulate` is the developer
  variant with evaluation against verified timestamps.
* **Errors:** expected problems raise `UserError` (plain message, exit 1); unexpected exceptions write `logs/crash_*.txt` (exit 2).
  The console's QuickEdit mode is disabled in `live` (a click would pause the process and stall counting).
* **Finding the program folder:** `paths.APP_DIR` is derived from `runtime\python\` when running the release runtime, so the
  app and the command line work whatever the current directory is. The launcher also starts pythonw by full path.
* **Bundled FFmpeg:** `runtime/ffmpeg/ffmpeg.exe`, found by `paths.bundled_ffmpeg_dir()` and prepended to `PATH` at startup. We ship an **LGPL v3** build (no GPL parts) run as a
  separate process, with its licence and `FFMPEG-NOTICE.txt`. Do not ship a `--enable-gpl` build unless you also offer the complete
  corresponding source. Pin the archive you ship (its SHA-256 is written into the notice).
* **Licences:** the project is MIT (`LICENSE`). The build copies the Python (PSF), NumPy and SciPy (BSD, incl. their bundled
  OpenBLAS/LAPACK/gfortran notices) licence texts into `runtime/licenses/`. Attach the zip, `SHA256SUMS.txt` and
  `ffmpeg-source-<commit>.tar.gz` to the GitHub release (LGPL v3: the corresponding source is offered next to the binary).
  The FFmpeg source for a build: `https://github.com/FFmpeg/FFmpeg/archive/<commit>.tar.gz`.
* **Module names:** avoid naming a module `sources` (it clashed with packaging tools in the past).
