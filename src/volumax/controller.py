"""Runs CLI commands (context-menu verbs, file associations) inside the Qt app."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QSystemTrayIcon,
)

from . import cli
from .archive_manager import ArchiveManager
from .config import ASSETS_DIR
from .settings import get_settings
from .ui.widgets.workers import run_in_background

logger = logging.getLogger("volumax.controller")

IDLE_QUIT_MS = 2500  # grace period so a burst of forwarded commands isn't cut off


class QuickProgress(QObject):
    """Background job with a progress dialog that only appears if it takes > 0.4 s."""

    def __init__(self, title: str, label: str, work: Callable, on_done: Callable, on_fail: Callable):
        super().__init__()
        self._cancel = False
        self._pct = 0
        self._label = label
        self.dialog = QProgressDialog(label, "Cancel", 0, 100)
        self.dialog.setWindowTitle(title)
        self.dialog.setMinimumDuration(400)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setValue(0)
        self.dialog.canceled.connect(self._on_cancel)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)
        self._on_done, self._on_fail = on_done, on_fail

        def progress(pct, msg=""):  # worker thread: only store values
            self._pct = int(pct)

        self._task = run_in_background(
            lambda: work(progress, lambda: self._cancel), self._finish, self._fail
        )

    def _on_cancel(self) -> None:
        self._cancel = True

    def _tick(self) -> None:
        self.dialog.setValue(min(99, self._pct))

    def _close(self) -> None:
        self._timer.stop()
        self.dialog.reset()
        self.dialog.close()

    def _finish(self, result) -> None:
        self._close()
        self._on_done(result)

    def _fail(self, message: str) -> None:
        self._close()
        self._on_fail(message)


class Controller(QObject):
    def __init__(self, app: QApplication, manager: Optional[ArchiveManager] = None) -> None:
        super().__init__()
        self.app = app
        self.manager = manager or ArchiveManager()
        self.settings = get_settings()
        self.window = None
        self._busy = 0
        self._keep: List[QObject] = []
        self._tray: Optional[QSystemTrayIcon] = None
        app.setQuitOnLastWindowClosed(False)
        app.lastWindowClosed.connect(self.maybe_quit)

    # ------------------------------------------------------------------ window
    def ensure_window(self):
        if self.window is None:
            from .ui.main_window import MainWindow

            self.window = MainWindow()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        return self.window

    def window_visible(self) -> bool:
        return self.window is not None and self.window.isVisible()

    # ---------------------------------------------------------------- dispatch
    def handle(self, cmd: cli.Command) -> None:
        kind = cmd.kind
        if kind in ("", "focus"):
            self.ensure_window()
        elif kind == cli.OPEN:
            self.ensure_window().open_archive(cmd.paths[0])
        elif kind == cli.ADD:
            win = self.ensure_window()
            win.goto("create")
            win.pages["create"].add_sources([p for p in cmd.paths if p.exists()])
        elif kind in (cli.EXTRACT_HERE, cli.EXTRACT_FOLDER):
            for path in cmd.paths:
                self._extract(path, kind)
        elif kind == cli.ADD_TO:
            self._add_quick(cmd.fmt, [p for p in cmd.paths if p.exists()])

    # ----------------------------------------------------------------- extract
    def _begin(self) -> None:
        self._busy += 1

    def _end(self) -> None:
        self._busy = max(0, self._busy - 1)
        self.maybe_quit()

    def _extract(self, archive: Path, mode: str, password: Optional[str] = None) -> None:
        if not archive.is_file():
            QMessageBox.warning(None, "VOLUMAX", f"File not found:\n{archive}")
            return
        self._begin()

        def list_work():
            return self.manager.list_contents(archive, password=password)

        def listed(res) -> None:
            if not res.success:
                if res.extra.get("needs_password"):
                    pwd, ok = QInputDialog.getText(
                        None, "Password required", f"“{archive.name}” is encrypted. Password:",
                        QLineEdit.EchoMode.Password,
                    )
                    self._end()
                    if ok and pwd:
                        self._extract(archive, mode, pwd)
                    return
                QMessageBox.critical(None, "VOLUMAX — cannot open archive", f"{archive.name}\n\n{res.message}")
                self._end()
                return
            dest, note = cli.plan_extract_destination(archive, [e.path for e in res.entries], mode)
            self._run_extract(archive, dest, note, password)

        run_in_background(list_work, listed, lambda m: (self._error("Cannot read archive", m), self._end()))

    def _run_extract(self, archive: Path, dest: Path, note: str, password: Optional[str]) -> None:
        def work(progress, cancel):
            return self.manager.extract(archive, dest, password=password, progress=progress, cancel=cancel)

        def done(res) -> None:
            if res.success:
                if self.settings.get("open_folder_after_extract", True):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest)))
            elif "Cancelled" not in (res.message or ""):
                self._error(f"Extraction failed — {archive.name}", res.message)
            self._end()

        self._keep.append(QuickProgress(
            "VOLUMAX", f"Extracting {archive.name} {note}…", work, done,
            lambda m: (self._error("Extraction failed", m), self._end()),
        ))

    # --------------------------------------------------------------------- add
    def _add_quick(self, fmt: str, paths: List[Path]) -> None:
        if not paths:
            return
        out = cli.plan_quick_archive(fmt, paths)
        preset = self.settings.get("compression_preset", "maximum")
        self._begin()

        def work(progress, cancel):
            return self.manager.create(out, paths, format=fmt, preset=preset,
                                       progress=progress, cancel=cancel)

        def done(res) -> None:
            if res.success:
                self.notify("Archive created", res.message or out.name)
            elif "Cancelled" not in (res.message or ""):
                self._error(f"Could not create {out.name}", res.message)
            self._end()

        self._keep.append(QuickProgress(
            "VOLUMAX", f"Creating {out.name}…", work, done,
            lambda m: (self._error("Could not create archive", m), self._end()),
        ))

    # ------------------------------------------------------------------- misc
    def notify(self, title: str, text: str) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            if self._tray is None:
                self._tray = QSystemTrayIcon(QIcon(str(ASSETS_DIR / "logo.ico")), self)
            self._tray.show()
            self._tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 5000)
        else:
            QMessageBox.information(None, title, text)

    @staticmethod
    def _error(title: str, message: str) -> None:
        QMessageBox.critical(None, f"VOLUMAX — {title}", message or "Unknown error")

    def maybe_quit(self) -> None:
        if self._busy == 0 and not self.window_visible():
            QTimer.singleShot(IDLE_QUIT_MS, self._quit_if_idle)

    def _quit_if_idle(self) -> None:
        if self._busy == 0 and not self.window_visible():
            self.app.quit()
