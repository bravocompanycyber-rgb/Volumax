"""VOLUMAX — Professional Windows Archive Management Application."""

__version__ = "1.3.0"
__author__ = "Bravo Projects"
__app_name__ = "VOLUMAX"


# Resolve the Qt binding (PySide6 on Win10/11, PySide2 on the Win7/8/8.1 Legacy build).
try:
    from . import qtcompat as _qtcompat

    QT_BINDING = _qtcompat.install()
except ImportError:  # headless/CLI use without Qt
    QT_BINDING = "none"
