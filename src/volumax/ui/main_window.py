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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..archive_manager import ArchiveManager
from ..compat import looks_like_archive, safe_exists  # noqa: F401  (looks_like_archive is re-exported)
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
from .tools_page import ToolsPage
from .diagnostics_page import DiagnosticsPage

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
    "text_dim": "#a9b6cb",
    "accent_blue": "#2563eb",
    "accent_blue_hover": "#1d4ed8",
    "link": "#7db4ff",
    "accent_gold": "#d4a017",
    "success": "#22c55e",
    "danger": "#fca5a5",
    "danger_fill": "#b91c1c",
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
QAbstractItemView {{
    background-color: {COLORS["bg_panel"]};
    alternate-background-color: {COLORS["bg_card"]};
    color: {COLORS["text"]};
    selection-background-color: {COLORS["accent_blue"]};
    selection-color: #ffffff;
    gridline-color: {COLORS["border"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
}}
QAbstractItemView::item:hover {{
    background-color: {COLORS["bg_hover"]};
}}
QAbstractItemView {{
    outline: 0;
}}
QAbstractItemView::item:selected, QAbstractItemView::item:selected:active,
QAbstractItemView::item:selected:!active, QAbstractItemView::item:selected:hover {{
    background-color: {COLORS["accent_blue"]};
    color: #ffffff;
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
    background-color: {COLORS["accent_blue_hover"]};
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
    background-color: {COLORS["danger_fill"]};
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
QTabWidget::pane {{
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {COLORS["bg_panel"]};
    color: {COLORS["text_dim"]};
    padding: 8px 16px;
    margin-right: 2px;
    border: 1px solid {COLORS["border"]};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:hover {{
    background-color: {COLORS["bg_hover"]};
    color: {COLORS["text"]};
}}
QTabBar::tab:selected {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text"]};
    border-bottom: 3px solid {COLORS["accent_gold"]};
    font-weight: 600;
}}
QHeaderView::section {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text"]};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {COLORS["border"]};
    font-weight: 600;
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


def apply_theme(app) -> None:
    """Application-wide dark palette + Fusion style.

    Without this, any widget the stylesheet does not name (e.g. a QTableView) falls back to the
    Windows system palette: its alternate-row colour is WHITE, which made every second row of
    the Archive Browser unreadable (light text on white).
    """
    from PySide6.QtGui import QPalette as P

    if app.property("volumax_theme_applied"):   # once per process: restyling is expensive
        return
    app.setProperty("volumax_theme_applied", True)
    app.setStyle("Fusion")  # identical rendering on Windows 8, 10 and 11
    pal = P()
    c = QColor
    for role, col in (
        (P.ColorRole.Window, COLORS["bg_dark"]), (P.ColorRole.WindowText, COLORS["text"]),
        (P.ColorRole.Base, COLORS["bg_panel"]), (P.ColorRole.AlternateBase, COLORS["bg_card"]),
        (P.ColorRole.Text, COLORS["text"]), (P.ColorRole.Button, COLORS["bg_card"]),
        (P.ColorRole.ButtonText, COLORS["text"]), (P.ColorRole.BrightText, "#ffffff"),
        (P.ColorRole.ToolTipBase, COLORS["bg_card"]), (P.ColorRole.ToolTipText, COLORS["text"]),
        (P.ColorRole.Highlight, COLORS["accent_blue"]), (P.ColorRole.HighlightedText, "#ffffff"),
        (P.ColorRole.Link, COLORS["link"]), (P.ColorRole.PlaceholderText, COLORS["text_dim"]),
    ):
        pal.setColor(role, c(col))
    for role in (P.ColorRole.Text, P.ColorRole.WindowText, P.ColorRole.ButtonText):
        pal.setColor(P.ColorGroup.Disabled, role, c(COLORS["text_dim"]))
    app.setPalette(pal)


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
    ("Tools", "tools"),
    ("Diagnostics", "diagnostics"),
    ("Settings", "settings"),
]


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

        cards = QGridLayout()
        cards.setSpacing(12)
        for i, (label, desc, key) in enumerate([
            ("Create", "7z, ZIP, TAR.XZ/GZ/BZ2 — up to Ultra compression", "create"),
            ("Extract", "Safe extraction with protections", "extract"),
            ("Browse", "Open any archive instantly and search it", "browser"),
            ("Convert", "Re-pack RAR/ZIP into smaller 7z", "convert"),
            ("Packages", "Independent size-limited ZIPs", "packages"),
            ("Volumes", "Multipart split archives", "volumes"),
        ]):
            card = QPushButton()
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setMinimumHeight(88)
            card.setAccessibleName(f"{label}: {desc}")
            card.setStyleSheet(
                f"QPushButton {{ background-color: {COLORS['bg_card']}; border-radius: 10px; }}"
                f"QPushButton:hover {{ background-color: {COLORS['bg_hover']}; }}"
            )
            inner = QVBoxLayout(card)
            inner.setContentsMargins(14, 10, 14, 10)
            head = QLabel(label)
            head.setStyleSheet(f"background: transparent; font-weight: 700; font-size: 14px; color: {COLORS['text']};")
            body = QLabel(desc)
            body.setWordWrap(True)
            body.setStyleSheet(f"background: transparent; color: {COLORS['text_dim']}; font-weight: 400;")
            for lbl in (head, body):
                lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                inner.addWidget(lbl)
            inner.addStretch()
            card.clicked.connect(lambda _c=False, k=key: self.navigate.emit(k))
            cards.addWidget(card, i // 3, i % 3)
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
        if not paths:
            hint = QListWidgetItem("No recent archives yet — open one with the button above, or drop it here.")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(hint)
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
        if safe_exists(icon_path):
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        from PySide6.QtWidgets import QApplication as _A

        if _A.instance() is not None:
            apply_theme(_A.instance())
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
        self.pages["tools"] = ToolsPage(self.manager)
        self.pages["diagnostics"] = DiagnosticsPage(self.manager)
        self.pages["settings"] = SettingsDialog(self.settings, embedded=True, manager=self.manager)

        for label, key in NAV_ITEMS:
            # Scroll wrapper: a page never gets squashed below its natural size
            # (controls stay readable on small windows / high DPI scaling).
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(self.pages[key])
            self.stack.addWidget(scroll)

        self.nav.setCurrentRow(0)
        dash = self.pages["dashboard"]
        dash.navigate.connect(self.goto)
        dash.open_requested.connect(lambda p: self.open_archive(Path(p)))
        dash.set_recent(self.settings.get("recent_archives", []))
        self.pages["browser"].opened.connect(self._remember_recent)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        if self.manager.engine.available:
            self.status.showMessage("Ready")
        else:
            self.status.showMessage("7-Zip engine not found — open Diagnostics and press Repair")
            QTimer.singleShot(400, lambda: self.goto("diagnostics"))

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
        self.pages["tools"].set_archive(Path(path))
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
            self._notify_failure(job.name, str(msg))

    def _notify_failure(self, name: str, msg: str) -> None:
        """ONE non-blocking notice at a time. A blocking dialog inside the poll timer
        re-enters it and stacks a dialog per failed job (a failed batch of 20 = 20 modals)."""
        box = getattr(self, "_fail_box", None)
        try:
            if box is not None and box.isVisible():
                self._fail_more = getattr(self, "_fail_more", 0) + 1
                box.setInformativeText(f"+{self._fail_more} more failed — details are in the Job Queue.")
                return
        except RuntimeError:  # the previous box was already deleted
            pass
        self._fail_more = 0
        box = QMessageBox(QMessageBox.Icon.Warning, f"{name} failed", msg[:1500],
                          QMessageBox.StandardButton.Ok, self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._fail_box = box
        box.open()

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.settings.set("window_geometry", self.saveGeometry().toHex().data().decode())
            self.settings.save()
        except Exception:
            pass
        super().closeEvent(event)
