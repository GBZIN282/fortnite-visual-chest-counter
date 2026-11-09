"""
The built-in updater (v0.2.3). No Qt and nothing from the detector or the counter in here.

    releases.py       which releases exist on GitHub, and which one is the newest valid update
    authenticity.py   the signed manifest: only a release signed by a trusted key is ever offered
    trust.py          the public keys this copy of the app trusts
    check.py          one complete check, on a background thread so the app window never waits for the network
    download.py       resumable download of the release zip, with the speed modes
    archive.py        checks every entry of the zip before anything is written
    staging.py        unpacks into .update/new and runs the start-up checks from there
    prepare.py        the background job that does all of the above when the user asks
    install.py        starts an installation from the running app
    install_helper.py replaces the runtime, proves the new version starts, rolls back if not (standard library only)
    health.py         the new version's proof that it started

docs/UPDATER.md explains the whole process; docs/UPDATE_SIGNING.md explains the signing keys and the release files.
"""
