"""PyInstaller entry point (the packaged program starts here)."""
import sys

from fortnite_chest_counter.counter import main

if __name__ == "__main__":
    sys.exit(main())
