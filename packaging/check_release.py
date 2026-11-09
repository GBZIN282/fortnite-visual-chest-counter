"""
The last check before a release can be published.   (Maintainer only: never shipped. See docs/UPDATE_SIGNING.md.)

    python packaging/check_release.py --out <the folder holding the release zip> [--version X.Y.Z] [--inputs <the build inputs folder>]

Everything must be in place and correct, or nothing may be published: the signed manifest and its signature, the zip they describe,
what is inside it (updater modules, official Python, pinned packages, trusted keys), the FFmpeg source that must be offered with it,
and no private key anywhere. verified_assets() is the only way the publish step gets its list of files, so it cannot upload a release
that has not passed.
"""

import argparse
import ast
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))

import build_release                                                     # noqa: E402
from fortnite_chest_counter.update import archive                        # noqa: E402
from fortnite_chest_counter.update import authenticity as A              # noqa: E402
from fortnite_chest_counter.update import install_helper as H            # noqa: E402
from fortnite_chest_counter.update.releases import MANIFEST_NAME, SIGNATURE_NAME, UpdateError, parse_version, zip_name  # noqa: E402
from fortnite_chest_counter.update.trust import TRUSTED_PUBLIC_KEYS      # noqa: E402
from fortnite_chest_counter.version import __version__                   # noqa: E402

PACKAGE = "runtime/lib/fortnite_chest_counter"
TRUST_FILE = f"{PACKAGE}/update/trust.py"
REQUIRED_MODULES = (*(f"{PACKAGE}/update/{path.name}" for path in sorted((ROOT / "src/fortnite_chest_counter/update").glob("*.py"))),
                    f"{PACKAGE}/gui/update_manager.py")
PROVENANCE = "runtime/PROVENANCE.txt"
PYTHON_FOLDER = "runtime/python/"
SUMS_NAME = "SHA256SUMS.txt"
PRIVATE_KEY_MARKER = b"PRIVATE" + b" KEY-----"
PRIVATE_KEY_SUFFIXES = (".pem", ".key")
SMALL_FILE = 64 * 1024                     # a key file is under a kilobyte, so only small files need reading
PUBLIC_CERTIFICATES = "runtime/lib/certifi/cacert.pem"                 # a public bundle, not a key
CRYPTO_TEST_VECTORS = "runtime/lib/Crypto/SelfTest/"                   # the crypto library's own published test keys


def _keys_in(text):
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TRUSTED_PUBLIC_KEYS":
            return ast.literal_eval(node.value)
    return ()


def _check_keys_are_usable(keys):
    from Crypto.Signature import eddsa
    bad = []
    for key in keys:
        try:
            eddsa.import_public_key(bytes.fromhex(key))
        except (ValueError, TypeError):
            bad.append(f"the key {str(key)[:24]}... in the release is not a valid public key")
    return bad


def _normal(name):
    return name.lower().replace("_", "-")


def _check_launcher(z, by_path, version):
    launcher = by_path.get(archive.LAUNCHER)
    return [] if launcher and version.encode("utf-16-le") in z.read(launcher.info) else ["the launcher in the release was not built for this version"]


def _check_dependencies(z, by_path):
    """The build records each package it copied, after checking it against its wheel. That record must be exactly the pinned list."""
    record = by_path.get(PROVENANCE)
    if record is None:
        return [f"the release does not contain {PROVENANCE}"]
    built = {_normal(name): version for name, version in re.findall(r"(?m)^(\S+?)\s*: (\S+) from PyPI", z.read(record.info).decode("utf-8"))}
    pinned = {_normal(name): version for name, version in build_release.pinned_packages().items()}
    return [f"{name} in the release is {built.get(name, 'absent')}, expected {pinned.get(name, 'not shipped')}"
            for name in sorted({*built, *pinned}) if built.get(name) != pinned.get(name)]


