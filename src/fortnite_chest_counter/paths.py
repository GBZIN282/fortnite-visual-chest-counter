"""
Where things live, for both `python -m fortnite_chest_counter` (development) and the packaged .exe.

  APP_DIR       the folder the user sees: config.toml, state/, logs/, obs_output/ live here.
                (packaged: the folder holding "Fortnite Visual Chest Counter.exe"; dev: this source folder)
  RESOURCE_DIR  read-only files shipped with the program: templates/, ffmpeg/.
                (packaged: PyInstaller's bundle folder, "runtime/"; dev: this source folder)

User data (APP_DIR) and program files (RESOURCE_DIR) are deliberately separate so an update can
replace the program without touching the user's counts or settings.
"""

import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    # Development / `pip install`: user data goes in the folder you run the command from;
    # the templates ship inside this package.
    APP_DIR = Path(os.environ.get("FCC_HOME") or os.getcwd()).resolve()
    RESOURCE_DIR = Path(__file__).resolve().parent

TEMPLATES_DIR = RESOURCE_DIR / "templates"

# Template files the live counter cannot run without.
REQUIRED_TEMPLATES = [
    TEMPLATES_DIR / "chest" / "en" / "chest.npy",
    TEMPLATES_DIR / "chest" / "pt" / "bau.npy",
    TEMPLATES_DIR / "container_opened.npy",
    TEMPLATES_DIR / "ui" / "interaction_disc.npy",
    TEMPLATES_DIR / "ui" / "interaction_ring.npy",
]


def bundled_ffmpeg_dir():
    """Folder holding the ffmpeg.exe shipped with the app, or None."""
    for candidate in (RESOURCE_DIR / "ffmpeg", APP_DIR / "ffmpeg"):
        if (candidate / "ffmpeg.exe").exists():
            return candidate
    return None


def setup_environment():
    """Run the app from APP_DIR (so config/state/logs are found) and make the bundled ffmpeg win over PATH."""
    os.chdir(APP_DIR)
    ffmpeg_dir = bundled_ffmpeg_dir()
    if ffmpeg_dir:
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")


def ffmpeg_executable():
    """Full path of the ffmpeg that will be used, or None if there is none."""
    ffmpeg_dir = bundled_ffmpeg_dir()
    if ffmpeg_dir:
        return str(ffmpeg_dir / "ffmpeg.exe")
    return shutil.which("ffmpeg")


def missing_templates():
    return [p for p in REQUIRED_TEMPLATES if not p.exists()]
