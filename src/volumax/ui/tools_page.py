"""Tools page: Preview, Compare, Find, Salvage and Small-file Pack (one tab each)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..compat import safe_exists, safe_is_dir, safe_is_file
from .. import extras, smallpack
from ..archive_manager import ArchiveManager
from ..jobs import get_job_queue
from ..listing import load_tree
from .archive_browser import ARCHIVE_FILTER
from .widgets.workers import run_in_background

logger = logging.getLogger("volumax.ui.tools")

DIM = "color: #a9b6cb;"


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 20px; font-weight: 600;")
    return lbl


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(DIM)
    return lbl


def _secondary(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("secondary")
    return b


class _PathRow(QWidget):
    """A line edit + Browse button (file or folder)."""

    def __init__(self, placeholder: str, mode: str = "archive", parent=None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        btn = _secondary("Browse")
        btn.clicked.connect(self._browse)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def _browse(self) -> None:
        if self.mode == "folder":
            p = QFileDialog.getExistingDirectory(self, "Select folder", self.edit.text())
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Select archive", self.edit.text(), ARCHIVE_FILTER)
        if p:
            self.edit.setText(p)

    def text(self) -> str:
        return self.edit.text().strip()

    def path(self) -> Path | None:
        t = self.text()
        return Path(t) if t else None


class ToolsPage(QWidget):
    def __init__(self, manager: ArchiveManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self._preview = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        lay.addWidget(_title("Tools"))
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._build_preview()
        self._build_compare()
        self._build_find()
        self._build_salvage()
        self._build_pack()

    def set_archive(self, path: Path) -> None:
        """Called when an archive is opened elsewhere: pre-fill the Preview tab."""
        self.pv_path.edit.setText(str(path))

    # ------------------------------------------------------------- preview
    def _build_preview(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_note("Look inside a file without extracting the whole archive. Text and images are shown."))
        self.pv_path = _PathRow("Archive to preview…")
        v.addWidget(self.pv_path)
        row = QHBoxLayout()
        self.pv_pass = QLineEdit()
        self.pv_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.pv_pass.setPlaceholderText("Password (if encrypted)")
        self.pv_filter = QLineEdit()
        self.pv_filter.setPlaceholderText("Filter file names…")
        self.pv_filter.textChanged.connect(self._pv_filter)
        load = QPushButton("List files")
        load.clicked.connect(self._pv_load)
        row.addWidget(self.pv_pass, 1)
        row.addWidget(self.pv_filter, 1)
        row.addWidget(load)
        v.addLayout(row)
        split = QHBoxLayout()
        self.pv_list = QListWidget()
        self.pv_list.setMinimumHeight(180)
        self.pv_list.currentItemChanged.connect(self._pv_select)
        right = QVBoxLayout()
        self.pv_text = QPlainTextEdit()
        self.pv_text.setReadOnly(True)
        self.pv_text.setMinimumHeight(180)
        self.pv_image = QLabel()
        self.pv_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pv_image.hide()
        right.addWidget(self.pv_text)
        right.addWidget(self.pv_image)
        split.addWidget(self.pv_list, 1)
        split.addLayout(right, 2)
        v.addLayout(split, 1)
        self.pv_status = _note("")
        v.addWidget(self.pv_status)
        self.tabs.addTab(w, "Preview")

    def _pv_load(self) -> None:
        arc = self.pv_path.path()
        if not arc or not safe_is_file(arc):
            QMessageBox.warning(self, "Preview", "Choose an archive first.")
            return
        pw = self.pv_pass.text() or None
        self.pv_status.setText("Reading…")

        def done(res) -> None:
            result, tree = res
            self.pv_list.clear()
            if tree is None or not tree.entries:
                self.pv_status.setText(result.message or "Could not read this archive (wrong password?).")
                return
            files = [e for e in tree.entries if not e.is_dir]
            for e in files[:20000]:
                it = QListWidgetItem(e.path)
                it.setData(Qt.ItemDataRole.UserRole, e.path)
                self.pv_list.addItem(it)
            more = f" (showing first 20,000 of {len(files):,})" if len(files) > 20000 else ""
            self.pv_status.setText(f"{len(files):,} files{more}. Select one to preview.")

        run_in_background(lambda: load_tree(self.manager, arc, pw), done, lambda m: self.pv_status.setText(m))

    def _pv_filter(self, text: str) -> None:
        t = text.lower()
        for i in range(self.pv_list.count()):
            it = self.pv_list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _pv_select(self, cur, _prev) -> None:
        if cur is None:
            return
        arc, member = self.pv_path.path(), cur.data(Qt.ItemDataRole.UserRole)
        pw = self.pv_pass.text() or None
        self.pv_status.setText("Extracting this file…")

        def done(pv) -> None:
            if self._preview is not None:
                self._preview.cleanup()
            self._preview = pv
            self.pv_image.hide()
            self.pv_text.show()
            if pv.kind == "text":
                self.pv_text.setPlainText(pv.text + ("\n\n… (truncated)" if pv.truncated else ""))
                self.pv_status.setText(member)
            elif pv.kind == "image" and pv.path:
                pix = QPixmap(str(pv.path))
                if pix.isNull():
                    self.pv_text.setPlainText("Image could not be displayed.")
                else:
                    self.pv_text.hide()
                    self.pv_image.setPixmap(pix.scaled(480, 360, Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))
                    self.pv_image.show()
                self.pv_status.setText(member)
            else:
                self.pv_text.setPlainText(pv.text)
                self.pv_status.setText(member)

        run_in_background(lambda: extras.preview_member(self.manager, arc, member, pw), done,
                          lambda m: self.pv_status.setText(m))

    # ------------------------------------------------------------- compare
    def _build_compare(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_note("Find out what differs between two archives (e.g. last week's backup and today's)."))
        self.cmp_a = _PathRow("Archive A…")
        self.cmp_b = _PathRow("Archive B…")
        v.addWidget(self.cmp_a)
        v.addWidget(self.cmp_b)
        go = QPushButton("Compare")
        go.clicked.connect(self._compare)
        v.addWidget(go)
        self.cmp_out = QPlainTextEdit()
        self.cmp_out.setReadOnly(True)
        v.addWidget(self.cmp_out, 1)
        self.tabs.addTab(w, "Compare")

    def _compare(self) -> None:
        a, b = self.cmp_a.path(), self.cmp_b.path()
        if not (a and b and safe_is_file(a) and safe_is_file(b)):
            QMessageBox.warning(self, "Compare", "Choose two archives.")
            return
        self.cmp_out.setPlainText("Comparing…")

        def done(r) -> None:
            if not r.ok:
                self.cmp_out.setPlainText(r.message)
                return
            lines = [r.message, ""]
            for title, items in (("Only in A", r.only_a), ("Only in B", r.only_b), ("Changed", r.changed)):
                if items:
                    lines.append(f"{title} ({len(items)}):")
                    lines += [f"  {x}" for x in items[:500]]
                    if len(items) > 500:
                        lines.append(f"  … and {len(items) - 500} more")
                    lines.append("")
            if r.identical:
                lines.append("The archives hold exactly the same files.")
            self.cmp_out.setPlainText("\n".join(lines))

        run_in_background(lambda: extras.compare_archives(self.manager, a, b), done, self.cmp_out.setPlainText)

    # ---------------------------------------------------------------- find
    def _build_find(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_note("Search file names inside every archive in a folder — without extracting anything. "
                          "Only the folder you choose is read."))
        self.fd_folder = _PathRow("Folder containing archives…", "folder")
        v.addWidget(self.fd_folder)
        row = QHBoxLayout()
        self.fd_pattern = QLineEdit()
        self.fd_pattern.setPlaceholderText("Name or wildcard, e.g. invoice  or  *.pdf")
        self.fd_pattern.returnPressed.connect(self._find)
        go = QPushButton("Search")
        go.clicked.connect(self._find)
        row.addWidget(self.fd_pattern, 1)
        row.addWidget(go)
        v.addLayout(row)
        self.fd_list = QListWidget()
        v.addWidget(self.fd_list, 1)
        self.fd_status = _note("")
        v.addWidget(self.fd_status)
        self.tabs.addTab(w, "Find")

    def _find(self) -> None:
        folder, pat = self.fd_folder.path(), self.fd_pattern.text().strip()
        if not folder or not safe_is_dir(folder) or not pat:
            QMessageBox.warning(self, "Find", "Choose a folder and type something to look for.")
            return
        self.fd_list.clear()
        self.fd_status.setText("Searching…")

        def done(res) -> None:
            hits, bad = res
            for h in hits:
                self.fd_list.addItem(f"{Path(h.archive).name}  →  {h.member}   ({h.size:,} bytes)")
            tail = f"  {len(bad)} archive(s) could not be read (damaged or password-protected)." if bad else ""
            self.fd_status.setText(f"{len(hits)} match(es).{tail}")

        run_in_background(lambda: extras.find_in_archives(self.manager, folder, pat), done,
                          lambda m: self.fd_status.setText(m))

    # ------------------------------------------------------------- salvage
    def _build_salvage(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_note("Archive damaged or incomplete? Salvage recovers every file that is still readable "
                          "into a new folder next to it. Your original is never modified."))
        self.sv_path = _PathRow("Damaged archive…")
        v.addWidget(self.sv_path)
        self.sv_pass = QLineEdit()
        self.sv_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.sv_pass.setPlaceholderText("Password (if encrypted)")
        v.addWidget(self.sv_pass)
        go = QPushButton("Recover what is readable")
        go.setObjectName("gold")
        go.clicked.connect(self._salvage)
        v.addWidget(go)
        self.sv_status = _note("")
        v.addWidget(self.sv_status)
        v.addStretch()
        self.tabs.addTab(w, "Salvage")

    def _salvage(self) -> None:
        arc = self.sv_path.path()
        if not arc or not safe_is_file(arc):
            QMessageBox.warning(self, "Salvage", "Choose an archive.")
            return
        pw = self.sv_pass.text() or None
        mgr = self.manager

        def job(progress=None, cancel=None, pause=None):
            r = extras.salvage(mgr, arc, arc.parent, pw, progress=progress, cancel=cancel)
            return r

        j = get_job_queue().submit(f"Salvage {arc.name}", job)
        self.sv_status.setText(f"Queued as job {j.id} — see the Job Queue. Recovered files go to a "
                               f"'{arc.stem}_salvaged' folder next to the archive.")

    # ----------------------------------------------------------- small pack
    def _build_pack(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_note(
            "Small-file Pack (.vxsp): every file is compressed on its own with Zstandard, so any single file can "
            "be read back instantly. A trained dictionary is used only when it measurably shrinks the pack by "
            "20% or more — typically for thousands of similar small files such as logs. For the smallest "
            "possible size, a normal solid 7z archive (Create Archive) is better; use this when you need fast "
            "access to individual files."))
        self.pk_src = _PathRow("Folder of small files to pack…", "folder")
        v.addWidget(self.pk_src)
        b1 = QPushButton("Create pack…")
        b1.clicked.connect(self._pack_create)
        self.pk_pack = _PathRow("Pack file (.vxsp) to unpack…")
        b2 = _secondary("Unpack…")
        b2.clicked.connect(self._pack_extract)
        v.addWidget(b1)
        v.addWidget(self.pk_pack)
        v.addWidget(b2)
        self.pk_status = _note("")
        v.addWidget(self.pk_status)
        if not smallpack.available():
            for b in (b1, b2):
                b.setEnabled(False)
            self.pk_status.setText("Needs the optional 'zstandard' package. Install it with:  pip install zstandard")
        v.addStretch()
        self.tabs.addTab(w, "Small-file Pack")

    def _pack_create(self) -> None:
        src = self.pk_src.path()
        if not src or not safe_exists(src):
            QMessageBox.warning(self, "Pack", "Choose a folder first.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Save pack", str(src.parent / (src.name + smallpack.EXT)),
                                             "VOLUMAX pack (*.vxsp)")
        if not out:
            return
        j = get_job_queue().submit(
            f"Pack {src.name}",
            lambda progress=None, cancel=None: smallpack.create_pack([src], Path(out), progress=progress, cancel=cancel),
        )
        self.pk_status.setText(f"Queued as job {j.id}.")

    def _pack_extract(self) -> None:
        pk = self.pk_pack.path()
        if not pk or not safe_is_file(pk):
            QMessageBox.warning(self, "Pack", "Choose a .vxsp file.")
            return
        dest = QFileDialog.getExistingDirectory(self, "Unpack into…", str(pk.parent))
        if not dest:
            return
        j = get_job_queue().submit(
            f"Unpack {pk.name}",
            lambda progress=None, cancel=None: smallpack.extract_pack(pk, Path(dest), progress=progress, cancel=cancel),
        )
        self.pk_status.setText(f"Queued as job {j.id}.")
