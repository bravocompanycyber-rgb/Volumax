"""Main application window — dark navy professional UI."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..archive_manager import ArchiveManager
from ..config import ASSETS_DIR
from ..jobs import get_job_queue
from ..settings import get_settings
from .archive_browser import ArchiveBrowserPage
from .create_dialog import CreateArchiveDialog
from .extract_dialog import ExtractArchiveDialog
from .package_dialog import IndependentPackageDialog
from .queue_panel import QueuePanel
from .settings_dialog import SettingsDialog
from .integrity_page import IntegrityPage
from .duplicates_page import DuplicatesPage
from .volume_dialog import VolumeDialog

logger = logging.getLogger("volumax.ui.main")

# ---------------------------------------------------------------------------
# Colour palette — dark navy / charcoal with blue & gold accents
# ---------------------------------------------------------------------------

COLORS = {
    "bg_dark": "#0f1419",
    "bg_panel": "#1a2332",
    "bg_card": "#243044",
    "bg_hover": "#2d3a50",
    "border": "#2a3548",
    "text": "#e8eef7",
    "text_dim": "#8b9bb4",
    "accent_blue": "#3b82f6",
    "accent_gold": "#d4a017",
    "success": "#22c55e",
    "danger": "#ef4444",
    "warning": "#f59e0b",
}


STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS["bg_dark"]};
    color: {COLORS["text"]};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
QToolBar {{
    background-color: {COLORS["bg_panel"]};
    border-bottom: 1px solid {COLORS["border"]};
    spacing: 6px;
    padding: 4px;
}}
QToolBar QToolButton {{
    background: transparent;
    color: {COLORS["text"]};
    border: none;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 2px;
}}
QToolBar QToolButton:hover {{
    background-color: {COLORS["bg_hover"]};
}}
QToolBar QToolButton:checked {{
    background-color: {COLORS["accent_blue"]};
    color: white;
}}
QListWidget {{
    background-color: {COLORS["bg_panel"]};
    border: none;
    border-right: 1px solid {COLORS["border"]};
    outline: none;
    padding: 8px 0;
}}
QListWidget::item {{
    color: {COLORS["text_dim"]};
    padding: 12px 18px;
    border-radius: 6px;
    margin: 2px 8px;
}}
QListWidget::item:selected {{
    background-color: {COLORS["accent_blue"]};
    color: white;
}}
QListWidget::item:hover:!selected {{
    background-color: {COLORS["bg_hover"]};
    color: {COLORS["text"]};
}}
QStatusBar {{
    background-color: {COLORS["bg_panel"]};
    color: {COLORS["text_dim"]};
    border-top: 1px solid {COLORS["border"]};
}}
QPushButton {{
    background-color: {COLORS["accent_blue"]};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: #2563eb;
}}
QPushButton:disabled {{
    background-color: {COLORS["bg_hover"]};
    color: {COLORS["text_dim"]};
}}
QPushButton#secondary {{
    background-color: {COLORS["bg_card"]};
    border: 1px solid {COLORS["border"]};
}}
QPushButton#secondary:hover {{
    background-color: {COLORS["bg_hover"]};
}}
QPushButton#gold {{
    background-color: {COLORS["accent_gold"]};
    color: #1a1a1a;
}}
QPushButton#danger {{
    background-color: {COLORS["danger"]};
}}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {COLORS["accent_blue"]};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {COLORS["accent_blue"]};
}}
QGroupBox {{
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {COLORS["accent_gold"]};
}}
QProgressBar {{
    background-color: {COLORS["bg_card"]};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: {COLORS["text"]};
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {COLORS["accent_blue"]};
    border-radius: 4px;
}}
QScrollBar:vertical {{
    background: {COLORS["bg_panel"]};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {COLORS["bg_hover"]};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QTableWidget {{
    background-color: {COLORS["bg_panel"]};
    gridline-color: {COLORS["border"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
}}
QHeaderView::section {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_dim"]};
    padding: 8px;
    border: none;
    border-bottom: 1px solid {COLORS["border"]};
}}
QDialog {{
    background-color: {COLORS["bg_dark"]};
}}
"""


NAV_ITEMS = [
    ("Home", "dashboard"),
    ("Create Archive", "create"),
    ("Extract Archive", "extract"),
    ("Archive Browser", "browser"),
    ("Independent Packages", "packages"),
    ("Split Volumes", "volumes"),
    ("Integrity & Checksums", "integrity"),
    ("Duplicate Finder", "duplicates"),
    ("Job Queue", "queue"),
    ("Settings", "settings"),
]


class DashboardPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        title = QLabel("VOLUMAX")
        title.setStyleSheet(
            f"font-size: 28px; font-weight: 700; color: {COLORS['accent_gold']};"
        )
        layout.addWidget(title)

        subtitle = QLabel("Professional Archive Management")
        subtitle.setStyleSheet(f"font-size: 15px; color: {COLORS['text_dim']};")
        layout.addWidget(subtitle)

        layout.addSpacing(24)

        cards = QHBoxLayout()
        for label, desc in [
            ("Create", "Build ZIP, 7Z, TAR archives"),
            ("Extract", "Safe extraction with protections"),
            ("Packages", "Independent size-limited ZIPs"),
            ("Volumes", "Multipart split archives"),
        ]:
            card = QFrame()
            card.setStyleSheet(
                f"background-color: {COLORS['bg_card']}; border-radius: 10px; padding: 16px;"
            )
            card.setFixedHeight(120)
            cl = QVBoxLayout(card)
            t = QLabel(label)
            t.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {COLORS['accent_blue']};")
            d = QLabel(desc)
            d.setStyleSheet(f"color: {COLORS['text_dim']};")
            d.setWordWrap(True)
            cl.addWidget(t)
            cl.addWidget(d)
            cl.addStretch()
            cards.addWidget(card)
        layout.addLayout(cards)
        layout.addStretch()


class PlaceholderPage(QWidget):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size: 22px; font-weight: 600; color: {COLORS['text']};")
        layout.addWidget(lbl)
        hint = QLabel("This page is available from the navigation.")
        hint.setStyleSheet(f"color: {COLORS['text_dim']};")
        layout.addWidget(hint)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VOLUMAX — Professional Archive Manager")
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)

        self.manager = ArchiveManager()
        self.settings = get_settings()
        self.queue = get_job_queue()

        # Icon
        icon_path = ASSETS_DIR / "logo.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        self.setStyleSheet(STYLESHEET)

        # Restore geometry if saved
        geo = self.settings.get("window_geometry")
        if geo:
            try:
                self.restoreGeometry(bytes.fromhex(geo))
            except Exception:
                pass

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Side navigation
        self.nav = QListWidget()
        self.nav.setFixedWidth(220)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for label, key in NAV_ITEMS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._on_nav)
        root.addWidget(self.nav)

        # Content stack
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # Pages
        self.pages: dict[str, QWidget] = {}
        self.pages["dashboard"] = DashboardPage()
        self.pages["create"] = CreateArchiveDialog(self.manager, embedded=True)
        self.pages["extract"] = ExtractArchiveDialog(self.manager, embedded=True)
        self.pages["browser"] = ArchiveBrowserPage(self.manager)
        self.pages["packages"] = IndependentPackageDialog(self.manager, embedded=True)
        self.pages["volumes"] = VolumeDialog(self.manager, embedded=True)
        self.pages["integrity"] = IntegrityPage(self.manager)
        self.pages["duplicates"] = DuplicatesPage()
        self.pages["queue"] = QueuePanel(self.queue)
        self.pages["settings"] = SettingsDialog(self.settings, embedded=True)

        for label, key in NAV_ITEMS:
            self.stack.addWidget(self.pages[key])

        self.nav.setCurrentRow(0)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

        # Toolbar
        tb = QToolBar("Main")
        tb.setIconSize(QSize(18, 18))
        tb.setMovable(False)
        self.addToolBar(tb)

        act_open = QAction("Open Archive", self)
        act_open.triggered.connect(self._open_archive)
        tb.addAction(act_open)

        act_create = QAction("Quick Create", self)
        act_create.triggered.connect(lambda: self.nav.setCurrentRow(1))
        tb.addAction(act_create)

    def _on_nav(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    def _open_archive(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Archive",
            self.settings.get("last_extract_dir", ""),
            "Archives (*.zip *.7z *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz);;All Files (*)",
        )
        if path:
            self.nav.setCurrentRow(3)  # browser
            browser = self.pages["browser"]
            if hasattr(browser, "load_archive"):
                browser.load_archive(Path(path))

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.settings.set("window_geometry", self.saveGeometry().toHex().data().decode())
            self.settings.save()
        except Exception:
            pass
        super().closeEvent(event)
