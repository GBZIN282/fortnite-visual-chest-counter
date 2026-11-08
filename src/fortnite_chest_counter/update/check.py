"""
One complete update check: find the newest release, fetch its two signing files, verify them.

"failed" means the check could not be done (no internet, GitHub limiting, ...), which says nothing about any release.
"rejected" means a newer release exists but did not verify. If the newest release is rejected the check stops there: older
releases are not tried, because a bad signature on the newest one is something to notice rather than work around.
"""

import threading
from dataclasses import dataclass

from fortnite_chest_counter.update import authenticity, releases
from fortnite_chest_counter.update.releases import GITHUB, UpdateError
from fortnite_chest_counter.version import __version__


@dataclass(frozen=True)
class CheckResult:
    status: str                            # up_to_date | available | failed | rejected
    message: str
    kind: str | None = None                # the UpdateError kind, for failed and rejected
    update: authenticity.VerifiedUpdate | None = None


def check_for_update(installed=__version__, source=GITHUB, public_keys=None):
    """-> CheckResult. Never raises for anything the network or GitHub can do. Blocks: the app uses BackgroundCheck."""
    current = releases.parse_version(installed)
    if current is None:
        return CheckResult("failed", f"The installed version ({installed}) is not a release version.", "bad_version")
    try:
        release = releases.select_update(releases.fetch_release_list(source), current, source)
        if release is None:
            return CheckResult("up_to_date", f"You have the latest version (v{installed}).")
        manifest = releases.fetch_small_asset(release.manifest, source)
        signature = releases.fetch_small_asset(release.signature, source)
    except UpdateError as error:
        return CheckResult("failed", str(error), error.kind)
    try:
        update = authenticity.verify_release(release, manifest, signature, current, public_keys)
    except UpdateError as error:
        return CheckResult("rejected", str(error), error.kind)
    return CheckResult("available", f"Version v{release.version_text} is available.", update=update)


class BackgroundCheck:
    """Runs one check on its own thread. The window polls result() from a timer, the same way it reads the counting worker
    (gui/worker.py), so it never waits for the network."""

    def __init__(self, **options):
        self._options = options
        self._result = None

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="update-check").start()
        return self

    def _run(self):
        try:
            self._result = check_for_update(**self._options)
        except Exception as error:         # a bug in the check must never take the app down or look like an update
            self._result = CheckResult("failed", f"The update check failed ({type(error).__name__}).", "unexpected")

    def result(self):
        """The CheckResult, or None while the check is still running."""
        return self._result
