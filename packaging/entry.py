"""PyInstaller entry point."""
import sys

from volumax.app import run

if __name__ == "__main__":
    sys.exit(run())
