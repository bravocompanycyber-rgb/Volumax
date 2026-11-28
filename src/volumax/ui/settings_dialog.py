"""Settings page."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..compression import PRESETS
from ..settings import Settings
from .create_dialog import FORMATS, PRESET_LABELS


class SettingsDialog(QWidget):
    def __init__(self, settings: Settings, embedded: bool = False, manager=None, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.manager = manager
        self._build()

    @staticmethod
    def _spin(lo: int, hi: int, value: int, suffix: str = "") -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(int(value))
        if suffix:
            sp.setSuffix(suffix)
        return sp

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        s = self.settings
        # --- compression
        g1 = QGroupBox("Compression defaults")
        f1 = QFormLayout(g1)
        self.format = QComboBox()
        self.format.addItems(FORMATS)
        self.format.setCurrentText(s.get("default_format", "7z"))
        f1.addRow("Default format:", self.format)
        self.preset = QComboBox()
        for key in PRESETS:
            self.preset.addItem(PRESET_LABELS[key], key)
        self.preset.setCurrentIndex(max(0, self.preset.findData(s.compression_preset)))
        f1.addRow("Default compression:", self.preset)
        self.smart = QCheckBox("Smart mode (PPMd for text, fast level for media)")
        self.smart.setChecked(bool(s.get("smart_compression", True)))
        f1.addRow("", self.smart)
        self.solid = QCheckBox("Solid archives (smaller, 7z)")
        self.solid.setChecked(bool(s.get("solid", True)))
        f1.addRow("", self.solid)
        self.threads = self._spin(0, 64, s.get("threads", 0))
        self.threads.setSpecialValueText("Auto (all cores)")
        f1.addRow("CPU threads:", self.threads)
        self.dict_cap = self._spin(16, 1536, s.get("max_dictionary_mb", 512), " MB")
        self.dict_cap.setToolTip("Upper limit for the Ultra preset's dictionary. Memory use is ~10× this per thread.")
        f1.addRow("Max dictionary (Ultra):", self.dict_cap)
        layout.addWidget(g1)

        # --- packages / volumes
        g2 = QGroupBox("Packages && volumes")
        f2 = QFormLayout(g2)
        self.zip_max = self._spin(1, 102400, s.independent_zip_max_mb, " MB")
        f2.addRow("Independent ZIP max size:", self.zip_max)
        self.zip_ceiling = self._spin(0, 102400, s.independent_zip_ceiling_mb, " MB")
        self.zip_ceiling.setSpecialValueText("No extra ceiling")
        f2.addRow("Absolute file ceiling:", self.zip_ceiling)
        self.vol_size = self._spin(1, 100000, s.volume_size_mb, " MB")
        f2.addRow("Default volume size:", self.vol_size)
        layout.addWidget(g2)

        # --- safety
        g3 = QGroupBox("Extraction safety")
        f3 = QFormLayout(g3)
        self.safe = QCheckBox("Safe extraction by default")
        self.safe.setChecked(s.safe_extraction)
        f3.addRow("", self.safe)
        self.max_files = self._spin(1000, 50_000_000, s.get("max_extraction_files", 3_000_000))
        f3.addRow("Max files per archive:", self.max_files)
        layout.addWidget(g3)

        # --- general
        g4 = QGroupBox("General")
        f4 = QFormLayout(g4)
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level.setCurrentText(s.get("log_level", "INFO"))
        f4.addRow("Log level (restart to apply):", self.log_level)
        self.engine_label = QLabel(self._engine_text())
        self.engine_label.setWordWrap(True)
        self.engine_label.setStyleSheet("color: #a9b6cb;")
        f4.addRow("Engine:", self.engine_label)
        self.path_label = QLabel(str(s.path))
        self.path_label.setStyleSheet("color: #a9b6cb;")
        self.path_label.setWordWrap(True)
        f4.addRow("Settings file:", self.path_label)
        layout.addWidget(g4)
        layout.addStretch()

        row = QHBoxLayout()
        btn = QPushButton("Save Settings")
        btn.setObjectName("gold")
        btn.clicked.connect(self._save)
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.setObjectName("secondary")
        btn_reset.clicked.connect(self._reset)
        btn_open = QPushButton("Open Settings Folder")
        btn_open.setObjectName("secondary")
        btn_open.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings.path.parent)))
        )
        row.addWidget(btn)
        row.addWidget(btn_reset)
        row.addWidget(btn_open)
        row.addStretch()
        outer.addLayout(row)
        self.status = QLabel("")
        outer.addWidget(self.status)

    def _engine_text(self) -> str:
        try:
            eng = self.manager.engine
            return f"{eng.version()}\n{eng.exe}"
        except Exception as exc:  # engine missing etc.
            return f"unavailable: {exc}"

    def _save(self) -> None:
        s = self.settings
        s.update({
            "default_format": self.format.currentText(),
            "compression_preset": self.preset.currentData(),
            "smart_compression": self.smart.isChecked(),
            "solid": self.solid.isChecked(),
            "threads": self.threads.value(),
            "max_dictionary_mb": self.dict_cap.value(),
            "independent_zip_max_mb": self.zip_max.value(),
            "independent_zip_ceiling_mb": self.zip_ceiling.value(),
            "volume_size_mb": self.vol_size.value(),
            "safe_extraction": self.safe.isChecked(),
            "max_extraction_files": self.max_files.value(),
            "log_level": self.log_level.currentText(),
        })
        s.save()
        self.status.setText("Settings saved.")

    def _reset(self) -> None:
        if QMessageBox.question(self, "Reset settings", "Restore all settings to their defaults?") \
                == QMessageBox.StandardButton.Yes:
            self.settings.reset()
            # rebuild the form with the default values
            QWidget().setLayout(self.layout())
            self._build()
            self.status.setText("Defaults restored.")
