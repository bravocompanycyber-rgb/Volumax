"""Job queue panel."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..jobs import Job, JobQueue, JobState

logger = logging.getLogger("volumax.ui.queue")


class QueuePanel(QWidget):
    def __init__(self, queue: JobQueue, parent=None) -> None:
        super().__init__(parent)
        self.queue = queue
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.queue.add_listener(lambda j: self.refresh())

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Job Queue")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Name", "State", "Progress", "Message"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_refresh.setObjectName("secondary")
        btn_refresh.clicked.connect(self.refresh)
        btn_cancel = QPushButton("Cancel Selected")
        btn_cancel.setObjectName("danger")
        btn_cancel.clicked.connect(self._cancel)
        row.addWidget(btn_refresh)
        row.addWidget(btn_cancel)
        row.addStretch()
        layout.addLayout(row)

    def refresh(self) -> None:
        jobs = self.queue.list_jobs()
        self.table.setRowCount(0)
        for job in sorted(jobs, key=lambda j: j.created_at, reverse=True):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(job.id))
            self.table.setItem(row, 1, QTableWidgetItem(job.name))
            self.table.setItem(row, 2, QTableWidgetItem(job.state.name))
            self.table.setItem(row, 3, QTableWidgetItem(f"{job.progress}%"))
            self.table.setItem(row, 4, QTableWidgetItem(job.message or job.error or ""))

    def _cancel(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        for idx in rows:
            job_id = self.table.item(idx.row(), 0).text()
            self.queue.cancel(job_id)
        self.refresh()
