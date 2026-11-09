"""
Reading a release zip without trusting its contents.

A valid signature says who built the zip, not that it is safe to unpack blindly. So inspect() checks EVERY entry before a single
file is written, and extract() writes only what inspect() approved.

The package layout is a contract with every copy of the app already installed, because these rules ship in the old version:
    <one root folder named for the version>/
        the five ROOT_FILES          program files next to the runtime
        runtime/**                   everything else the program needs (NEW PROGRAM FILES MUST GO HERE)
        state/README.txt, logs/README.txt, obs_output/*.txt
                                     placeholders: recognised and never unpacked

Anything else is refused, including config.toml, saved counts, logs or captures: a release must never carry user data.
"""

import re
import stat
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass

from fortnite_chest_counter.update.releases import UpdateError

LAUNCHER = "Fortnite Visual Chest Counter.exe"
ROOT_FILES = (LAUNCHER, "README.html", "LICENSE.txt", "LICENSE-NOTICE.txt", "config.example.toml")
PACKAGE_DIR = "runtime/lib/fortnite_chest_counter"
VERSION_FILE = f"{PACKAGE_DIR}/version.py"
PLACEHOLDERS = ("state/README.txt", "logs/README.txt")
# The stable entry points. What a particular version needs beyond these, it checks itself in the staged start-up checks.
REQUIRED_FILES = (LAUNCHER, "runtime/python/python.exe", "runtime/python/pythonw.exe", VERSION_FILE, f"{PACKAGE_DIR}/__main__.py",
                  f"{PACKAGE_DIR}/gui/__main__.py", f"{PACKAGE_DIR}/paths.py", "runtime/ffmpeg/ffmpeg.exe",
                  "runtime/lib/PySide6/QtWidgets.pyd", "runtime/lib/numpy/__init__.py", "runtime/lib/scipy/__init__.py",
                  "runtime/lib/Crypto/__init__.py")

# Measured on v0.2.2: 4,994 files, 399 MB, largest 136 MB, worst ratio above 1 MiB is 5.5 to 1.
MAX_ENTRIES = 20_000
MAX_FILE_SIZE = 512 * 1024 * 1024
MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
MAX_RATIO = 200                            # for files above RATIO_FLOOR, whose size alone makes a high ratio suspicious
RATIO_FLOOR = 1024 * 1024
MAX_VERSION_FILE = 4096
CHUNK = 64 * 1024
_BAD_CHARACTERS = set('<>:"|?*\\')
_RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
_VERSION_LINE = re.compile(r'^__version__\s*=\s*"([^"\n]+)"\s*$', re.MULTILINE)
_READ_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError, ValueError)
_UNSAFE = "This update failed a safety check, so it will not be installed."


@dataclass(frozen=True)
class PlannedFile:
    info: zipfile.ZipInfo
    path: str                              # relative to the package root, with forward slashes
    size: int
    crc: int


@dataclass(frozen=True)
class ArchivePlan:
    root: str
    files: tuple
    placeholders: tuple
    total_size: int

    @property
    def longest_path(self):
        return max(len(f.path) for f in self.files)


def _unsafe_name(name):
    """Traversal, absolute paths, drive letters, Windows streams, device names and names Windows would silently change."""
    if not name or name.startswith("/"):
        return True
    for part in name.split("/"):
        if part in ("", ".", "..") or part[-1] in ". " or part.split(".")[0].lower() in _RESERVED:
            return True
        if any(c in _BAD_CHARACTERS or ord(c) < 32 for c in part):
            return True
    return False


def _unsafe_entry_type(info):
    """Only plain files: no symbolic links, reparse points, devices or encrypted entries, and no unusual compression."""
    file_type = stat.S_IFMT(info.external_attr >> 16)
    return (file_type not in (0, stat.S_IFREG) or info.external_attr & 0x400 or info.flag_bits & 0x1
            or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED))


def _classify(relative):
    """'program', 'placeholder', or None for anything that does not belong in a release."""
    if relative in ROOT_FILES or relative.startswith("runtime/"):
        return "program"
    if relative in PLACEHOLDERS or (relative.startswith("obs_output/") and relative.count("/") == 1 and relative.endswith(".txt")):
        return "placeholder"
    return None


def _layout_error(detail):
    return UpdateError("archive_layout", f"{_UNSAFE} (Unexpected package contents: {detail}.)")


