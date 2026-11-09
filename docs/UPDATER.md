# The built-in updater

Internal / developer note. Signing keys are covered in [UPDATE_SIGNING.md](UPDATE_SIGNING.md).

**Current state (v0.2.3):** the whole updater is built, including the app's window controls and settings, and passes the automated tests
on small synthetic installations. Both production public keys are in the trust list. It ships as **experimental**.

**Unverified, not passed.** The project has no users yet, so on 2026-11-09 the real-package checks were postponed to v0.2.4 development:

- A complete update of a real package, and the other four scenarios under "Checking with a real package": automatic rollback, crash
  recovery, damaged data and chained updates.
- The deliberate-breakage check of the install and rollback code.
- Whether the temporary update helper runs under Smart App Control.
- The effect on counting while an update downloads and is prepared.

The only attempt at a real packaged update, in M3, hit real bugs and then a Windows crash. Those bugs were fixed and have only been tested
on small installations. The cause of one intermittent `disk_error` while preparing was never established; `.update\prepare.log` now records
it. v0.2.3's own code performs the update to v0.2.4, so a defect in it cannot be fixed by the v0.2.4 package, and v0.2.4 may need a manual
install.

## In the app

Shortly after opening, the app checks for a new version in the background, unless that is turned off in Settings > Updates. A failed
automatic check says nothing. Nothing is downloaded or installed without the user asking.

| Step | What the user sees |
|---|---|
| A verified newer release exists | A small "Update available" link in the sidebar. Nothing pops up |
| Link or manual check | Version, release notes, **Download & Install**, **Later** |
| Preparing | Stage, percentage, sizes, speed and Cancel. Counting continues, and the window can be closed |
| Ready | **Restart & Install**, with confirmation first if counting is active |
| After the restart | One notice: updated, rolled back, or needs attention |

Installation is refused if counting does not stop cleanly, if another window or diagnostics is still open, or if `begin_install`
refuses. In every case the app stays open and usable. A success notice needs a commit recorded for the version that is running.

Speed settings are in the "Download speed" table below. The `[update]` section of `config.toml` holds them, and an update never
touches that file.

## Preparing an update

