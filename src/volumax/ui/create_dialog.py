"""Create Archive page."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..compat import is_relative_to, safe_exists, safe_is_dir
from ..archive_manager import ArchiveManager
from ..backends.base import BackendResult
from ..compression import PRESETS, analyze_sources, plan_compression
from ..extras import export_create_script, verify_created, write_sha256_sidecar
from ..jobs import get_job_queue
from ..security import assess_password
from ..settings import get_settings
from .widgets.workers import run_in_background

logger = logging.getLogger("volumax.ui.create")

FORMATS = ["7z", "zip", "tar.xz", "tar.gz", "tar.bz2", "tar"]
PRESET_LABELS = {
    "store": "Store (no compression)",
    "fastest": "Fastest",
    "fast": "Fast",
    "normal": "Normal",
    "maximum": "Maximum (recommended)",
    "ultra": "Ultra (smallest, slowest)",
}
EXTENSIONS = {"7z": ".7z", "zip": ".zip", "tar": ".tar", "tar.gz": ".tar.gz",
              "tar.bz2": ".tar.bz2", "tar.xz": ".tar.xz"}



class CreateArchiveDialog(QWidget):
    def __init__(self, manager: ArchiveManager, embedded: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.settings = get_settings()
        self.sources: list[Path] = []
        self.setAcceptDrops(True)
        self._plan_task = None
        self._plan_timer = QTimer(self)
        self._plan_timer.setSingleShot(True)
        self._plan_timer.setInterval(250)
        self._plan_timer.timeout.connect(self._update_plan_preview)
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Create Archive")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        src_group = QGroupBox("Source Files && Folders  (you can also drag them in)")
        src_layout = QVBoxLayout(src_group)
        self.source_list = QListWidget()
        self.source_list.setMinimumHeight(110)
        self.source_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        src_layout.addWidget(self.source_list)
        btn_row = QHBoxLayout()
        for text, slot, obj in (
            ("Add Files", self._add_files, None),
            ("Add Folder", self._add_folder, "secondary"),
            ("Remove Selected", self._remove_selected, "secondary"),
            ("Clear", self._clear_sources, "secondary"),
        ):
            b = QPushButton(text)
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        btn_row.addStretch()
        src_layout.addLayout(btn_row)
        layout.addWidget(src_group)

        opt = QGroupBox("Options")
        form = QFormLayout(opt)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output archive path (suggested automatically)…")
        btn_browse = QPushButton("Browse")
        btn_browse.setObjectName("secondary")
        btn_browse.clicked.connect(self._browse_output)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(btn_browse)
        form.addRow("Output:", out_row)

        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS)
        self.format_combo.setCurrentText(self.settings.get("default_format", "7z"))
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        form.addRow("Format:", self.format_combo)

        self.preset_combo = QComboBox()
        for key in PRESETS:
            self.preset_combo.addItem(PRESET_LABELS[key], key)
        idx = self.preset_combo.findData(self.settings.compression_preset)
        self.preset_combo.setCurrentIndex(idx if idx >= 0 else self.preset_combo.findData("maximum"))
        self.preset_combo.currentIndexChanged.connect(lambda _i: self._plan_timer.start())
        form.addRow("Compression:", self.preset_combo)

        self.plan_label = QLabel("Add files to see which method will be used.")
        self.plan_label.setWordWrap(True)
        self.plan_label.setStyleSheet("color: #a9b6cb;")
        form.addRow("", self.plan_label)

        adv = QHBoxLayout()
        self.solid_check = QCheckBox("Solid (smaller; 7z only)")
        self.solid_check.setChecked(bool(self.settings.get("solid", True)))
        self.smart_check = QCheckBox("Smart mode")
        self.smart_check.setToolTip(
            "Analyses your files: uses PPMd for text/code and a fast level for\n"
            "already-compressed media (jpg, mp4, zip…). Usually smaller AND faster."
        )
        self.smart_check.setChecked(bool(self.settings.get("smart_compression", True)))
        self.smart_check.toggled.connect(lambda _c: self._plan_timer.start())
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 64)
        self.threads_spin.setSpecialValueText("Auto")
        self.threads_spin.setValue(int(self.settings.get("threads", 0)))
        adv.addWidget(self.solid_check)
        adv.addWidget(self.smart_check)
        adv.addWidget(QLabel("Threads:"))
        adv.addWidget(self.threads_spin)
        adv.addStretch()
        form.addRow("Advanced:", adv)

        self.split_check = QCheckBox("Split into volumes of")
        self.split_spin = QSpinBox()
        self.split_spin.setRange(1, 100000)
        self.split_spin.setSuffix(" MB")
        self.split_spin.setValue(self.settings.volume_size_mb)
        self.split_spin.setEnabled(False)
        self.split_check.toggled.connect(self.split_spin.setEnabled)
        split_row = QHBoxLayout()
        split_row.addWidget(self.split_check)
        split_row.addWidget(self.split_spin)
        split_row.addStretch()
        form.addRow("", split_row)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Password (AES-256) — leave empty for none")
        self.password_edit.textChanged.connect(self._on_password_changed)
        form.addRow("Password:", self.password_edit)
        self.password2_edit = QLineEdit()
        self.password2_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password2_edit.setPlaceholderText("Repeat password")
        form.addRow("Confirm:", self.password2_edit)
        self.strength_label = QLabel("")
        form.addRow("", self.strength_label)

        self.encrypt_names = QCheckBox("Also hide file names (7z only, recommended with a password)")
        self.encrypt_names.setChecked(True)
        form.addRow("", self.encrypt_names)
        self.verify_check = QCheckBox("Verify the archive after creating it (recommended)")
        self.verify_check.setChecked(bool(self.settings.get("verify_after_create", True)))
        form.addRow("", self.verify_check)
        self.sidecar_check = QCheckBox("Also save a SHA-256 checksum file (.sha256)")
        self.sidecar_check.setChecked(bool(self.settings.get("write_checksum_sidecar", False)))
        form.addRow("", self.sidecar_check)
        layout.addWidget(opt)

        self.btn_create = QPushButton("Create Archive")
        self.btn_create.setObjectName("gold")
        self.btn_create.clicked.connect(self._create)
        self.btn_script = QPushButton("Export as script…")
        self.btn_script.setObjectName("secondary")
        self.btn_script.setToolTip("Save these settings as a .bat/.ps1/.sh script for scheduled or automated backups.\nThe password is never written into the script — it is asked for when the script runs.")
        self.btn_script.clicked.connect(self._export_script)
        row = QHBoxLayout()
        row.addWidget(self.btn_create, 1)
        row.addWidget(self.btn_script)
        layout.addLayout(row)
        layout.addStretch()
        self._on_format_changed(self.format_combo.currentText())

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.add_sources([Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()])

    # ------------------------------------------------------------- sources
    def add_sources(self, paths: list[Path]) -> None:
        for p in paths:
            if safe_exists(p) and p not in self.sources:
                self.sources.append(p)
                self.source_list.addItem(str(p))
        self._suggest_output()
        self._plan_timer.start()

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files")
        self.add_sources([Path(f) for f in files])

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.add_sources([Path(folder)])

    def _remove_selected(self) -> None:
        for item in self.source_list.selectedItems():
            self.sources.remove(Path(item.text()))
            self.source_list.takeItem(self.source_list.row(item))
        self._plan_timer.start()

    def _clear_sources(self) -> None:
        self.sources.clear()
        self.source_list.clear()
        self.plan_label.setText("Add files to see which method will be used.")

    # ---------------------------------------------------------- format/out
    def _ext(self) -> str:
        return EXTENSIONS[self.format_combo.currentText()]

    def _on_format_changed(self, fmt: str) -> None:
        is7z, is_tar_codec = fmt == "7z", fmt.startswith("tar.")
        self.solid_check.setEnabled(is7z)
        self.encrypt_names.setEnabled(is7z)
        if is7z:
            self.encrypt_names.setChecked(True)   # strongest option by default
        else:
            self.encrypt_names.setChecked(False)
        for w in (self.password_edit, self.password2_edit):
            w.setEnabled(not is_tar_codec and fmt != "tar")
            if not w.isEnabled():
                w.clear()
        self.preset_combo.setEnabled(fmt != "tar")
        # keep the typed name, swap only the extension
        text = self.output_edit.text().strip()
        if text:
            self.output_edit.setText(self._with_extension(text))
        else:
            self._suggest_output()
        self._plan_timer.start()

    def _with_extension(self, path: str) -> str:
        lower = path.lower()
        known = sorted(EXTENSIONS.values(), key=len, reverse=True) + [
            ".tgz", ".txz", ".tbz2", ".gz", ".bz2", ".xz"
        ]
        for ext in known:
            if lower.endswith(ext):
                path = path[: -len(ext)]
                break
        return path + self._ext()

    def _suggest_output(self) -> None:
        if self.output_edit.text().strip() or not self.sources:
            return
        first = self.sources[0]
        if len(self.sources) == 1:
            stem = first.name if safe_is_dir(first) else first.stem
        else:
            stem = first.parent.name or "archive"
        self.output_edit.setText(str(first.parent / (stem or "archive")) + self._ext())

    def _browse_output(self) -> None:
        start = self.output_edit.text().strip() or (str(self.sources[0].parent) if self.sources else "")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Archive As", start, f"Archive (*{self._ext()})"
        )
        if path:
            self.output_edit.setText(self._with_extension(path))

    # ------------------------------------------------------------- passwords
    def _on_password_changed(self, text: str) -> None:
        if not text:
            self.strength_label.setText("")
            return
        s = assess_password(text)
        colors = ["#e5484d", "#e5484d", "#f5a524", "#3fb950", "#3fb950"]
        self.strength_label.setStyleSheet(f"color: {colors[min(s.score, 4)]};")
        hint = f" — {s.hints[0]}" if s.hints else ""
        self.strength_label.setText(f"Strength: {s.label}{hint}")

    # ------------------------------------------------------------ plan preview
    def _update_plan_preview(self) -> None:
        if not self.sources:
            return
        sources = list(self.sources)
        fmt = self.format_combo.currentText()
        preset = self.preset_combo.currentData()
        smart, solid = self.smart_check.isChecked(), self.solid_check.isChecked()
        codec = {"tar.gz": "gzip", "tar.bz2": "bzip2", "tar.xz": "xz"}.get(fmt, fmt)
        self.plan_label.setText("Analysing files…")

        def work():
            prof = analyze_sources(sources)
            plan = plan_compression(codec, preset=preset, profile=prof, smart=smart, solid=solid)
            return prof, plan

        def done(res) -> None:
            prof, plan = res
            mb = prof.total_bytes / (1024 * 1024)
            self.plan_label.setText(
                f"{prof.file_count:,} files, {mb:,.1f} MB → {plan.description}"
            )

        self._plan_task = run_in_background(work, done, lambda m: self.plan_label.setText(""))

    # ----------------------------------------------------------------- create
    def _create(self) -> None:
        if not self.sources:
            QMessageBox.warning(self, "No sources", "Add at least one file or folder.")
            return
        out = self.output_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "No output", "Specify an output archive path.")
            return
        password = self.password_edit.text() or None
        if password and password != self.password2_edit.text():
            QMessageBox.warning(
                self, "Passwords differ",
                "The two passwords don't match. A typo here would make the archive unrecoverable.",
            )
            return

        archive = Path(self._with_extension(out))
        if safe_exists(archive):
            ans = QMessageBox.question(
                self, "Replace file?", f"{archive.name} already exists. Replace it?"
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        if any(archive == s or is_relative_to(archive, s) for s in self.sources if safe_is_dir(s)):
            QMessageBox.warning(
                self, "Output inside source",
                "The archive would be created inside a folder you are archiving. "
                "Choose a different output location.",
            )
            return

        fmt = self.format_combo.currentText()
        preset = self.preset_combo.currentData()
        options = dict(
            preset=preset,
            solid=self.solid_check.isChecked(),
            smart=self.smart_check.isChecked(),
            threads=self.threads_spin.value(),
            max_dictionary_mb=int(self.settings.get("max_dictionary_mb", 512)),
        )
        encrypt = self.encrypt_names.isChecked()
        sources = list(self.sources)  # snapshot: the list may be edited before the job runs
        volume = f"{self.split_spin.value()}m" if self.split_check.isChecked() else None
        manager = self.manager

        verify = self.verify_check.isChecked() and volume is None
        sidecar = self.sidecar_check.isChecked()
        for key, value in (("verify_after_create", self.verify_check.isChecked()),
                           ("write_checksum_sidecar", sidecar),
                           ("compression_preset", preset), ("default_format", fmt),
                           ("solid", options["solid"]), ("smart_compression", options["smart"]),
                           ("threads", options["threads"])):
            self.settings.set(key, value)
        self.settings.save()

        def job(progress=None, cancel=None, pause=None):
            guard = _space_problem(archive.parent, sources)
            if guard:
                return BackendResult(False, guard)
            backup = None
            if safe_exists(archive):  # keep the old file until the new one is safely built
                backup = archive.with_name(archive.name + ".volumax-old")
                try:
                    if safe_exists(backup):
                        backup.unlink()
                    archive.replace(backup)
                except OSError as exc:
                    return BackendResult(False, f"Cannot replace the existing file: {exc}")
            result = manager.create(
                archive, sources, format=fmt, password=password,
                encrypt_filenames=encrypt, volume_size=volume,
                progress=progress, cancel=cancel, pause=pause, **options,
            )
            if result.success and verify:
                ok, note = verify_created(manager, archive, password, sidecar=sidecar)
                if not ok:
                    result = BackendResult(False, note)
                else:
                    result.message = f"{result.message} {note}".strip()
            elif result.success and sidecar:
                try:
                    write_sha256_sidecar(archive)
                except OSError:
                    pass
            if backup is not None:
                if result.success:
                    backup.unlink(missing_ok=True)
                else:  # failed or cancelled: put the original back
                    try:
                        if safe_exists(archive):
                            archive.unlink()
                        backup.replace(archive)
                    except OSError:
                        pass
            return result

        j = get_job_queue().submit(f"Create {archive.name}", job)
        self.plan_label.setText(f"Queued as job {j.id} — progress is in the Job Queue.")


    def _export_script(self) -> None:
        if not self.sources:
            QMessageBox.warning(self, "No sources", "Add at least one file or folder first.")
            return
        out = self.output_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "No output", "Specify an output archive path first.")
            return
        native = "bat" if os.name == "nt" else "sh"
        path, chosen = QFileDialog.getSaveFileName(
            self, "Export script", f"volumax-backup.{native}",
            "Batch file (*.bat);;PowerShell (*.ps1);;Shell script (*.sh)",
        )
        if not path:
            return
        shell = Path(path).suffix.lower().lstrip(".")
        shell = shell if shell in ("bat", "ps1", "sh") else native
        fmt = self.format_combo.currentText()
        if fmt not in ("7z", "zip"):
            QMessageBox.information(self, "Format", "Script export supports 7z and ZIP; exporting as 7z.")
            fmt = "7z"
        try:
            text = export_create_script(
                str(self.manager.engine.exe or "7z"), Path(self._with_extension(out)), list(self.sources),
                fmt=fmt, preset=self.preset_combo.currentData(), solid=self.solid_check.isChecked(),
                threads=self.threads_spin.value(), shell=shell,
                encrypt=bool(self.password_edit.text()), encrypt_filenames=self.encrypt_names.isChecked(),
            )
            with open(path, "w", encoding="utf-8", newline="") as fh:   # py3.8-safe
                fh.write(text)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self.plan_label.setText(f"Script saved: {path}")


def _space_problem(folder: Path, sources) -> str:
    """Plain-language message when the output drive clearly cannot hold the result."""
    import shutil

    try:
        probe = folder if safe_exists(folder) else folder.parent
        free = shutil.disk_usage(probe).free
    except OSError:
        return ""
    prof = analyze_sources(list(sources))
    if free < 50 * 1024 * 1024 or free < prof.low_gain_bytes:
        return (f"Not enough free space on the destination drive ({free // (1024 * 1024):,} MB free). "
                "Free some space or choose another location.")
    return ""