def _unsafe_error(detail):
    return UpdateError("archive_unsafe", f"{_UNSAFE} ({detail}.)")


def _too_large_error(detail):
    return UpdateError("archive_too_large", f"{_UNSAFE} ({detail}.)")


def _build_plan(infos, root):
    if not infos:
        raise _layout_error("the package is empty")
    if len(infos) > MAX_ENTRIES:
        raise _too_large_error("Too many files in the package")
    files, placeholders, keys, folders, total = [], [], set(), set(), 0
    for info in infos:
        name = info.filename
        if info.orig_filename != name or _unsafe_name(name.removesuffix("/") if info.is_dir() else name):
            raise _unsafe_error("Unsafe file name in the package")
        if info.is_dir():
            raise _layout_error("a folder entry")          # the release build writes files only
        if _unsafe_entry_type(info):
            raise _unsafe_error("Unsupported kind of file in the package")
        key = unicodedata.normalize("NFC", name).casefold()
        if key in keys:
            raise _unsafe_error("Two files in the package would have the same name")
        keys.add(key)
        parts = key.split("/")
        folders.update("/".join(parts[:i]) for i in range(1, len(parts)))
        if not name.startswith(root + "/"):
            raise _layout_error("a file outside the version folder")
        relative = name[len(root) + 1:]
        kind = _classify(relative)
        if kind is None:
            raise _layout_error(relative)
        if kind == "placeholder":
            placeholders.append(relative)
            continue
        if info.file_size > MAX_FILE_SIZE:
            raise _too_large_error("A file in the package is too large")
        if info.file_size > RATIO_FLOOR and info.file_size > MAX_RATIO * max(info.compress_size, 1):
            raise _too_large_error("A file in the package expands too much")
        total += info.file_size
        if total > MAX_TOTAL_SIZE:
            raise _too_large_error("The package is too large")
        files.append(PlannedFile(info, relative, info.file_size, info.CRC))
    if keys & folders:
        raise _unsafe_error("A file in the package has the same name as a folder")
    return ArchivePlan(root, tuple(files), tuple(placeholders), total)


def _check_program_files(archive, plan, version):
    by_path = {f.path: f for f in plan.files}
    missing = [path for path in REQUIRED_FILES if path not in by_path]
    if missing:
        raise _layout_error(f"missing {missing[0]}")
    if not any(re.fullmatch(r"runtime/python/python3[0-9]*\._pth", path) for path in by_path):
        raise _layout_error("missing the Python path file")
    version_file = by_path[VERSION_FILE]
    if version_file.size > MAX_VERSION_FILE:
        raise _layout_error("the version file is too large")
    found = _VERSION_LINE.search(archive.read(version_file.info).decode("utf-8", errors="replace"))
    if not found or found.group(1) != version:
        raise _layout_error("the program inside is a different version")


def inspect(zip_path, manifest):
    """Check every entry of a verified zip. -> ArchivePlan. Writes nothing."""
    root = f"Fortnite-Visual-Chest-Counter-v{manifest.version}"
    try:
        with zipfile.ZipFile(zip_path) as archive:
            plan = _build_plan(archive.infolist(), root)
            _check_program_files(archive, plan, manifest.version)
    except _READ_ERRORS:
        raise UpdateError("archive_invalid", f"{_UNSAFE} (The package is damaged.)") from None
    except OSError as error:
        raise UpdateError("package_unreadable", "The downloaded update could not be read. Please try again.", f"{type(error).__name__}: {error}") from None
    return plan


def extract(zip_path, plan, destination, on_bytes):
    """Write the approved program files. Sizes are enforced while writing, because a zip's own numbers can lie."""
    written_total = 0
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for item in plan.files:
                target = destination.joinpath(*item.path.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(item.info) as source, open(target, "xb") as out:      # "x": never replaces anything
                    while chunk := source.read(CHUNK):
                        written += len(chunk)
                        written_total += len(chunk)
                        if written > item.size or written_total > plan.total_size:
                            raise _too_large_error("A file in the package is larger than it claims")
                        out.write(chunk)
                        on_bytes(len(chunk))
                if written != item.size:
                    raise UpdateError("archive_invalid", f"{_UNSAFE} (The package is damaged.)")
    except _READ_ERRORS:
        raise UpdateError("archive_invalid", f"{_UNSAFE} (The package is damaged.)") from None
