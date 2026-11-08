# The built-in updater

Internal / developer note. Signing keys are covered in [UPDATE_SIGNING.md](UPDATE_SIGNING.md).

**Current state:** the app does not call this code yet. Finding a release, downloading it, unpacking it and testing it from
staging are built. Replacing the installed program, rollback and the app's window controls are still to come.

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

## The package contract

These rules ship inside each installed version, so **a later release must satisfy them or older copies will refuse it**:

- Asset names: `Fortnite-Visual-Chest-Counter-vX.Y.Z.zip`, `update-manifest.json`, `update-manifest.json.sig`.
- One root folder, `Fortnite-Visual-Chest-Counter-vX.Y.Z/`, containing files only, with no folder entries.
- At the root, only `ROOT_FILES` in `archive.py`. **New program files must go under `runtime/`.**
- Placeholders are limited to `state/README.txt`, `logs/README.txt` and `obs_output/*.txt`. They are never unpacked.
- `REQUIRED_FILES` in `archive.py` must exist, and `version.py` must keep its `__version__ = "X.Y.Z"` line.
- The staged Python must be able to run the check in `staging.py` (`fortnite_chest_counter.counter`, `paths.missing_templates`,
  `paths.ffmpeg_executable`, `Crypto.Signature.eddsa`, `update.trust`) and `gui --self-test` with its report fields.
- A new version with no trusted update keys is refused, because it could never update again.
