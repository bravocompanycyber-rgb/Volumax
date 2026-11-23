"""Settings page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..settings import Settings


class SettingsDialog(QWidget):
    def __init__(self, settings: Settings, embedded: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        group = QGroupBox("Defaults")
        form = QFormLayout(group)

        self.level = QSpinBox()
        self.level.setRange(0, 9)
        self.level.setValue(self.settings.compression_level)
        form.addRow("Compression level:", self.level)

        self.zip_max = QSpinBox()
        self.zip_max.setRange(1, 102400)
        self.zip_max.setValue(self.settings.independent_zip_max_mb)
        form.addRow("Independent ZIP max (MB):", self.zip_max)

        self.vol_size = QSpinBox()
        self.vol_size.setRange(1, 10000)
        self.vol_size.setValue(self.settings.volume_size_mb)
        form.addRow("Default volume size (MB):", self.vol_size)

        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level.setCurrentText(self.settings.get("log_level", "INFO"))
        form.addRow("Log level:", self.log_level)

        layout.addWidget(group)

        btn = QPushButton("Save Settings")
        btn.setObjectName("gold")
        btn.clicked.connect(self._save)
        layout.addWidget(btn)
        layout.addStretch()

    def _save(self) -> None:
        self.settings.set("compression_level", self.level.value())
        self.settings.set("independent_zip_max_mb", self.zip_max.value())
        self.settings.set("volume_size_mb", self.vol_size.value())
        self.settings.set("log_level", self.log_level.currentText())
        self.settings.save()
