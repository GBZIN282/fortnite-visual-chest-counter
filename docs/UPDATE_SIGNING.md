# Update signing

Internal / maintainer note. User-facing docs do not need any of this.

The built-in updater installs only releases signed with a private key that never leaves the maintainer's control. This file
covers what that protects, where trust comes from, and how to create, store, use and replace the keys.

**Current state (2026-11-08):** no production key exists yet and `TRUSTED_PUBLIC_KEYS` in
[`update/trust.py`](../src/fortnite_chest_counter/update/trust.py) is empty, so every release is rejected. Development and
tests use temporary keys generated during each test run.

## What this protects

A checksum published next to a zip only proves the download is not corrupted: anyone who can change the zip on GitHub can
change the checksum too. A signature proves the release was made by whoever holds the private key, so write access to the
GitHub repository is not enough to get an update installed.

It does not:

- Make the launcher or any other Windows program Authenticode-signed. See [WINDOWS_TRUST.md](WINDOWS_TRUST.md).
- Protect a manual download. A copy installed by hand is only as trustworthy as the place it came from.

## Where trust comes from

The only keys that count are the literal list in `update/trust.py` **inside the installed app**.

- A release cannot supply a key. Key fields in the manifest or signature file, extra release files, API fields and release
  notes are ignored. The updater fetches only the manifest and its signature.
- A key id only selects among the keys already installed. The key bytes that verify a signature always come from the
  installed list, so a forged or colliding id gains nothing.
- There is no trust on first use. An empty list rejects everything.
- Verification changes nothing. The list is an immutable constant, and no setting, environment variable or file can extend it.

The list changes only when a new version of the app is installed, and that version must first pass verification by a key the
installed app already trusts. **The updater must verify a release using the installed app's list before unpacking or running
anything from the zip. Nothing from a new package may take part in deciding whether that package is trusted.**

The limit: whoever holds a trusted private key can sign a release that changes the list. That is why the keys are protected as
described below.

### First install

v0.2.2 has no updater and no key. Installing the first signed version by hand (v0.2.3) establishes the trust list for every
later update, so that download must come from the official GitHub release page.

## Files in each release

| Asset | Used by |
|---|---|
| `Fortnite-Visual-Chest-Counter-vX.Y.Z.zip` | The updater and manual installs |
| `update-manifest.json` | The updater: what was released |
| `update-manifest.json.sig` | The updater: the signature(s) of the manifest |
| `SHA256SUMS.txt` | People checking a manual download |

`update-manifest.json` is canonical JSON on one line, with sorted keys, no spaces and a final newline. The same inputs always
give the same bytes, and any other form is rejected:

```json
{"format":1,"product":"fortnite-visual-chest-counter","sha256":"<hex>","size":155573320,"version":"0.2.3","zip":"Fortnite-Visual-Chest-Counter-v0.2.3.zip"}
```

`update-manifest.json.sig` holds one or more Ed25519 signatures of those exact bytes. `key_id` is the first 16 hex characters of
the SHA-256 of the raw public key:

```json
{"format":1,"signatures":[{"key_id":"<16 hex>","signature":"<base64>"}]}
```

The updater verifies the signature first, then requires the manifest to match the release tag, the zip name and size GitHub
lists, GitHub's SHA-256 digest when it reports one, and finally the downloaded file. The version must be newer than the
installed one.

## Creating the keys

Create **two** keys and ship both public keys from the first signed release: a primary for signing releases and an offline
backup that is used only if the primary is lost or stolen. With only one key, losing it forces every user into another manual
install.

Run this on a PC you trust, for each key, with a path outside the repository:

```powershell
python packaging/sign_release.py keygen --out "D:\release-keys\fcc-update-primary.pem"
python packaging/sign_release.py keygen --out "E:\offline\fcc-update-backup.pem"
```

The tool asks for a passphrase of at least 16 characters, encrypts the file, never overwrites an existing key and refuses a path
inside this repository. It prints each public key: add both to `TRUSTED_PUBLIC_KEYS`.

## Storing the keys

- Keep private keys out of this repository, build folders, GitHub secrets, CI and cloud-synced folders.
- Use a different passphrase for each key, kept in a password manager.
- Keep at least one encrypted copy of each key on separate offline media. Keep the backup key **only** offline.

## Signing a release

1. Build the release zip as usual.
2. Sign it: `python packaging/sign_release.py sign --version X.Y.Z --zip <the zip> --key <primary key file>`
3. Upload the zip and both signing files to a **draft** release, then publish it, so a half-uploaded release is never visible.

The release process must refuse to publish without both signing files, and a release build must fail if `TRUSTED_PUBLIC_KEYS` is
empty. Both checks are still to be added, together with the production keys.

## Changing keys

**Planned change.** Create the new key. Ship a release whose trust list holds the old and new keys, signed by the old key. Keep
signing with both (repeat `--key`) for as long as older copies may still need updating. Remove the old key from the list only
in a release that is still signed by it as well.

**Primary lost, backup safe.** Sign the next release with the backup key; every copy already trusts it. In that release, add a
new key to the trust list and remove the lost one.

**Primary stolen.** Treat the GitHub account as at risk too: change its password and tokens. Publish a release signed by the
backup key that removes the stolen key and adds a new one. Installed copies cannot be reached remotely, so each keeps trusting
the stolen key until it installs that release. A thief would also need a way to publish to this repository.

**Every key lost.** No installed copy can verify a new release. Create new keys and tell users to install the next version by
hand, which establishes a new trust list, the same way as the first install.
