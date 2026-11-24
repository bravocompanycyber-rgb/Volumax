"""Virtual (lazy) table model for archive contents — paints only visible rows."""

from __future__ import annotations

import posixpath
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QApplication, QStyle

from ..backends.base import ArchiveEntry
from ..listing import ArchiveTree

COLUMNS = ("Name", "Size", "Packed", "Modified", "Type")
UP_ROW = ArchiveEntry(path="..", is_dir=True)


def human_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _type_of(e: ArchiveEntry) -> str:
    if e.is_dir:
        return "Folder"
    ext = posixpath.splitext(e.path)[1].lstrip(".").upper()
    return f"{ext} file" if ext else "File"


class ArchiveModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tree: ArchiveTree | None = None
        self.cwd = ""
        self._query = ""
        self._rows: list[ArchiveEntry] = []
        self._sort_col = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        style = QApplication.style()
        self._dir_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self._up_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogToParent)

    # ----- data ----------------------------------------------------------
    def set_tree(self, tree: ArchiveTree | None) -> None:
        self.tree = tree
        self.cwd = ""
        self._query = ""
        self._rebuild()

    def set_cwd(self, path: str) -> None:
        self.cwd = path.strip("/")
        self._query = ""
        self._rebuild()

    def set_query(self, text: str) -> None:
        self._query = text.strip().lower()
        self._rebuild()

    @property
    def searching(self) -> bool:
        return bool(self._query)

    def _sort_key(self):
        col = self._sort_col
        if col == 1:
            return lambda e: e.size
        if col == 2:
            return lambda e: e.compressed_size
        if col == 3:
            return lambda e: e.timestamp or ""
        if col == 4:
            return lambda e: (_type_of(e), e.path.casefold())
        return lambda e: e.path.rpartition("/")[2].casefold() if not self._query else e.path.casefold()

    def _rebuild(self) -> None:
        self.beginResetModel()
        rows: list[ArchiveEntry] = []
        if self.tree is not None:
            reverse = self._sort_order == Qt.SortOrder.DescendingOrder
            if self._query:
                q = self._query
                rows = [e for e in self.tree.entries if q in e.path.lower()]
                rows.sort(key=self._sort_key(), reverse=reverse)
            else:
                items = self.tree.children.get(self.cwd, [])
                dirs = [e for e in items if e.is_dir]
                files = [e for e in items if not e.is_dir]
                key = self._sort_key()
                dirs.sort(key=key, reverse=reverse)
                files.sort(key=key, reverse=reverse)
                rows = dirs + files  # folders always first, like WinRAR/Explorer
                if self.cwd:
                    rows.insert(0, UP_ROW)
        self._rows = rows
        self.endResetModel()

    # ----- Qt API --------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if e is UP_ROW:
                return ".." if col == 0 else ""
            if col == 0:
                return e.path if self._query else e.path.rpartition("/")[2]
            if col == 1:
                return "" if e.is_dir else human_size(e.size)
            if col == 2:
                return "" if e.is_dir or not e.compressed_size else human_size(e.compressed_size)
            if col == 3:
                return e.timestamp or ""
            return _type_of(e)
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            if e is UP_ROW:
                return self._up_icon
            return self._dir_icon if e.is_dir else self._file_icon
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (1, 2):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return e.path
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        self._sort_col = column
        self._sort_order = order
        self._rebuild()

    def entry_at(self, row: int) -> ArchiveEntry | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None