def _check_official_python(z, by_path, python_embed):
    """Every file of the official embeddable Python, and nothing else. The build's only edit is one added line in the ._pth file."""
    shipped = {path[len(PYTHON_FOLDER):]: item for path, item in by_path.items() if path.startswith(PYTHON_FOLDER)}
    with zipfile.ZipFile(python_embed) as official:
        expected = {member.filename: member for member in official.infolist() if not member.is_dir()}
        found = [f"{name} is not part of the official Python" for name in sorted(set(shipped) - set(expected))]
        found += [f"the official Python file {name} is missing from the release" for name in sorted(set(expected) - set(shipped))]
        for name in sorted(set(shipped) & set(expected)):
            if name.endswith("._pth"):
                wanted = official.read(name).decode("utf-8").replace("\r\n", "\n").rstrip("\n") + "\n..\\lib\n"
                if z.read(shipped[name].info).decode("utf-8").replace("\r\n", "\n") != wanted:
                    found.append(f"{name} has changes the build does not make")
            elif shipped[name].info.CRC != expected[name].CRC or shipped[name].info.file_size != expected[name].file_size:
                found.append(f"{name} differs from the official Python")
    return found


def _inspect_zip(zip_path, manifest, expected_keys, python_embed):
    found = []
    plan = archive.inspect(zip_path, manifest)
    by_path = {item.path: item for item in plan.files}
    found += [f"the release does not contain {module}" for module in REQUIRED_MODULES if module not in by_path]
    with zipfile.ZipFile(zip_path) as z:
        found += _check_launcher(z, by_path, manifest.version)
        found += _check_dependencies(z, by_path)
        if python_embed is not None:
            found += _check_official_python(z, by_path, python_embed)
        listing = by_path.get(f"{H.RUNTIME}/{H.PACKAGE_FILES}")
        if listing is None:
            found.append(f"the release does not contain {H.RUNTIME}/{H.PACKAGE_FILES}")
        else:
            listed = set(json.loads(z.read(listing.info))["files"])
            actual = {path[len(H.RUNTIME) + 1:] for path in by_path if path.startswith(H.RUNTIME + "/") and not path.endswith("/" + H.PACKAGE_FILES)}
            if listed != actual:
                found.append(f"{H.PACKAGE_FILES} does not match the files in the release")
        trust = by_path.get(TRUST_FILE)
        keys = _keys_in(z.read(trust.info).decode("utf-8")) if trust else ()
        found += [f"in the release: {problem}" for problem in build_release.check_update_keys(keys)]
        found += _check_keys_are_usable(keys)
        if tuple(keys) != tuple(expected_keys):
            found.append("the keys in the release are not the production keys in this repository")
        for item in plan.files:
            if item.path == PUBLIC_CERTIFICATES or item.path.startswith(CRYPTO_TEST_VECTORS):
                continue
            if item.path.lower().endswith(PRIVATE_KEY_SUFFIXES) or (item.size <= SMALL_FILE and PRIVATE_KEY_MARKER in z.read(item.info)):
                found.append(f"the release contains private key material: {item.path}")
    return found, keys


def _check_sums(out, zip_path, manifest, ffmpeg_source):
    sums = out / SUMS_NAME
    if not sums.is_file():
        return [f"{SUMS_NAME} is missing"]
    listed = dict(reversed(line.split(None, 1)) for line in sums.read_text(encoding="utf-8").splitlines() if line.strip())
    expected = {zip_path.name: manifest.sha256}
    if ffmpeg_source is not None:
        expected[ffmpeg_source.name] = A.file_sha256(ffmpeg_source)
    return [] if listed == expected else [f"{SUMS_NAME} does not match the zip and the FFmpeg source archive"]


def _check_no_private_keys_nearby(out):
    found = []
    for file in out.iterdir():
        if file.is_file() and (file.suffix.lower() in PRIVATE_KEY_SUFFIXES or (file.stat().st_size <= SMALL_FILE and PRIVATE_KEY_MARKER in file.read_bytes())):
            found.append(f"private key material next to the release: {file.name}")
    return found


