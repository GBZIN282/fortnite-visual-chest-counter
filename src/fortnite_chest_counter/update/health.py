"""
The new version's proof that it really started, written once its window is up and its event loop is running.

The install helper starts the app with --update-health REPORT NONCE. The nonce is new for every installation, so only this start of
this version can produce an acceptable report. If anything goes wrong here no report appears, which correctly counts as a failed start.
"""

import json
import os
from pathlib import Path

from fortnite_chest_counter import paths
from fortnite_chest_counter.update.install_helper import HEALTH_FORMAT, write_json_durably
from fortnite_chest_counter.version import __version__


def write_report(report_path, nonce):
    try:
        write_json_durably(Path(report_path), {"format": HEALTH_FORMAT, "stage": "ready", "nonce": nonce, "version": __version__, "pid": os.getpid(),
                                               "app_dir": str(paths.APP_DIR)})
    except OSError:
        pass
