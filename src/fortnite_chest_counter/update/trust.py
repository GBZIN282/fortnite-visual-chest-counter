"""
The Ed25519 public keys this copy of the app trusts to sign updates: raw 32-byte keys, as hex. See docs/UPDATE_SIGNING.md.

Public keys are not secret. The matching private keys never enter this repository or a release.

An update must carry a valid signature from one of these keys. This list changes only by installing a release that a key already
listed has signed: nothing in a release, a setting or a file can add to it.
"""

TRUSTED_PUBLIC_KEYS = (
    "ca8b875d7c1feda25b4b56b6ee29b589ab9a1ebccd764a36c0be96a57bdb5230",   # primary: signs ordinary releases
    "ffd1c3aefedd8f411a4c337a90ba90958744d4d8cb13a567f426e1e8907952e7",   # recovery: kept offline, replaces a lost or stolen primary
)
