"""
Build the public release folder + zip.   (Developers only - end users never run this.)

    python packaging/build_release.py --ffmpeg-zip path/to/ffmpeg-win64-lgpl.zip --ffmpeg-source FFmpeg-<commit>.tar.gz [--out build_out]

Needs (in the Python you run it with):  pip install numpy scipy pyinstaller
It does NOT need librosa / matplotlib: the live app does not use them.

Steps: PyInstaller (one-folder app, internals tucked in runtime/) -> add bundled ffmpeg -> add the
launchers, README and example config -> fresh, ZERO-count obs_output files -> zip.
User data (state/, logs/, config.toml) is never created by the build, so a release can never carry old counts.
"""

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from fortnite_chest_counter.version import APP_NAME, __version__                       # noqa: E402

EXE_NAME = APP_NAME
TEMPLATES_SRC = ROOT / "src" / "fortnite_chest_counter" / "templates"
TEMPLATE_FILES = ["chest/en/chest.npy", "chest/pt/bau.npy", "container_opened.npy", "ui/interaction_disc.npy",
                  "ui/interaction_ring.npy"]                    # audio_fingerprint.npy is development-only
# imported inside functions (lazily) - listed so the packager can never miss them
HIDDEN_IMPORTS = ["fortnite_chest_counter.estimator", "fortnite_chest_counter.settings", "fortnite_chest_counter.paths",
                  "fortnite_chest_counter.version", "fortnite_chest_counter.input.video_sources",
                  "fortnite_chest_counter.detection.visual", "fortnite_chest_counter.detection.sprite",
                  "fortnite_chest_counter.detection.evidence", "fortnite_chest_counter.detection.object_cue",
                  "fortnite_chest_counter.detection.fusion", "fortnite_chest_counter.detection.refine",
                  "fortnite_chest_counter.detection.predict", "fortnite_chest_counter.detection.audio",
                  "scipy.ndimage"]
EXCLUDES = ["matplotlib", "librosa", "numba", "llvmlite", "sklearn", "soundfile", "pandas", "PIL", "tkinter",
            "IPython", "pytest", "scipy.io.matlab.tests"]


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, **kw)


def audit(app_root):
    """Fail the build if development leftovers or old counts could reach users."""
    problems = []
    bad_names = {"samples", "analysis_output", "__pycache__", ".venv", "chest_count.txt", "chest_count_save.txt",
                 "audio_fingerprint.npy", "chest_state.json", "config.toml"}
    for f in app_root.rglob("*"):
        if f.name in bad_names or f.suffix in (".mp4", ".wav", ".npz", ".pyc", ".jsonl", ".py"):
            problems.append(str(f.relative_to(app_root)))
    if any(f.suffix == ".json" for f in (app_root / "state").iterdir()):
        problems.append("state/ contains a saved counter")
    for name, expected in (("certain_chests.txt", "CERTAIN OPENED CHESTS: 0"), ("approximate_chests.txt", "APPROX. OPENED CHESTS: 0")):
        if (app_root / "obs_output" / name).read_text(encoding="utf-8").strip() != expected:
            problems.append(f"obs_output/{name} is not zero")
    if problems:
        raise SystemExit("RELEASE AUDIT FAILED:\n  " + "\n  ".join(problems))
    print("Release audit passed: no samples, analysis output, bytecode, logs or saved counts; OBS files start at 0.")


