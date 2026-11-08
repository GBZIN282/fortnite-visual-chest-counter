"""
Is this release really ours? Every release the updater may install carries two small files next to the zip:

    update-manifest.json       exactly what was released, as canonical JSON on one line:
        {"format":1,"product":"fortnite-visual-chest-counter","sha256":"<hex>","size":123,"version":"0.2.3","zip":"<name>"}
    update-manifest.json.sig   one or more Ed25519 signatures of those exact bytes:
        {"format":1,"signatures":[{"key_id":"<16 hex>","signature":"<base64>"}]}

The signature is checked on the raw bytes BEFORE the manifest is read at all. There is no unsigned path: a missing, damaged
or unknown signature means no update. Several signatures are allowed so a release can be signed by an old and a new key
while keys are being changed (docs/UPDATE_SIGNING.md).

Trust comes only from trust.py in the INSTALLED app. Nothing a release carries can add a key: a key id only selects among
the keys already installed, and the key bytes that do the verifying always come from that list.

The manifest binds the version to one exact zip. Its name, size and SHA-256 must then match what GitHub lists, and later the
downloaded file. A properly signed old manifest attached to a new tag fails, and so does anything not newer than this copy.
"""

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from fortnite_chest_counter.update.releases import Release, UpdateError, parse_version, zip_name
from fortnite_chest_counter.update.trust import TRUSTED_PUBLIC_KEYS

PRODUCT = "fortnite-visual-chest-counter"
MANIFEST_FORMAT = 1
SIGNATURE_FORMAT = 1
MAX_SIGNATURES = 8
_KEY_ID = re.compile("[0-9a-f]{16}")
_SHA256 = re.compile("[0-9a-f]{64}")
_NOT_VERIFIED = "This update could not be verified, so it will not be installed."


@dataclass(frozen=True)
class Manifest:
    version: str
    zip: str
    sha256: str
    size: int


@dataclass(frozen=True)
class VerifiedUpdate:
    release: Release
    manifest: Manifest
    signed_by: str                         # the key id that verified


