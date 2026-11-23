"""Application entry — creates QApplication and MainWindow."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .logging_config import setup_logging
from .settings import get_settings
from .ui.main_window import MainWindow


def run() -> int:
    settings = get_settings()
    setup_logging(level=settings.get("log_level", "INFO"))

    app = QApplication(sys.argv)
    app.setApplicationName("VOLUMAX")
    app.setOrganizationName("Bravo Projects")
    app.setApplicationVersion("1.0.0")

    window = MainWindow()
    window.show()
    return app.exec()