def build(out, ffmpeg_zip, ffmpeg_source=None):
    work = out / "_work"
    app_root = out / f"Fortnite-Visual-Chest-Counter-v{__version__}"
    for d in (work, app_root):
        shutil.rmtree(d, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    # ---- 1. the program
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
           "--name", EXE_NAME, "--contents-directory", "runtime",
           "--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work)]
    for rel in TEMPLATE_FILES:
        cmd += ["--add-data", f"{TEMPLATES_SRC / rel}{';'}{Path('templates') / Path(rel).parent}"]
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    cmd += ["--paths", str(ROOT / "src"), str(ROOT / "packaging" / "entry.py")]
    run(cmd, cwd=ROOT)
    shutil.copytree(work / "dist" / EXE_NAME, app_root)

    # ---- 2. bundled ffmpeg (so users never install it or touch PATH)
    ff_dir = app_root / "runtime" / "ffmpeg"
    ff_dir.mkdir(parents=True)
    with zipfile.ZipFile(ffmpeg_zip) as z:
        for info in z.infolist():
            name = info.filename
            base = name.rsplit("/", 1)[-1]
            if base == "ffmpeg.exe":
                with z.open(info) as src, open(ff_dir / "ffmpeg.exe", "wb") as dst:
                    shutil.copyfileobj(src, dst)
            elif base in ("LICENSE.txt", "LICENSE", "COPYING.LGPLv3") and name.count("/") <= 1:
                (ff_dir / base).write_bytes(z.read(info))
    if not (ff_dir / "ffmpeg.exe").exists():
        raise SystemExit(f"no ffmpeg.exe inside {ffmpeg_zip}")
    # Identify the exact FFmpeg build without running it: its version string is embedded in the binary.
    exe_bytes = (ff_dir / "ffmpeg.exe").read_bytes()
    found = re.search(rb"N-\d+-g([0-9a-f]{7,40})-\d{8}", exe_bytes)
    if not found:
        raise SystemExit("cannot identify the FFmpeg build (no 'N-<n>-g<commit>-<date>' version string)")
    build_id, short = found.group(0).decode(), found.group(1).decode()
    commit = short
    if ffmpeg_source:                                # the matching source archive: FFmpeg-<full commit>/...
        with tarfile.open(ffmpeg_source) as tar:
            top = tar.next().name.split("/")[0]
        if not top.startswith(f"FFmpeg-{short}"):
            raise SystemExit(f"{ffmpeg_source} is the source of {top}, not of the bundled build {build_id}")
        commit = top.split("-", 1)[1]
    notice = (ROOT / "packaging" / "FFMPEG-NOTICE.txt").read_text(encoding="utf-8").replace("{commit}", commit).replace("{short}", short)
    (ff_dir / "FFMPEG-NOTICE.txt").write_text(
        notice + f"\nBundled build          : {build_id}\n"
        f"ffmpeg.exe SHA-256     : {hashlib.sha256(exe_bytes).hexdigest()}\n"
        f"Build archive SHA-256  : {hashlib.sha256(Path(ffmpeg_zip).read_bytes()).hexdigest()}\n", encoding="utf-8")
    print(f"FFmpeg: {build_id} (source commit {commit})")

    # ---- 2b. third-party license texts (BSD / PSF require them alongside binaries)
    lic = app_root / "runtime" / "licenses"
    lic.mkdir()
    site = Path(__import__("numpy").__file__).parent.parent
    sources = {"Python-LICENSE.txt": Path(sys.base_prefix) / "LICENSE.txt",
               "NumPy-LICENSE.txt": next(site.glob("numpy-*.dist-info")) / "licenses" / "LICENSE.txt",
               "SciPy-LICENSE.txt": next(site.glob("scipy-*.dist-info")) / "LICENSE.txt",
               "PyInstaller-COPYING.txt": next(site.glob("pyinstaller-*.dist-info")) / "licenses" / "COPYING.txt"}
    for name, src in sources.items():
        if not src.exists():
            raise SystemExit(f"missing third-party license text: {src}")
        shutil.copy2(src, lic / name)

    # ---- 3. user-facing files
    for src in (ROOT / "packaging" / "launchers").glob("*.bat"):
        shutil.copy2(src, app_root / src.name)
    shutil.copy2(ROOT / "packaging" / "README.html", app_root / "README.html")
    shutil.copy2(ROOT / "config.example.toml", app_root / "config.example.toml")
    shutil.copy2(ROOT / "packaging" / "LICENSE-NOTICE.txt", app_root / "LICENSE-NOTICE.txt")
    shutil.copy2(ROOT / "LICENSE", app_root / "LICENSE.txt")
    for d in ("state", "logs"):
        (app_root / d).mkdir()
        (app_root / d / "README.txt").write_text(
            "Your counter and logs live here. Keep this folder when updating.\n" if d == "state"
            else "Session logs. Send logs/diagnostics.txt (and any crash_*.txt) when you ask for help.\n", encoding="utf-8")
    obs = app_root / "obs_output"
    obs.mkdir()
    (obs / "certain_chests.txt").write_text("CERTAIN OPENED CHESTS: 0\n", encoding="utf-8")
    (obs / "approximate_chests.txt").write_text("APPROX. OPENED CHESTS: 0\n", encoding="utf-8")
    (obs / "chest_status.txt").write_text("0 certain \u2022 ~0 estimated\n", encoding="utf-8")
    (obs / "last_chest.txt").write_text("NO CHESTS YET\n", encoding="utf-8")

    audit(app_root)

    # ---- 4. zip
    zip_path = out / f"{app_root.name}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app_root.rglob("*")):
            if f.is_file():
                z.write(f, Path(app_root.name) / f.relative_to(app_root))
    # ---- 5. checksums for the GitHub release page
    assets = [zip_path] + ([Path(ffmpeg_source)] if ffmpeg_source else [])
    (out / "SHA256SUMS.txt").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in assets),
                                        encoding="utf-8", newline="\n")
    print(f"\nBuilt {app_root}\n      {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)\n      {out / 'SHA256SUMS.txt'}")
    return app_root, zip_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg-zip", required=True, help="a win64 LGPL ffmpeg build zip (see packaging/FFMPEG-NOTICE.txt)")
    ap.add_argument("--ffmpeg-source", help="the FFmpeg source archive of the exact bundled commit (attached to the release)")
    ap.add_argument("--out", default=str(ROOT / "build_out"))
    a = ap.parse_args()
    build(Path(a.out), Path(a.ffmpeg_zip), a.ffmpeg_source)
