# Development notes

End users: read the top-level [README.md](../README.md). This file is for contributors.
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
  templates/        runtime detector templates (.npy) - tracked in Git, REQUIRED at runtime
packaging/          build_release.py (embeddable Python + verified numpy/scipy + bundled ffmpeg + zip), README.html, notices
tests/              test_basics.py, test_release.py (no video needed)
research/           offline experiment scripts (not shipped)
docs/               this file + the research log
samples/            LOCAL ONLY, git-ignored: recordings used for regression (~680 MB)
analysis_output/    LOCAL ONLY, git-ignored
```

## Setup

```text
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"      # numpy, scipy (+ pytest, pyinstaller, and the research libs)
.venv\Scripts\python -m fortnite_chest_counter --version
.venv\Scripts\python tests\test_basics.py ; .venv\Scripts\python tests\test_release.py     # or: pytest
```

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
python -m venv build-venv && build-venv\Scripts\pip install numpy scipy
build-venv\Scripts\python packaging\build_release.py --python-embed python-3.13.17-embed-amd64.zip ^
    --ffmpeg-zip <ffmpeg-win64-lgpl.zip> --ffmpeg-source <ffmpeg-source-COMMIT.tar.gz> --out build_out\vX.Y.Z
```

The Windows release contains **no self-built executable** (since v0.1.1). The `.bat` launchers run
`runtime\python\python.exe -m fortnite_chest_counter <command>`:

* `runtime/python/` - the official python.org *embeddable* distribution of the **same 3.x as the build venv**, unmodified
  except one line (`..\lib`) appended to `python3xx._pth`. Download it with its `.asc` and verify it with Steve Dower's
  Windows release key (fingerprint `7ED1 0B65 31D7 C8E1 BC29 6021 FC62 4643 4870 34E5`, published on python.org).
  The build refuses to continue unless every `.exe/.dll/.pyd` has a valid Authenticode signature (Python Software Foundation
  / Microsoft).
* `runtime/lib/` - our package (only the 5 runtime templates) + numpy + scipy copied from the build venv. Every file is checked
  against its wheel's `RECORD` hash first; `tests` folders are left out; everything is precompiled (`unchecked-hash` pycs).
* `runtime/ffmpeg/` - unmodified LGPL FFmpeg; the build reads its id from the binary and checks it against the source archive.
* `runtime/PROVENANCE.txt` - versions, hashes and signers of all of the above.
* Zip entries are sorted and use a fixed timestamp, so the same inputs give a byte-identical zip. `SHA256SUMS.txt` covers the
  zip and the FFmpeg source archive.

v0.1.0 was built with PyInstaller (see git history). Since v0.1.1 the release ships the signed official runtime instead of
an unsigned, self-built launcher executable. Release checklist: scan the final zip and folder with
`MpCmdRun -Scan -ScanType 3 -File <path> -DisableRemediation`, then run the packaged app from a fresh extraction.

Release history note: the v0.1.1 zip was refreshed on 2026-11-06 (Configure Counter.bat and clearer overlay setup); the
first v0.1.1 zip (SHA-256 `f7fb4129…`, source `9f90de7`) is kept privately in `build_out/v0.1.1-original/`, and the
`v0.1.1` tag was moved to the source of the refreshed zip.

The build runs a **release audit** that fails on samples, analysis output, logs, a saved counter, non-zero OBS files or any
executable other than the official `python.exe`/`pythonw.exe` and `ffmpeg.exe`. Bump the version only in `version.py`.
`packaging/README.html` (shipped in the zip) and the top-level `README.md` (GitHub) are separate files; keep them consistent.

### What ships

| Category | Files | In the zip? |
|---|---|---|
| Runtime | everything under `src/fortnite_chest_counter/` except unused templates; only 5 `.npy` templates | yes (in `runtime/`) |
| User-facing | `packaging/README.html`, `packaging/launchers/*.bat`, `config.example.toml`, `packaging/LICENSE-NOTICE.txt` | yes |
| Dev / test | `tests/`, `research/`, `docs/`, `pyproject.toml`, `requirements*.txt`, `packaging/build_release.py` | no |
| Sample footage, analysis output, local state | `samples/`, `analysis_output/`, `state/`, `logs/`, `obs_output/` | no (git-ignored) |

## Design points worth knowing

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
* **Reset while running:** `Reset Counter.bat` is a separate process. The running counter polls the state file's mtime once a second
  (`CounterSession.sync_external_changes`) and adopts the new numbers.
* **Video files:** `video` command = same estimator as live, not persisted, writes to `video_output/`. `simulate` is the developer
  variant with evaluation against verified timestamps.
* **Errors:** expected problems raise `UserError` (plain message, exit 1); unexpected exceptions write `logs/crash_*.txt` (exit 2).
  The console's QuickEdit mode is disabled in `live` (a click would pause the process and stall counting).
* **Launchers call the exe by full path** (`"%~dp0..."`). Never rely on the current directory: some systems set
  `NoDefaultCurrentDirectoryInExePath`.
* **Bundled FFmpeg:** `runtime/ffmpeg/ffmpeg.exe`, found by `paths.bundled_ffmpeg_dir()` and prepended to `PATH` at startup. We ship an **LGPL v3** build (no GPL parts) run as a
  separate process, with its licence and `FFMPEG-NOTICE.txt`. Do not ship a `--enable-gpl` build unless you also offer the complete
  corresponding source. Pin the archive you ship (its SHA-256 is written into the notice).
* **Licences:** the project is MIT (`LICENSE`). The build copies the Python (PSF), NumPy and SciPy (BSD, incl. their bundled
  OpenBLAS/LAPACK/gfortran notices) licence texts into `runtime/licenses/`. Attach the zip, `SHA256SUMS.txt` and
  `ffmpeg-source-<commit>.tar.gz` to the GitHub release (LGPL v3: the corresponding source is offered next to the binary).
  The FFmpeg source for a build: `https://github.com/FFmpeg/FFmpeg/archive/<commit>.tar.gz`.
* **Module names:** avoid naming a module `sources` (it clashed with packaging tools in the past).
