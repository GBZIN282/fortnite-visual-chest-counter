# Windows trust: Smart App Control, SmartScreen and code signing

Internal / developer note (November 2026). User-facing docs deliberately do not talk about security warnings; this file
records what we know so the signing decision can be made on facts.

## What happened

A test PC ("PC B") refused to run v0.1.1. Most PCs, including the development PC, never block it: on the development PC
`Get-MpComputerStatus` reports `SmartAppControlState : Off`. The block on PC B is most likely **Smart App Control** (SAC),
not SmartScreen. The exact file it rejected is still unknown (see "Find the blocked file" below).

## How Smart App Control decides (Microsoft's FAQ)

1. It asks Microsoft's cloud reputation service whether the file is known-safe. Known-safe -> runs; known-bad -> blocked.
2. If the service is not confident, it checks the **Authenticode signature**: valid signature from a trusted CA -> runs;
   unsigned or invalid -> **blocked**.
3. There is **no per-app exception** ("Run anyway" does not exist for SAC). The user can only turn SAC off; recent Windows
   updates allow turning it back on without reinstalling Windows.

SAC is typically only active on clean Windows 11 installs, which explains why most enthusiasts (who run lots of unsigned
tools) never see it. SmartScreen is a different feature: it shows "Windows protected your PC" with **More info -> Run
anyway** for unknown downloads; SAC has no such button.

Why do tools like Fan Control run? Their maintainers sign them (Fan Control's repository says its exe, installer and updater
are signed), and popular files also gain cloud reputation. A new, niche, unsigned file has neither.

SAC evaluates **every** executable file that is loaded - `.exe`, and also each `.dll`/`.pyd` a process loads. Signing only
the file the user double-clicks is not enough. `.bat` files are not directly controlled the same way, but the programs they
start are; the .bat files were probably not what PC B rejected.

## Our package (from the build's SIGNATURES.txt)

| | v0.1.1 | v0.2.0 dev build |
|---|---|---|
| Executable files (.exe/.dll/.pyd) | 159 | 173 |
| Signed: Python Software Foundation / Microsoft | 30 | 31 |
| Signed: The Qt Company (window toolkit) | - | 12 (+1 Microsoft C++ runtime) |
| **Unsigned** | **128** | **129** |
| - launcher `Fortnite Visual Chest Counter.exe` (ours) | - | 1 |
| - `runtime/ffmpeg/ffmpeg.exe` (BtbN LGPL nightly build) | 1 | 1 |
| - numpy (+ OpenBLAS) | 20 | 20 |
| - scipy | 107 | 107 |

The desktop app itself adds only signed Qt files plus our one launcher. The unsigned bulk is ffmpeg and the numpy/scipy
compiled modules from PyPI (PyPI wheels are not Authenticode-signed). Whether SAC trusts the numpy/scipy files by reputation
is unknown; a nightly ffmpeg build almost certainly has no reputation.

## Find the blocked file (PC B, 2 minutes)

Event Viewer -> Applications and Services Logs -> Microsoft -> Windows -> CodeIntegrity -> Operational, entries with
ID 3077 (blocked) / 3033 (signing level). Or in PowerShell:

```powershell
Get-MpComputerStatus | Select-Object SmartAppControlState
Get-WinEvent -LogName 'Microsoft-Windows-CodeIntegrity/Operational' -MaxEvents 500 |
  Where-Object { $_.Id -in 3033, 3077 } | Select-Object -First 20 TimeCreated, Id, Message | Format-List
```

The message names the file that was refused and the process that tried to load it.

## Options

| Option | Cost | Covers | Notes |
|---|---|---|---|
| Do nothing (reputation) | free | nothing predictable | every release is new files with no reputation; niche app |
| [SignPath Foundation](https://signpath.org/) | free for OSS | **our own binaries** (the launcher) | certificate is issued to "SignPath Foundation" (shown as publisher); requires an OSI licence (MIT ok), public repo, builds from CI with origin verification, MFA; they sign only the project's own binaries, so ffmpeg/numpy/scipy stay unsigned |
| [Certum Open Source Code Signing](https://shop.certum.eu/open-source-code-signing-on-simplysign.html) | low (listed from about EUR 49/year; check) | anything we distribute, signed as "Open Source Developer, <name>" | individual developer, cloud key (SimplySign); OV-level, so SmartScreen reputation still builds over time |
| Azure Artifact Signing | about USD 10/month | anything we distribute | eligibility restricted by country/organisation type (not verified for this project) |
| Microsoft Store (MSIX) | free account | Microsoft signs the package | MSIX cannot write next to the program: state/, logs/, obs_output/ would move to the user's folders; OBS file path changes; bigger change |
| Shrink the unsigned surface | free | fewer files to trust | the detector uses SciPy for **one** function (`scipy.signal.fftconvolve`); a NumPy-FFT version would drop all 107 SciPy binaries and ~30 MB. It is a detector change: must pass `research/regress.py compare` event-for-event first |

Signing our launcher alone does not make the package pass SAC while unsigned ffmpeg/numpy/scipy files are loaded. A
complete answer for SAC = a certificate we may use for every file we ship (Certum- or Azure-style; check the CA's terms for
signing redistributed third-party open-source binaries before doing it), or fewer unsigned files plus signing the rest.

## Recommendation

1. Read PC B's CodeIntegrity log first: it tells us which file(s) SAC refuses.
2. Cheap and independent of signing: try replacing `scipy.signal.fftconvolve` with NumPy (only if the regression harness shows
   identical events), which removes 107 of 129 unsigned files.
3. If SAC support matters: an individual open-source certificate (Certum) that can sign the launcher, ffmpeg and the remaining
   numpy files in the build; apply SignPath Foundation in parallel if a CI-built, SignPath-published launcher is preferred.
4. Only mention SAC in user docs if a release still cannot run with it on.