Checking for updates may happen automatically. Downloading only starts when the user asks for it. All of this runs while the
app keeps counting, and everything is written inside `.update\` in the program folder:

| Path | What it is |
|---|---|
| `download\NAME.zip.part` and `.part.json` | An unfinished download, and which signed file it belongs to |
| `download\NAME.zip` | A download whose size and SHA-256 matched the signed manifest |
| `new.partial\` | Being unpacked; never trusted, and removed on the next attempt |
| `new\` | The unpacked program files |
| `selftest\` | Reports from the start-up checks |
| `staged.json` | Written last: the package passed everything |

The order is fixed: verify the zip against the signed manifest, inspect every entry, unpack, compare with the zip, run the
start-up checks, compare with the zip again, write `staged.json`. A package marked ready is compared with the zip again before
it is used.

The start-up checks run the staged Python, which uses `.update\new` as its program folder because it finds that folder from its
own location. Their reports must confirm that folder, so a check cannot pass by looking at the live installation.

## Download speed

| Mode | While counting | While idle |
|---|---|---|
| Adaptive (default) | About 1 MB/s (`ADAPTIVE_COUNTING_LIMIT`) | No limit |
| Unlimited | No limit | No limit |
| Custom | The chosen limit | The chosen limit |

The limit is re-read for every chunk, so it follows counting starting or stopping. Adaptive is based only on whether the app is
counting. It does not measure the connection, and 1 MB/s is 8 Mbit/s, which is more than a slow connection has. Measure before
making it network-aware.

## What is kept after a problem

| Problem | Kept |
|---|---|
| Cancelled, or a network failure | The partial download, to resume |
| The download fails its checksum | Nothing. If it was resumed, it restarts from zero once first |
| Unsafe or damaged package | Nothing: it can never become valid |
| Start-up check or disk failure | The verified zip, so a retry need not download it again |

## Installing

`install.begin_install()` runs in the app after the user confirms and counting has stopped. It checks everything that can refuse the
update while nothing has changed: the signature again with the installed keys, every staged file, folder permissions and links, free
space, and that `runtime\` holds nothing the release did not put there. It then writes the journal and starts the helper, and the app
closes.

The helper (`install_helper.py`) is the **installed** version's own code, standard library only, running on a private copy of the
official Python in `.update\helper`. Nothing from the new package runs until the new version is started to prove itself, so a broken
release cannot damage the code that has to undo it.

| Journal phase | What has happened |
|---|---|
| `prepared` | Checks passed. Nothing has moved |
| `old_retained` | `runtime\` is now `.update\old\runtime` |
| `new_installed` | The staged runtime is now `runtime\` |
| `awaiting_health` | The new version is starting |
| `committing` | It proved itself: finish, never go back |
| `committed` | Finished; cleaning up |
| `rolling_back`, `rolled_back` | Undoing, and undone |

Before the swap the helper waits for the app and everything running from `runtime\` to exit, compares every staged file with the zip,
and copies the user's small data files. The other program files (launcher, guide, licences) are replaced only after the commit, so a
rollback never has to restore them.

### What counts as started

The helper starts the new version with `--update-health REPORT NONCE`. Once its window has been up for two seconds the app writes a
report naming the nonce, its version, its process id and its program folder. The nonce is new for every installation, so an old or
forged report cannot pass. The process existing proves nothing. There is a 3-minute deadline.

### Recovery

A journal and a folder rename cannot happen as one step, so recovery looks at which folders exist as well as the phase. On every start
the launcher checks for a journal, and if there is one it runs the helper's `recover` using the helper's own Python, so recovery works
even if the new runtime cannot start.

| Found on the next launch | Result |
|---|---|
| `prepared`, nothing moved | Abandoned; the prepared package is kept for another try |
| Any uncommitted phase with the old runtime retained | The old runtime is restored |
| `awaiting_health` with a valid report | The update completes: the new version did prove itself |
| `committing` or `committed` | The commit finishes |
| Unreadable journal | Treated as uncommitted, never as success |

Recovery can be interrupted and run again from any point.

### User data across a rollback

The live files are never touched during the swap. If a new version ran and was rolled back, each small data file is compared with its
pre-update copy. A changed file stays if the old version can read it, because those may be the user's newer numbers. A file the old
version cannot read goes back to the pre-update copy, and the newer one is kept in `state\backups\from-failed-vX-...`. Both are listed
in `.update\result.json`, so nothing is restored silently. After a commit, the pre-update copy is kept in `state\backups\before-vX-...`
(the newest three).

**A release that changes a saved format must not migrate data before its update is committed**, and must update
`_readable_by_this_version` in `install_helper.py` to describe what that release can read.

### Cases that can still need the user

- A file in the program folder stays locked. The launcher says so. Closing the program using it or restarting Windows is enough; no
  folders need renaming.
- Something deletes `.update\helper` during an update **and** the new runtime is in place **and** it cannot start. Without the helper
  the launcher can only restore the old runtime when `runtime\` is missing. Extracting the release zip over the folder repairs it.
- Both `runtime\` and `.update\old\runtime` are deleted from outside, or the disk itself fails. The user's data stays in place;
  extracting the zip repairs the program.
- The launcher program itself is deleted or damaged.

## Brief file locks

On Windows, a file another program has open can refuse to be renamed or replaced, and a folder refuses while any file inside it is
open. Antivirus and the search indexer do this to freshly written files, so every rename and replace waits out that one error for a
limited time: about 5 seconds for small files, about 30 seconds for a finished zip or unpacked folder. If the lock stays, the
operation fails without changing anything, and the real cause goes to `.update\prepare.log` or `.update\install.log`.

A journal that stays locked is not treated as damaged: the launcher says so and leaves everything for the next start.

## Checking with a real package

The automated tests use small installations. A real package still has to pass `tests/update_e2e.py`, which is manual and demanding.

**Run it on a stable PC, one scenario at a time, while nothing is counting.** Security software stays on.

1. Once, on a PC with this repository: `python tests/update_e2e.py make-kit --base <built folder> --out C:\fcc-kit`. This copies the
   build once and packs three variations. It holds a test private key, so it must be outside the repository.
2. Copy the kit to the test PC if needed. Nothing else needs installing.
3. Run one scenario: `C:\fcc-kit\base\<build>\runtime\python\python.exe C:\fcc-kit\update_e2e.py run healthy`
4. Read the printed result, also saved in `C:\fcc-kit\runs\<scenario>\report.txt`. Stop at the first failure or any sign of instability.

The tool enforces the order below: a scenario refuses to run until every earlier one has a passing report. Each report also states the
Smart App Control state and how many files from the kit Windows blocked during the run. Any block fails the scenario. The tool only
reads this information and never changes a security setting.

| Order | Scenario | What it proves |
|---|---|---|
| 1 | `healthy` | Real download, staging, swap, Qt window health report and commit; the OBS text still shows the saved counts |
| 2 | `failed-start` | A real new version that will not start is rolled back, the old one reopens, and the OBS text still shows the saved counts |
| 3 | `crash-after-swap` | The helper dies with the new runtime in place, the real launcher restores the old version, and the OBS text still shows the saved counts |
| 4 | `damaged-data` | Saved data the old version cannot read is restored, and the newer file is kept |
| 5 | `chained` | An updated copy can install the next update with its own helper |

Each scenario does one real unpack of about 400 MB, so leave a few minutes between them. A real app window opens during each one.

Run these on a PC with Smart App Control on as well, with no exceptions or bypasses. The temporary helper uses a copy of the official
signed Python from `.update\helper`, and that has to work there too. It is the one part of the update path that PC has not run yet.

## The package contract

These rules ship inside each installed version, so **a later release must satisfy them or older copies will refuse it**:

- Asset names: `Fortnite-Visual-Chest-Counter-vX.Y.Z.zip`, `update-manifest.json`, `update-manifest.json.sig`.
- One root folder, `Fortnite-Visual-Chest-Counter-vX.Y.Z/`, containing files only, with no folder entries.
- At the root, only `ROOT_FILES` in `archive.py`. **New program files must go under `runtime/`.**
- Placeholders are limited to `state/README.txt`, `logs/README.txt` and `obs_output/*.txt`. They are never unpacked.
- `REQUIRED_FILES` in `archive.py` must exist, and `version.py` must keep its `__version__ = "X.Y.Z"` line.
- The staged Python must be able to run the check in `staging.py` (`fortnite_chest_counter.counter`, `paths.missing_templates`,
  `paths.ffmpeg_executable`, `Crypto.Signature.eddsa`, `update.trust`) and `gui --self-test` with its report fields.
- A new version with no trusted update keys is refused, because it could never update again. It must also ship
  `runtime/package-files.json` (written by the release build), `update.install_helper`, and report `update_health` in its self-test.
- `gui --update-health REPORT NONCE` must keep writing the health report once the window is up.
- The launcher must keep running the helper's `recover` when `.update\transaction.json` exists.
