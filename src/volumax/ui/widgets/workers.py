"""Tiny helper to run blocking work off the GUI thread."""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger("volumax.ui.workers")


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:  # runs on a pool thread
        try:
            self.signals.done.emit(self.fn())
        except Exception as exc:
            logger.exception("Background task failed")
            self.signals.failed.emit(str(exc))


def run_in_background(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[str], None] | None = None,
) -> _Task:
    """Run ``fn`` on the global thread pool; callbacks fire on the GUI thread."""
    task = _Task(fn)
    task.setAutoDelete(False)  # keep signals object alive until delivered
    task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    QThreadPool.globalInstance().start(task)
    return task
