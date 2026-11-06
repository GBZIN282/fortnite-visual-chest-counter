"""
Build the Windows release folder + zip.   (Developers only - end users never run this.)

    python packaging/build_release.py --python-embed python-3.13.17-embed-amd64.zip \
        --ffmpeg-zip ffmpeg-win64-lgpl.zip --ffmpeg-source ffmpeg-source-<commit>.tar.gz [--out build_out/vX]

Run it with the Python whose site-packages hold the exact numpy / scipy to ship (same minor version as the embeddable
runtime, e.g. a venv with `pip install numpy scipy`).

The package contains NO self-built executable:
  runtime/python/   the official python.org "embeddable" Python, UNMODIFIED except one added line in python313._pth
                    (every .exe/.dll/.pyd is Authenticode-signed by the Python Software Foundation / Microsoft; checked)
  runtime/lib/      our source code + numpy + scipy (copied from the build environment and verified file-by-file against
                    their wheels' RECORD hashes), precompiled
  runtime/ffmpeg/   unmodified LGPL FFmpeg build (its source archive is attached to the GitHub release)
  *.bat             launchers that run  runtime\\python\\python.exe -m fortnite_chest_counter <command>
User data (state/, logs/, config.toml) is never created by the build, so a release can never carry old counts.
runtime/PROVENANCE.txt records where every component came from and its hashes; the zip is written with fixed timestamps
and sorted entries, so the same inputs produce a byte-identical zip.
"""

import argparse
import base64
import compileall
import csv
import hashlib
import importlib.metadata as md
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from fortnite_chest_counter.version import __version__                   # noqa: E402

PACKAGE = "fortnite_chest_counter"
TEMPLATE_FILES = ["chest/en/chest.npy", "chest/pt/bau.npy", "container_opened.npy", "ui/interaction_disc.npy",
                  "ui/interaction_ring.npy"]                    # audio_fingerprint.npy is development-only