def _canonical(fields):
    return (json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def key_id(public_key):
    """A short name for a raw 32-byte public key. Derived from the key, so a name can never point at the wrong key."""
    return hashlib.sha256(public_key).hexdigest()[:16]


def build_manifest(version, zip_file_name, sha256, size):
    """The exact manifest bytes: the same inputs always give the same bytes."""
    raw = _canonical({"format": MANIFEST_FORMAT, "product": PRODUCT, "sha256": sha256, "size": size, "version": version,
                      "zip": zip_file_name})
    parse_manifest(raw)                    # the signing tool cannot produce a manifest the app would refuse
    return raw


def build_signature_file(signatures):
    """[(key id, 64 signature bytes), ...] -> the bytes of the signature file."""
    return _canonical({"format": SIGNATURE_FORMAT, "signatures": [{"key_id": kid, "signature": base64.b64encode(sig).decode("ascii")}
                                                                  for kid, sig in signatures]})


def _signatures(raw):
    """[(key id, signature bytes)] from a signature file. Anything malformed raises."""
    invalid = UpdateError("signature_invalid", _NOT_VERIFIED + " (Its signature is damaged.)")
    try:
        data = json.loads(raw.decode("ascii"))
    except (ValueError, RecursionError):
        raise invalid from None
    entries = data.get("signatures") if isinstance(data, dict) and data.get("format") == SIGNATURE_FORMAT else None
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_SIGNATURES:
        raise invalid
    result = []
    for entry in entries:
        kid, text = (entry.get("key_id"), entry.get("signature")) if isinstance(entry, dict) else (None, None)
        if not isinstance(kid, str) or not _KEY_ID.fullmatch(kid) or not isinstance(text, str):
            raise invalid
        try:
            signature = base64.b64decode(text, validate=True)
        except ValueError:
            raise invalid from None
        if len(signature) != 64:
            raise invalid
        result.append((kid, signature))
    return result


def _trusted(public_keys):
    """{key id: raw key}. A malformed entry is simply not trusted."""
    trusted = {}
    for text in public_keys:
        try:
            raw = bytes.fromhex(text)
        except (ValueError, TypeError):
            continue
        if len(raw) == 32:
            trusted[key_id(raw)] = raw
    return trusted


def verify_signature(manifest_bytes, signature_bytes, public_keys):
    """-> the id of the trusted key that signed exactly these bytes. Raises UpdateError otherwise."""
    trusted = _trusted(public_keys)
    if not trusted:
        raise UpdateError("no_trusted_keys", _NOT_VERIFIED + " (This copy of the app has no update key.)")
    try:
        from Crypto.Signature import eddsa
    except ImportError:
        raise UpdateError("verifier_missing", _NOT_VERIFIED + " (A program file is missing.)") from None
    known = [(kid, signature) for kid, signature in _signatures(signature_bytes) if kid in trusted]
    if not known:
        raise UpdateError("untrusted_key", _NOT_VERIFIED + " (It was signed by an unknown key.)")
    for kid, signature in known:
        try:
            eddsa.new(eddsa.import_public_key(trusted[kid]), "rfc8032").verify(manifest_bytes, signature)
            return kid
        except ValueError:
            continue
    raise UpdateError("signature_invalid", _NOT_VERIFIED + " (Its signature does not match.)")


def parse_manifest(raw):
    """The manifest from its exact bytes. Only for bytes whose signature has been verified (or that this program just built).
    Fields this version does not know are ignored: they are covered by the signature, and later formats may add some."""
    invalid = UpdateError("manifest_invalid", _NOT_VERIFIED + " (Its manifest is not valid.)")
    try:
        fields = json.loads(raw.decode("ascii"))
    except (ValueError, RecursionError):
        raise invalid from None
    if not isinstance(fields, dict) or _canonical(fields) != raw:
        raise invalid                      # also rejects repeated keys, which JSON parsers silently collapse
    version, name, sha256, size = fields.get("version"), fields.get("zip"), fields.get("sha256"), fields.get("size")
    if type(fields.get("format")) is not int or fields["format"] != MANIFEST_FORMAT or fields.get("product") != PRODUCT:
        raise invalid
    if parse_version(version) is None or name != zip_name(version) or type(size) is not int or size <= 0:
        raise invalid
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise invalid
    return Manifest(version, name, sha256, size)


def verify_release(release, manifest_bytes, signature_bytes, installed, public_keys=None):
    """Authenticate the manifest, then require it to describe this release and a newer version. -> VerifiedUpdate."""
    keys = TRUSTED_PUBLIC_KEYS if public_keys is None else public_keys
    signer = verify_signature(manifest_bytes, signature_bytes, keys)       # nothing in the manifest is read before this
    manifest = parse_manifest(manifest_bytes)
    version = parse_version(manifest.version)
    mismatch = None
    if version != release.version:
        mismatch = "its version"
    elif manifest.zip != release.package.name:
        mismatch = "its file name"
    elif manifest.size != release.package.size:
        mismatch = "its size"
    elif release.package.sha256 is not None and release.package.sha256 != manifest.sha256:
        mismatch = "its checksum"
    if mismatch:
        raise UpdateError("mismatch", f"{_NOT_VERIFIED} ({mismatch.capitalize()} does not match the signed manifest.)")
    if version <= installed:
        raise UpdateError("downgrade", "This release is not newer than the installed version, so it will not be installed.")
    return VerifiedUpdate(release, manifest, signer)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(path, manifest):
    """A downloaded zip against its verified manifest: exact size, then SHA-256."""
    try:
        if Path(path).stat().st_size != manifest.size:
            raise UpdateError("mismatch", _NOT_VERIFIED + " (The downloaded file has the wrong size.)")
        if file_sha256(path) != manifest.sha256:
            raise UpdateError("mismatch", _NOT_VERIFIED + " (The downloaded file has the wrong checksum.)")
    except OSError:
        raise UpdateError("package_unreadable", "The downloaded update could not be read. Please try again.") from None
