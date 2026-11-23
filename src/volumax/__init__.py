"""VOLUMAX — Professional Windows Archive Management Application."""

__version__ = "1.0.0"
__author__ = "Bravo Projects"
__app_name__ = "VOLUMAX"

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
ENGINES_DIR = PROJECT_ROOT / "engines"
LOGS_DIR = PROJECT_ROOT / "logs"
