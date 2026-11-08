"""
The built-in updater (v0.2.3). No Qt and nothing from the detector or the counter in here.

    releases.py       which releases exist on GitHub, and which one is the newest valid update
    authenticity.py   the signed manifest: only a release signed by a trusted key is ever offered
    trust.py          the public keys this copy of the app trusts
    check.py          one complete check, on a background thread so the app window never waits for the network

docs/UPDATE_SIGNING.md explains the signing keys and the release files.
"""