THIRD_PARTY = ["numpy", "scipy"]
ZIP_TIME = (2026, 1, 1, 0, 0, 0)                                # fixed timestamps -> reproducible zip
LAUNCHERS = {                                                   # file -> (window title, command, extra)
    "Start Chest Counter.bat": ("Fortnite Visual Chest Counter", "live"),
    "Set Starting Count.bat": ("Set Starting Count", "set-count"),
    "Reset Counter.bat": ("Reset Chest Counter", "reset"),
    "Show Counter.bat": ("Show Chest Counter", "show"),
    "Diagnostics.bat": ("Chest Counter Diagnostics", "diagnostics"),
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def authenticode(paths):
    """{path: (status, signer)} via PowerShell Get-AuthenticodeSignature (reads signatures; runs nothing)."""
    script = ("$ErrorActionPreference='Stop'; foreach ($p in $input) { $s = Get-AuthenticodeSignature -LiteralPath $p; "
              "'{0}|{1}|{2}' -f $p, $s.Status, ($s.SignerCertificate.Subject -replace '^CN=([^,]+).*','$1') }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], input="\n".join(map(str, paths)),
                         capture_output=True, text=True, check=True).stdout
    return {Path(p): (status, signer) for p, status, signer in (l.split("|", 2) for l in out.splitlines() if l.count("|") == 2)}


def verify_record(dist):
    """Every file of an installed distribution must still match its wheel's RECORD hash. -> (dist, files checked)."""
    d = md.distribution(dist)
    base = Path(d.locate_file(""))
    checked = 0
    for row in csv.reader(d.read_text("RECORD").splitlines()):
        if len(row) < 2 or not row[1].startswith("sha256="):
            continue
        f = base / row[0]
        want = row[1].split("=", 1)[1]
        got = base64.urlsafe_b64encode(hashlib.sha256(f.read_bytes()).digest()).rstrip(b"=").decode()
        if got != want:
            raise SystemExit(f"{dist}: {row[0]} does not match its wheel RECORD - refusing to ship it")
        checked += 1
    return d, base, checked


def launcher(title, command):
    body = f'''@echo off
setlocal
cd /d "%~dp0"
title {title}
if not exist "%~dp0runtime\\python\\python.exe" (
  echo The program files were not found next to this file.
  echo Please extract the WHOLE zip file first ^(right-click the zip, "Extract All"^), then try again.
  echo.
  pause
  exit /b 1
)
"%~dp0runtime\\python\\python.exe" -m {PACKAGE} {command}
echo.
echo Press any key to close this window.
pause >nul
'''
    return body.replace("\n", "\r\n")


VIDEO_LAUNCHER = r'''@echo off
setlocal
cd /d "%~dp0"
title Count Chests In A Video
if not exist "%~dp0runtime\python\python.exe" (
  echo The program files were not found next to this file.
  echo Please extract the WHOLE zip file first ^(right-click the zip, "Extract All"^), then try again.
  echo.
  pause
  exit /b 1
)
if "%~1"=="" (
  echo To count the chests in a recorded gameplay video:
  echo   drag the video file and drop it ONTO this file ^("Count Video File.bat"^).
  echo.
  echo This does not change your live counter.
  echo.
  pause
  exit /b 0
)
"%~dp0runtime\python\python.exe" -m fortnite_chest_counter video "%~1"
echo.
echo Press any key to close this window.
pause >nul
'''.replace("\n", "\r\n")

COMMAND_LINE_ENTRY = r'''@echo off
rem Command-line entry for advanced use, e.g.:
rem   "Fortnite Visual Chest Counter.cmd" set-count 150
rem   "Fortnite Visual Chest Counter.cmd" live --source desktop --monitor 2
setlocal
set "FCC_HOME=%~dp0"
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" -m fortnite_chest_counter %*
'''.replace("\n", "\r\n")


def audit(app_root):
    """Fail the build if development leftovers or old counts could reach users."""
    problems = []
    bad_names = {"samples", "analysis_output", ".venv", "chest_count.txt", "chest_count_save.txt",
                 "audio_fingerprint.npy", "chest_state.json", "config.toml"}
    third_party = [app_root / "runtime" / "lib" / d for d in ("numpy", "numpy.libs", "scipy", "scipy.libs")]
    for f in app_root.rglob("*"):
        if any(t in f.parents for t in third_party):
            continue                     # verified against the wheels' RECORD (scipy legitimately ships a .npz table)
        if f.name in bad_names or f.suffix in (".mp4", ".wav", ".npz", ".jsonl"):
            problems.append(str(f.relative_to(app_root)))
    if any(f.suffix == ".json" for f in (app_root / "state").iterdir()):
        problems.append("state/ contains a saved counter")
    for name, expected in (("certain_chests.txt", "CERTAIN OPENED CHESTS: 0"), ("approximate_chests.txt", "APPROX. OPENED CHESTS: 0")):
        if (app_root / "obs_output" / name).read_text(encoding="utf-8").strip() != expected:
            problems.append(f"obs_output/{name} is not zero")
    exes = [f.relative_to(app_root) for f in app_root.rglob("*.exe")]
    allowed = {Path("runtime/python/python.exe"), Path("runtime/python/pythonw.exe"), Path("runtime/ffmpeg/ffmpeg.exe")}
    if set(exes) - allowed:
        problems.append(f"unexpected executables: {sorted(map(str, set(exes) - allowed))}")
    if problems:
        raise SystemExit("RELEASE AUDIT FAILED:\n  " + "\n  ".join(problems))
    print("Release audit passed: no samples, logs, saved counts or unexpected executables; OBS files start at 0.")


def build(out, python_embed, ffmpeg_zip, ffmpeg_source):
    app_root = out / f"Fortnite-Visual-Chest-Counter-v{__version__}"
    shutil.rmtree(app_root, ignore_errors=True)
    if app_root.exists():
        raise SystemExit(f"cannot clear {app_root} (a file in it is locked)")
    out.mkdir(parents=True, exist_ok=True)
    runtime = app_root / "runtime"
    provenance = [f"Fortnite Visual Chest Counter v{__version__} - provenance of the bundled components", ""]

    # ---- 1. official embeddable Python, unmodified (one line added to the ._pth so it finds runtime\lib)
    py = runtime / "python"
    with zipfile.ZipFile(python_embed) as z:
        z.extractall(py)
    pth = next(py.glob("python3*._pth"))
    ver = pth.stem.replace("python", "")
    build_ver = f"{sys.version_info.major}{sys.version_info.minor}"
    if ver != build_ver:
        raise SystemExit(f"embeddable Python is {ver} but numpy/scipy come from Python {build_ver}")
    pth.write_text(pth.read_text(encoding="utf-8").rstrip("\n") + "\n..\\lib\n", encoding="utf-8")
    binaries = sorted(p for p in py.iterdir() if p.suffix in (".exe", ".dll", ".pyd"))
    sigs = authenticode(binaries)
    unsigned = [p.name for p in binaries if sigs.get(p, ("?",))[0] != "Valid"]
    if unsigned:
        raise SystemExit(f"embeddable Python files without a valid signature: {unsigned}")
    signers = sorted({s for _, s in sigs.values()})
    provenance += [f"Python runtime  : {Path(python_embed).name} from https://www.python.org/ftp/python/",
                   f"                  archive SHA-256 {sha256(python_embed)}",
                   f"                  {len(binaries)} binaries, all with a valid Authenticode signature by: {', '.join(signers)}",
                   f"                  only change: '..\\lib' appended to {pth.name}", ""]

    # ---- 2. our code + numpy/scipy, verified against their wheels, precompiled
    lib = runtime / "lib"
    lib.mkdir()
    shutil.copytree(ROOT / "src" / PACKAGE, lib / PACKAGE, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "templates"))
    for rel in TEMPLATE_FILES:
        dst = lib / PACKAGE / "templates" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "src" / PACKAGE / "templates" / rel, dst)
    for dist in THIRD_PARTY:
        d, base, checked = verify_record(dist)
        # the package's own folders only (RECORD also lists helper scripts outside site-packages, e.g. ../../Scripts/f2py.exe)
        tops = sorted({Path(f).parts[0] for f in d.files if not str(f).endswith(".pyc") and Path(f).parts[0] != ".."})
        for top in tops:
            src = base / top
            if src.is_dir():
                shutil.copytree(src, lib / top, ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyc"))
            else:
                shutil.copy2(src, lib / top)
        provenance.append(f"{dist:<16}: {d.version} from PyPI; {checked} files verified against the wheel RECORD hashes")
    # stripdir/prependdir: the .pyc files record "lib\..." instead of this build machine's folder (reproducible, no local paths)
    compileall.compile_dir(str(lib), quiet=1, stripdir=str(lib), prependdir="lib",
                           invalidation_mode=compileall.py_compile.PycInvalidationMode.UNCHECKED_HASH)
    provenance.append(f"our code        : {PACKAGE} v{__version__}, plain Python source (open source, MIT)")
    provenance.append("")

    # ---- 3. bundled ffmpeg, identified without running it
    ff_dir = runtime / "ffmpeg"
    ff_dir.mkdir()
    with zipfile.ZipFile(ffmpeg_zip) as z:
        for info in z.infolist():
            base = info.filename.rsplit("/", 1)[-1]
            if base == "ffmpeg.exe":
                (ff_dir / "ffmpeg.exe").write_bytes(z.read(info))
            elif base in ("LICENSE.txt", "LICENSE") and info.filename.count("/") <= 1:
                (ff_dir / base).write_bytes(z.read(info))
    exe_bytes = (ff_dir / "ffmpeg.exe").read_bytes()
    found = re.search(rb"N-\d+-g([0-9a-f]{7,40})-\d{8}", exe_bytes)
    if not found:
        raise SystemExit("cannot identify the FFmpeg build")
    build_id, short = found.group(0).decode(), found.group(1).decode()
    with tarfile.open(ffmpeg_source) as tar:
        top = tar.next().name.split("/")[0]
    if not top.startswith(f"FFmpeg-{short}"):
        raise SystemExit(f"{ffmpeg_source} is the source of {top}, not of the bundled build {build_id}")
    commit = top.split("-", 1)[1]
    notice = (ROOT / "packaging" / "FFMPEG-NOTICE.txt").read_text(encoding="utf-8").replace("{commit}", commit).replace("{short}", short)
    (ff_dir / "FFMPEG-NOTICE.txt").write_text(notice + f"\nBundled build          : {build_id}\n"
                                              f"ffmpeg.exe SHA-256     : {hashlib.sha256(exe_bytes).hexdigest()}\n", encoding="utf-8")
    provenance += [f"FFmpeg          : {build_id} (LGPL, https://github.com/BtbN/FFmpeg-Builds), source commit {commit}",
                   f"                  ffmpeg.exe SHA-256 {hashlib.sha256(exe_bytes).hexdigest()}", ""]

    # ---- 4. licence texts
    lic = runtime / "licenses"
    lic.mkdir()
    shutil.copy2(py / "LICENSE.txt", lic / "Python-LICENSE.txt")
    for dist, name in (("numpy", "NumPy-LICENSE.txt"), ("scipy", "SciPy-LICENSE.txt")):
        d = md.distribution(dist)
        files = [f for f in d.files if re.search(r"dist-info/(licenses/)?LICENSE(\.txt)?$", str(f))]
        if not files:
            raise SystemExit(f"missing licence text for {dist}")
        shutil.copy2(d.locate_file(files[0]), lic / name)

    # ---- 5. user-facing files
    for name, (title, command) in LAUNCHERS.items():
        (app_root / name).write_bytes(launcher(title, command).encode("ascii"))
    (app_root / "Count Video File.bat").write_bytes(VIDEO_LAUNCHER.encode("ascii"))
    (app_root / "Fortnite Visual Chest Counter.cmd").write_bytes(COMMAND_LINE_ENTRY.encode("ascii"))
    shutil.copy2(ROOT / "packaging" / "README.html", app_root / "README.html")
    shutil.copy2(ROOT / "config.example.toml", app_root / "config.example.toml")
    shutil.copy2(ROOT / "packaging" / "LICENSE-NOTICE.txt", app_root / "LICENSE-NOTICE.txt")
    shutil.copy2(ROOT / "LICENSE", app_root / "LICENSE.txt")
    for d, text in (("state", "Your counter lives here. Keep this folder when updating.\n"),
                    ("logs", "Session logs. Send logs/diagnostics.txt (and any crash_*.txt) when you ask for help.\n")):
        (app_root / d).mkdir()
        (app_root / d / "README.txt").write_text(text, encoding="utf-8")
    obs = app_root / "obs_output"
    obs.mkdir()
    (obs / "certain_chests.txt").write_text("CERTAIN OPENED CHESTS: 0\n", encoding="utf-8")
    (obs / "approximate_chests.txt").write_text("APPROX. OPENED CHESTS: 0\n", encoding="utf-8")
    (obs / "chest_status.txt").write_text("0 certain • ~0 estimated\n", encoding="utf-8")
    (obs / "chest_counter.txt").write_text("CERTAIN OPENED CHESTS: 0\nAPPROX. OPENED CHESTS: 0\n", encoding="utf-8")
    (obs / "last_chest.txt").write_text("NO CHESTS YET\n", encoding="utf-8")
    (runtime / "PROVENANCE.txt").write_text("\n".join(provenance) + "\n", encoding="utf-8")

    audit(app_root)

    # ---- 6. reproducible zip + checksums
    zip_path = out / f"{app_root.name}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(p for p in app_root.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(str(Path(app_root.name) / f.relative_to(app_root)).replace("\\", "/"), ZIP_TIME)
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, f.read_bytes(), compresslevel=9)
    assets = [zip_path, Path(ffmpeg_source)]
    (out / "SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in assets), encoding="utf-8", newline="\n")
    print("\n".join(provenance))
    print(f"Built {app_root}\n      {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)\n      {out / 'SHA256SUMS.txt'}")
    return app_root, zip_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-embed", required=True, help="python-3.X.Y-embed-amd64.zip from python.org (same 3.X as this Python)")
    ap.add_argument("--ffmpeg-zip", required=True, help="a win64 LGPL ffmpeg build zip (see packaging/FFMPEG-NOTICE.txt)")
    ap.add_argument("--ffmpeg-source", required=True, help="the FFmpeg source archive of the exact bundled commit")
    ap.add_argument("--out", default=str(ROOT / "build_out"))
    a = ap.parse_args()
    build(Path(a.out), Path(a.python_embed), Path(a.ffmpeg_zip), Path(a.ffmpeg_source))
