"""Application entry — QApplication, single instance, CLI commands, main window."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from typing import Optional

from . import QT_BINDING, __version__, cli
from .logging_config import setup_logging
from .settings import get_settings

logger = logging.getLogger("volumax.app")

APP_USER_MODEL_ID = "BravoProjects.VOLUMAX"


def _install_excepthook() -> None:
    """Log every unhandled exception and show it instead of dying silently."""
    from PySide6.QtWidgets import QMessageBox

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


def _prepare_platform() -> None:
    """Things that must happen BEFORE QApplication exists."""
    if os.name == "nt":
        try:  # own taskbar identity (grouping, pinned-icon, toast sender)
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
    if QT_BINDING == "PySide2":  # Qt 5 needs high-DPI switched on explicitly; Qt 6 has it
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        try:
            from PySide6.QtGui import QGuiApplication

            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        except Exception:
            pass


def run(argv: Optional[list] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = argv[1:]
    if cli.wants_version(args):
        print(f"VOLUMAX {__version__} ({QT_BINDING})")
        return 0
    if cli.wants_help(args):
        print(cli.help_text())
        return 0

    if "--selftest" in args:
        i = args.index("--selftest")
        report = args[i + 1] if i + 1 < len(args) else "volumax-selftest.json"
        from .selftest import run as selftest

        return selftest(report)

    settings = get_settings()
    setup_logging(level=settings.get("log_level", "INFO"))
    cmd = cli.parse(args)

    _prepare_platform()
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .config import ASSETS_DIR
    from .controller import Controller
    from .single_instance import InstanceServer, send_to_running

    app = QApplication(argv)
    app.setApplicationName("VOLUMAX")
    app.setOrganizationName("Bravo Projects")
    app.setApplicationVersion(__version__)
    icon = ASSETS_DIR / "logo.ico"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    _install_excepthook()

    # Already running? Hand the command over (this is what makes multi-select work).
    if send_to_running(cmd if cmd.kind else cli.Command("focus")):
        return 0

    controller = Controller(app)
    server = InstanceServer(controller.handle)
    server.listen()
    if cmd.kind in ("", cli.OPEN):
        controller.handle(cmd)          # no waiting needed
    else:
        server.dispatch(cmd)            # merge with siblings from the same multi-select
    code = app.exec()
    server.close()
    return code
