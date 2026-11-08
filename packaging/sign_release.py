"""
Create update-signing keys and sign a release.   (Maintainer only: never shipped. See docs/UPDATE_SIGNING.md.)

    python packaging/sign_release.py keygen --out "<a path outside this repository>"
    python packaging/sign_release.py sign --version 0.2.3 --zip build_out/v0.2.3/Fortnite-Visual-Chest-Counter-v0.2.3.zip \
        --key "<key file outside this repository>" [--key "<a second key, while keys are being changed>"]

`sign` writes update-manifest.json and update-manifest.json.sig next to the zip. Private keys are refused if they are inside
this repository, and they are only ever stored encrypted with a passphrase.
"""

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from Crypto.PublicKey import ECC                                        # noqa: E402
from Crypto.Signature import eddsa                                      # noqa: E402

from fortnite_chest_counter.update import authenticity as A             # noqa: E402
from fortnite_chest_counter.update.releases import MANIFEST_NAME, SIGNATURE_NAME, parse_version, zip_name  # noqa: E402

MIN_PASSPHRASE = 16
PROTECTION = "scryptAndAES256-CBC"


def _refuse_inside_repository(path):
    if Path(path).resolve().is_relative_to(ROOT):
        raise SystemExit(f"Refusing: {path} is inside the repository. Private keys must be kept outside it.")


def public_key_hex(key):
    return key.public_key().export_key(format="raw").hex()


def create_key(path, passphrase):
    """Write a new encrypted private key to `path`, which must be outside the repository and not exist yet. -> the key."""
    _refuse_inside_repository(path)
    if len(passphrase) < MIN_PASSPHRASE:
        raise SystemExit(f"The passphrase must be at least {MIN_PASSPHRASE} characters long.")
    key = ECC.generate(curve="ed25519")
    pem = key.export_key(format="PEM", passphrase=passphrase, protection=PROTECTION)
    try:
        with open(path, "x", encoding="ascii", newline="\n") as f:
            f.write(pem + "\n")
    except FileExistsError:
        raise SystemExit(f"Refusing: {path} already exists. A key is never overwritten.") from None
    return key


def load_key(path, passphrase):
    _refuse_inside_repository(path)
    try:
        return ECC.import_key(Path(path).read_text(encoding="ascii"), passphrase=passphrase)
    except (ValueError, IndexError, TypeError):
        raise SystemExit(f"Could not open {path}: wrong passphrase, or not a key file.") from None


def sign_manifest(manifest_bytes, keys):
    """The bytes of a signature file: one signature per key."""
    return A.build_signature_file([(A.key_id(key.public_key().export_key(format="raw")),
                                    eddsa.new(key, "rfc8032").sign(manifest_bytes)) for key in keys])


def sign_package(zip_path, version, keys, out_dir=None):
    """Write and self-check the manifest and signature file for a release zip. -> (manifest path, signature path)."""
    zip_path = Path(zip_path)
    if parse_version(version) is None:
        raise SystemExit(f"{version} is not a release version (expected MAJOR.MINOR.PATCH).")
    if zip_path.name != zip_name(version):
        raise SystemExit(f"{zip_path.name} is not the zip of version {version} (expected {zip_name(version)}).")
    if not keys:
        raise SystemExit("At least one signing key is required.")
    manifest = A.build_manifest(version, zip_path.name, A.file_sha256(zip_path), zip_path.stat().st_size)
    signature = sign_manifest(manifest, keys)
    for key in keys:                       # prove each signature verifies before anything leaves this PC
        A.verify_signature(manifest, signature, [public_key_hex(key)])
    out = Path(out_dir) if out_dir else zip_path.parent
    (out / MANIFEST_NAME).write_bytes(manifest)
    (out / SIGNATURE_NAME).write_bytes(signature)
    return out / MANIFEST_NAME, out / SIGNATURE_NAME


def _keygen(args):
    passphrase = getpass.getpass("New passphrase: ")
    if passphrase != getpass.getpass("Repeat the passphrase: "):
        raise SystemExit("The passphrases do not match. No key was created.")
    key = create_key(args.out, passphrase)
    print(f"Created {args.out}\nKey id     : {A.key_id(bytes.fromhex(public_key_hex(key)))}\nPublic key : {public_key_hex(key)}")


def _sign(args):
    keys = [load_key(path, getpass.getpass(f"Passphrase for {path}: ")) for path in args.key]
    for path in sign_package(args.zip, args.version, keys):
        print(f"Wrote {path}")
    for key in keys:
        print(f"Signed by  : {A.key_id(bytes.fromhex(public_key_hex(key)))}  public key {public_key_hex(key)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    keygen = commands.add_parser("keygen", help="create a new passphrase-protected signing key")
    keygen.add_argument("--out", required=True, help="the key file to create, outside this repository")
    keygen.set_defaults(run=_keygen)
    sign = commands.add_parser("sign", help="write the signed manifest for a release zip")
    sign.add_argument("--version", required=True, help="the release version, for example 0.2.3")
    sign.add_argument("--zip", required=True, help="the release zip")
    sign.add_argument("--key", required=True, action="append", help="a private key file (repeat to sign with several)")
    sign.set_defaults(run=_sign)
    arguments = parser.parse_args()
    arguments.run(arguments)
