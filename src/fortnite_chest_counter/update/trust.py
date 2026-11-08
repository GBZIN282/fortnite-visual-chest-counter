"""
The Ed25519 public keys this copy of the app trusts to sign updates: raw 32-byte keys, as hex. See docs/UPDATE_SIGNING.md.

Public keys are not secret. The matching private keys never enter this repository or a release.

EMPTY during development, on purpose: with no trusted key every release is rejected, so an update can never be offered
unsigned. The production public key goes here when signing is added to the release process.
"""

TRUSTED_PUBLIC_KEYS = ()
