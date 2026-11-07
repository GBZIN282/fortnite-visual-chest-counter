import os
import sys

from fortnite_chest_counter.console import CONSOLE
from fortnite_chest_counter.counter import main

code = main()
if CONSOLE.machine:
    # The desktop app's worker: everything is saved and reported by now. Leave at once - a thread may still be waiting on
    # the app's stdin pipe, and a normal interpreter shutdown can block on that pipe on Windows.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)
sys.exit(code)