def _one_input(inputs, pattern):
    """The single build input matching `pattern`, or None."""
    matches = sorted(Path(inputs if inputs is not None else ROOT / "build_out" / "inputs").glob(pattern))
    return matches[0] if len(matches) == 1 else None


def _official_python_zip(inputs):
    return _one_input(inputs, "python-*-embed-amd64.zip")


def _ffmpeg_source(inputs):
    return _one_input(inputs, "ffmpeg-source-*.tar.gz")


def problems(out_dir, version=__version__, expected_keys=None, notes_folder=None, inputs=None):
    """Everything that stops this release being published. -> [problems], empty if it may go out."""
    out = Path(out_dir)
    expected_keys = TRUSTED_PUBLIC_KEYS if expected_keys is None else expected_keys
    if parse_version(version) is None:
        return [f"{version} is not a release version"]
    zip_path, manifest_path, signature_path = out / zip_name(version), out / MANIFEST_NAME, out / SIGNATURE_NAME
    missing = [f"{path.name} is missing" for path in (zip_path, manifest_path, signature_path) if not path.is_file()]
    notes = Path(notes_folder if notes_folder is not None else ROOT / "docs") / f"RELEASE_NOTES_v{version}.md"
    if not notes.is_file() or not notes.read_text(encoding="utf-8").strip():
        missing.append(f"{notes.name} is missing or empty")
    if any("is missing" in entry and "RELEASE_NOTES" not in entry for entry in missing):
        return missing
    found = list(missing)
    python_embed, ffmpeg_source = _official_python_zip(inputs), _ffmpeg_source(inputs)
    if python_embed is None:
        found.append("the build inputs must hold exactly one official Python zip (python-*-embed-amd64.zip)")
    if ffmpeg_source is None:
        found.append("the build inputs must hold exactly one FFmpeg source archive (ffmpeg-source-*.tar.gz)")
    found += [f"before release: {problem}" for problem in build_release.check_update_keys(expected_keys)]
    found += _check_no_private_keys_nearby(out)
    manifest_bytes, signature_bytes = manifest_path.read_bytes(), signature_path.read_bytes()
    try:
        manifest = A.parse_manifest(manifest_bytes)
        A.verify_package(zip_path, manifest)
        if manifest.version != version or manifest.zip != zip_path.name:
            found.append("the signed manifest describes a different release")
        contents, keys = _inspect_zip(zip_path, manifest, expected_keys, python_embed)
        found += contents
        A.verify_signature(manifest_bytes, signature_bytes, keys)
        found += _check_sums(out, zip_path, manifest, ffmpeg_source)
    except UpdateError as error:
        found.append(f"{error.kind}: {error}")
    except (OSError, ValueError, KeyError, TypeError, SyntaxError, zipfile.BadZipFile) as error:
        found.append(f"could not check the release ({type(error).__name__}: {error})")
    return found


def verified_assets(out_dir, version=__version__, inputs=None, **options):
    """Every file to upload, including the FFmpeg source the licence requires. Raises SystemExit unless every check passes."""
    found = problems(out_dir, version, inputs=inputs, **options)
    if found:
        raise SystemExit("This release must not be published:\n  " + "\n  ".join(found))
    out = Path(out_dir)
    return [out / zip_name(version), out / MANIFEST_NAME, out / SIGNATURE_NAME, out / SUMS_NAME, _ffmpeg_source(inputs)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="the folder holding the release zip and its signing files")
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--inputs", help="the folder holding the official Python zip and the FFmpeg source archive (default: build_out/inputs)")
    arguments = parser.parse_args()
    for asset in verified_assets(arguments.out, arguments.version, inputs=arguments.inputs):
        print(f"ok  {asset.name}")
    print(f"Release v{arguments.version} passed every check.")
