"""Application entry — creates QApplication and MainWindow."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .logging_config import setup_logging
from .settings import get_settings
from .ui.main_window import MainWindow

logger = logging.getLogger("volumax.app")


def _install_excepthook() -> None:
    """Log every unhandled exception and show it instead of dying silently."""

    def hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logger.critical("Unhandled exception:\n%s", text)
        try:
            box = QMessageBox(QMessageBox.Icon.Critical, "VOLUMAX — unexpected error",
                              f"{exc_type.__name__}: {exc}")
            box.setDetailedText(text)
            box.exec()
        except Exception:
            pass

    sys.excepthook = hook


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    settings = get_settings()
    setup_logging(level=settings.get("log_level", "INFO"))

    app = QApplication(argv)
    app.setApplicationName("VOLUMAX")
    app.setOrganizationName("Bravo Projects")
    app.setApplicationVersion(__version__)
    _install_excepthook()

    window = MainWindow()
    window.show()

    # "Open with VOLUMAX" / `volumax archive.7z`
    args = [Path(a) for a in argv[1:] if not a.startswith("-")]
    if args and args[0].is_file():
        window.open_archive(args[0])
    return app.exec()
