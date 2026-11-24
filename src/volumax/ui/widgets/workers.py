"""Tiny helper to run blocking work off the GUI thread."""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger("volumax.ui.workers")

# Strong references: a task (and its Signals QObject) must outlive its worker
# thread AND the queued delivery of its result. Callers routinely overwrite
# ``self._task`` when a new request starts, which used to delete the signal
# object while the old thread was still about to emit on it.
_ACTIVE: set["_Task"] = set()


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
            result = self.fn()
        except Exception as exc:
            logger.exception("Background task failed")
            self._emit(self.signals.failed, str(exc))
            return
        self._emit(self.signals.done, result)

    @staticmethod
    def _emit(signal, value) -> None:
        try:
            signal.emit(value)
        except RuntimeError:  # QObject already torn down (app closing)
            logger.debug("Result dropped: receiver gone")


def run_in_background(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[str], None] | None = None,
) -> _Task:
    """Run ``fn`` on the global thread pool; callbacks fire on the GUI thread."""
    task = _Task(fn)
    task.setAutoDelete(False)
    _ACTIVE.add(task)
    task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    # Connected last, so (queued, in order) it runs after the caller's slots.
    release = lambda *_: _ACTIVE.discard(task)  # noqa: E731
    task.signals.done.connect(release)
    task.signals.failed.connect(release)
    QThreadPool.globalInstance().start(task)
    return task
