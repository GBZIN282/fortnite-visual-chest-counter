"""
Where things live, for both `python -m fortnite_chest_counter` (development) and the packaged .exe.

  APP_DIR       the folder the user sees: config.toml, state/, logs/, obs_output/ live here.
                (release: the folder holding "Fortnite Visual Chest Counter.exe", found from runtime/python/;
                dev: the current folder or FCC_HOME)
  RESOURCE_DIR  read-only files shipped with the program: templates/, ffmpeg/.
                (release: runtime/lib/fortnite_chest_counter; dev: this source folder)

User data (APP_DIR) and program files (RESOURCE_DIR) are deliberately separate so an update can
replace the program without touching the user's counts or settings.
"""

import hashlib
import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
_EXE_DIR = Path(sys.executable).resolve().parent


def _release_root(exe_dir):
    """The app folder if `exe_dir` is the release's runtime\\python folder (app\\runtime\\python\\python(w).exe), else None.
    Lets the desktop app and the command line find config/state/logs wherever they were started from."""
    if exe_dir.name.lower() == "python" and exe_dir.parent.name.lower() == "runtime" \
            and (exe_dir.parent / "lib" / "fortnite_chest_counter").is_dir():
        return exe_dir.parent.parent
    return None


if FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
elif _release_root(_EXE_DIR) is not None:
    APP_DIR = _release_root(_EXE_DIR)
    RESOURCE_DIR = Path(__file__).resolve().parent
else:
    # Development / `pip install`: user data goes in the folder you run the command from;
    # the templates ship inside this package.
    APP_DIR = Path(os.environ.get("FCC_HOME") or os.getcwd()).resolve()
    RESOURCE_DIR = Path(__file__).resolve().parent

TEMPLATES_DIR = RESOURCE_DIR / "templates"

# The Windows release runs the official python.org embeddable Python shipped in runtime\python\ (signed by the Python
# Software Foundation): the desktop app is runtime\python\pythonw.exe -m fortnite_chest_counter.gui.
EMBEDDED_RUNTIME = APP_DIR / "runtime" / "python"
PACKAGED = FROZEN or Path(sys.executable).resolve().parent == EMBEDDED_RUNTIME.resolve()

# Template files the live counter cannot run without.
REQUIRED_TEMPLATES = [
    TEMPLATES_DIR / "chest" / "en" / "chest.npy",
    TEMPLATES_DIR / "chest" / "en" / "chest_small.npy",
    TEMPLATES_DIR / "chest" / "en" / "rare.npy",
    TEMPLATES_DIR / "chest" / "en" / "rare_small.npy",
    TEMPLATES_DIR / "chest" / "en" / "sprite.npy",
    TEMPLATES_DIR / "chest" / "en" / "sprite_small.npy",
    TEMPLATES_DIR / "chest" / "pt" / "bau.npy",
    TEMPLATES_DIR / "container_opened.npy",
    TEMPLATES_DIR / "ui" / "interaction_disc.npy",
    TEMPLATES_DIR / "ui" / "interaction_ring.npy",
]


def app_mutex_name():
    """One app window per program folder. Windows releases this however the app ends."""
    return "Local\\FortniteVisualChestCounter-App-" + hashlib.sha1(str(APP_DIR).lower().encode()).hexdigest()[:16]


def bundled_ffmpeg_dir():
    """Folder holding the ffmpeg.exe shipped with the app, or None."""
    for candidate in (RESOURCE_DIR / "ffmpeg", APP_DIR / "runtime" / "ffmpeg", APP_DIR / "ffmpeg"):
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


# The desktop app and its counting worker have no console window. A console program (ffmpeg) started from such a process
# would get a NEW console window of its own (a black window flashing up), so in that mode every helper process is started
# with CREATE_NO_WINDOW. The command-line mode leaves this off: there ffmpeg shares the visible console, as in v0.1.x.
HIDE_CHILD_CONSOLES = False


def _has_console_window():
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        return True


def child_process_flags():
    """creationflags for subprocess calls that start ffmpeg: CREATE_NO_WINDOW when this process has no console window of
    its own (the desktop app, its worker, its diagnostics run), else 0 = exactly the v0.1.x behaviour."""
    if os.name != "nt":
        return 0
    return 0x08000000 if (HIDE_CHILD_CONSOLES or not _has_console_window()) else 0         # CREATE_NO_WINDOW


def child_stdin():
    """stdin for ffmpeg. In the desktop app's worker, stdin is the app's control pipe: ffmpeg must never share it (it polls
    stdin for key presses, and on Windows two processes using one synchronous pipe can block each other). None = inherit,
    the v0.1.x console behaviour."""
    return -3 if HIDE_CHILD_CONSOLES else None                                         # subprocess.DEVNULL


def worker_python():
    """The python.exe that runs the counting worker for the desktop app: the release's own runtime, else this Python
    (python.exe rather than pythonw.exe, so the worker's output pipes behave like a normal console program's)."""
    for candidate in (EMBEDDED_RUNTIME / "python.exe", _EXE_DIR / "python.exe"):
        if candidate.is_file():
            return str(candidate)
    return sys.executable
