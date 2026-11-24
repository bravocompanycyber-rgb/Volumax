"""Main application window — dark navy professional UI."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer, Signal
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
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..archive_manager import ArchiveManager
from ..config import ASSETS_DIR
from ..jobs import JobState, get_job_queue
from ..settings import get_settings
from .archive_browser import ArchiveBrowserPage
from .convert_dialog import ConvertDialog
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
    ("Convert Archive", "convert"),
    ("Independent Packages", "packages"),
    ("Split Volumes", "volumes"),
    ("Integrity & Checksums", "integrity"),
    ("Duplicate Finder", "duplicates"),
    ("Job Queue", "queue"),
    ("Settings", "settings"),
]


_ARCHIVE_SUFFIXES = (
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tbz2", ".tbz", ".txz",
    ".iso", ".cab", ".wim", ".001", ".zipx", ".jar", ".apk", ".arj", ".lzh", ".z",
)


def looks_like_archive(path: Path) -> bool:
    return path.name.lower().endswith(_ARCHIVE_SUFFIXES)


class DashboardPage(QWidget):
    """Home: quick actions, drop zone and recently opened archives."""

    navigate = Signal(str)          # page key
    open_requested = Signal(str)    # archive path

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

        drop = QLabel("Drop an archive here to browse it  ·  drop files or folders anywhere to compress them")
        drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop.setMinimumHeight(90)
        drop.setStyleSheet(
            f"border: 2px dashed {COLORS['border']}; border-radius: 12px; "
            f"color: {COLORS['text_dim']}; font-size: 14px;"
        )
        layout.addWidget(drop)

        cards = QHBoxLayout()
        for label, desc, key in [
            ("Create", "7z, ZIP, TAR.XZ/GZ/BZ2 — up to Ultra compression", "create"),
            ("Extract", "Safe extraction with protections", "extract"),
            ("Browse", "Open any archive instantly and search it", "browser"),
            ("Convert", "Re-pack RAR/ZIP into smaller 7z", "convert"),
            ("Packages", "Independent size-limited ZIPs", "packages"),
            ("Volumes", "Multipart split archives", "volumes"),
        ]:
            card = QPushButton(f"{label}\n{desc}")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setMinimumHeight(96)
            card.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; border-radius: 10px; "
                f"padding: 12px; text-align: left; color: {COLORS['text_dim']}; }}"
                f"QPushButton:hover {{ background-color: {COLORS['bg_hover']}; "
                f"color: {COLORS['text']}; }}"
            )
            card.clicked.connect(lambda _c=False, k=key: self.navigate.emit(k))
            cards.addWidget(card)
        layout.addLayout(cards)

        recent_title = QLabel("Recent archives")
        recent_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(recent_title)
        self.recent = QListWidget()
        self.recent.setMaximumHeight(220)
        self.recent.itemActivated.connect(
            lambda it: self.open_requested.emit(it.data(Qt.ItemDataRole.UserRole))
        )
        self.recent.itemClicked.connect(
            lambda it: self.open_requested.emit(it.data(Qt.ItemDataRole.UserRole))
        )
        layout.addWidget(self.recent)
        layout.addStretch()

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        for path in paths:
            p = Path(path)
            item = QListWidgetItem(f"{p.name}    —    {p.parent}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.recent.addItem(item)


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
        self._announced: set[str] = set()
        self.setAcceptDrops(True)

        # Icon
        icon_path = ASSETS_DIR / "logo.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        self.setStyleSheet(STYLESHEET)

        self._job_timer = QTimer(self)
        self._job_timer.timeout.connect(self._poll_jobs)
        self._job_timer.start(400)

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
        self.pages["convert"] = ConvertDialog(self.manager)
        self.pages["packages"] = IndependentPackageDialog(self.manager, embedded=True)
        self.pages["volumes"] = VolumeDialog(self.manager, embedded=True)
        self.pages["integrity"] = IntegrityPage(self.manager)
        self.pages["duplicates"] = DuplicatesPage()
        self.pages["queue"] = QueuePanel(self.queue)
        self.pages["settings"] = SettingsDialog(self.settings, embedded=True, manager=self.manager)

        for label, key in NAV_ITEMS:
            self.stack.addWidget(self.pages[key])

        self.nav.setCurrentRow(0)
        dash = self.pages["dashboard"]
        dash.navigate.connect(self.goto)
        dash.open_requested.connect(lambda p: self.open_archive(Path(p)))
        dash.set_recent(self.settings.get("recent_archives", []))
        self.pages["browser"].opened.connect(self._remember_recent)

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
        act_create.triggered.connect(lambda: self.goto("create"))
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
            self.open_archive(Path(path))

    # ------------------------------------------------------------ navigation
    def goto(self, key: str) -> None:
        for row in range(self.nav.count()):
            if self.nav.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.nav.setCurrentRow(row)
                return

    def open_archive(self, path: Path) -> None:
        self.goto("browser")
        self.pages["browser"].load_archive(Path(path))

    def _remember_recent(self, path: str) -> None:
        recent = [p for p in self.settings.get("recent_archives", []) if p != path]
        recent.insert(0, path)
        recent = recent[:10]
        self.settings.set("recent_archives", recent)
        self.settings.save()
        self.pages["dashboard"].set_recent(recent)

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        if len(paths) == 1 and paths[0].is_file() and looks_like_archive(paths[0]):
            self.open_archive(paths[0])
        else:
            self.goto("create")
            self.pages["create"].add_sources(paths)
        event.acceptProposedAction()

    # ----------------------------------------------------- job notifications
    def _poll_jobs(self) -> None:
        """Runs on the GUI thread: announce finished jobs and show live progress."""
        running = None
        for job in self.queue.list_jobs():
            if job.state in (JobState.RUNNING, JobState.PAUSED):
                running = job
            if job.finished_at and job.id not in self._announced:
                self._announced.add(job.id)
                self._announce(job)
        if running is not None:
            tag = "paused" if running.is_paused() else f"{running.progress}%"
            self.setWindowTitle(f"{tag} — {running.name} — VOLUMAX")
            self.status.showMessage(f"{running.name}: {running.progress}%  {running.message}")
        else:
            self.setWindowTitle("VOLUMAX — Professional Archive Manager")

    def _announce(self, job) -> None:
        if job.state == JobState.COMPLETED:
            self.status.showMessage(f"✔ {job.message}", 20000)
        elif job.state == JobState.CANCELLED:
            self.status.showMessage(f"Cancelled: {job.name}", 10000)
        elif job.state == JobState.FAILED:
            extra = getattr(job.result, "extra", None) or {}
            msg = job.error or job.message
            if extra.get("needs_password"):
                msg = "This archive is password-protected, or the password was wrong."
            self.status.showMessage(f"✖ {job.name} failed", 20000)
            QMessageBox.warning(self, f"{job.name} failed", str(msg)[:1500])

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.settings.set("window_geometry", self.saveGeometry().toHex().data().decode())
            self.settings.save()
        except Exception:
            pass
        super().closeEvent(event)
