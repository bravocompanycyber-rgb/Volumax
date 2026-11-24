"""Qt binding selector.

The code base is written against PySide6 (Qt 6): the *Modern* build for Windows 10 1809+
and Windows 11. Qt 6 does not run on Windows 8/8.1, so the *Legacy* build uses
PySide2 (Qt 5.15, Python 3.8). This module makes ``import PySide6...`` resolve to PySide2
when PySide6 is not installed, and patches the few API differences, so the UI code is
shared unchanged.
"""

from __future__ import annotations

import importlib.util
import sys

BINDING = "PySide6"


def install() -> str:
    """Return the active binding name ('PySide6' or 'PySide2'), aliasing if needed."""
    global BINDING
    if importlib.util.find_spec("PySide6") is not None:
        BINDING = "PySide6"
        return BINDING
    if importlib.util.find_spec("PySide2") is None:
        raise ImportError("Neither PySide6 nor PySide2 is installed")

    import PySide2
    from PySide2 import QtCore, QtGui, QtNetwork, QtWidgets  # noqa: F401

    # Qt5 keeps these in QtWidgets; Qt6 moved them to QtGui.
    for name in ("QAction", "QShortcut", "QActionGroup"):
        if not hasattr(QtGui, name) and hasattr(QtWidgets, name):
            setattr(QtGui, name, getattr(QtWidgets, name))

    # Qt6 spells it exec(); PySide2 5.15 has exec_() (and sometimes exec()).
    for cls in (QtWidgets.QApplication, QtWidgets.QDialog, QtCore.QCoreApplication):
        if not hasattr(cls, "exec") and hasattr(cls, "exec_"):
            try:
                setattr(cls, "exec", cls.exec_)
            except TypeError:
                pass

    sys.modules["PySide6"] = PySide2
    for sub in ("QtCore", "QtGui", "QtWidgets", "QtNetwork"):
        sys.modules[f"PySide6.{sub}"] = getattr(PySide2, sub)
    BINDING = "PySide2"
    return BINDING
