"""Vault UI: create options, the unlock/browse page and the first-launch contract panel."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import vault as vlt
from ..backends.base import BackendResult
from ..compat import safe_is_file
from ..jobs import get_job_queue
from ..vault_store import CONTRACT_FINE_PRINT, CONTRACT_TEXT, default_store
from .widgets.workers import run_in_background

logger = logging.getLogger("volumax.ui.vault")
DIM = "color: #a9b6cb;"
LIMITS_NOTE = (
    "Honest limits: the attempt limit protects against people using Volumax. Someone who copies the "
    "file can guess offline, limited only by Argon2id and how strong your secret is. Copies made "
    "before a wipe keep their own key. There is no recovery of any kind."
)
VAULT_FORMAT = "Volumax Vault (.volumax)"


def _uses_text(method: str) -> bool:
    return method in ("pin", "passphrase", "passphrase+keydoc", "pin+keydoc")


def _uses_doc(method: str) -> bool:
    return method.endswith("keydoc")


def _pick_doc(parent, edit: QLineEdit) -> None:
    path, _ = QFileDialog.getOpenFileName(parent, "Choose the key document", "", "All files (*)")
    if path:
        edit.setText(path)


class _SecretFields(QWidget):
    """Method selector + secret inputs.  ``blank=True`` leaves the selector empty (unlock)."""

    def __init__(self, blank: bool, confirm: bool, parent=None) -> None:
        super().__init__(parent)
        self.confirm = confirm
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.method = QComboBox()
        if blank:
            self.method.addItem("— choose how this unlocks —", "")
        for key in vlt.METHODS:
            self.method.addItem(vlt.METHOD_LABELS[key], key)
        self.method.currentIndexChanged.connect(self._refresh)
        lay.addWidget(self.method)
        self.text = QLineEdit()
        self.text.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(self.text)
        self.text2 = QLineEdit()
        self.text2.setEchoMode(QLineEdit.EchoMode.Password)
        self.text2.setPlaceholderText("Repeat to confirm")
        lay.addWidget(self.text2)
        self.text2.setVisible(confirm)
        doc_row = QHBoxLayout()
        self.doc = QLineEdit()
        self.doc.setPlaceholderText("Key document (any file; only its fingerprint is used)")
        self.btn_doc = QPushButton("Browse")
        self.btn_doc.setObjectName("secondary")
        self.btn_doc.clicked.connect(lambda: _pick_doc(self, self.doc))
        doc_row.addWidget(self.doc, 1)
        doc_row.addWidget(self.btn_doc)
        self.doc_box = QWidget()
        self.doc_box.setLayout(doc_row)
        doc_row.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.doc_box)
        self._refresh()

    def key(self) -> str:
        return self.method.currentData() or ""

    def _refresh(self) -> None:
        m = self.key()
        self.text.setVisible(_uses_text(m))
        self.text2.setVisible(self.confirm and _uses_text(m))
        self.doc_box.setVisible(_uses_doc(m))
        self.text.setPlaceholderText("PIN (digits)" if m.startswith("pin") else "Passphrase")

    def secret(self) -> vlt.Secret:
        m = self.key()
        if not m:
            raise vlt.VaultError("Choose how this vault is unlocked.")
        doc = Path(self.doc.text().strip()) if _uses_doc(m) and self.doc.text().strip() else None
        sec = vlt.Secret(m, self.text.text() if _uses_text(m) else "", doc)
        if self.confirm and _uses_text(m) and self.text.text() != self.text2.text():
            raise vlt.VaultError("The two entries do not match. A typo here would lock you out for good.")
        return sec

    def clear(self) -> None:
        self.text.clear()
        self.text2.clear()


class VaultOptionsPanel(QGroupBox):
    """Shown in the Create page only while the Volumax Vault format is selected."""

    def __init__(self, parent=None) -> None:
        super().__init__("Volumax Vault — owner-or-nothing", parent)
        lay = QVBoxLayout(self)
        intro = QLabel("Opens only for you, only in Volumax. To anyone else it is random noise. "
                       "There is no recovery: if you lose the secret, the data is gone.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.main = _SecretFields(blank=False, confirm=True)
        self.main.method.setCurrentIndex(vlt.METHODS.index("passphrase"))
        lay.addWidget(QLabel("How it unlocks:"))
        lay.addWidget(self.main)

        self.limit_check = QCheckBox("Self-destruct: erase this vault's key after repeated failed attempts")
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 99)
        self.limit_spin.setValue(5)
        self.limit_spin.setPrefix("after ")
        self.limit_spin.setSuffix(" failed attempts")
        self.limit_spin.setEnabled(False)
        self.limit_check.toggled.connect(self.limit_spin.setEnabled)
        self.delete_check = QCheckBox("…and delete the file as well")
        self.delete_check.setEnabled(False)
        self.limit_check.toggled.connect(self.delete_check.setEnabled)
        lay.addWidget(self.limit_check)
        row = QHBoxLayout()
        row.addWidget(self.limit_spin)
        row.addWidget(self.delete_check)
        row.addStretch()
        lay.addLayout(row)

        self.duress_check = QCheckBox("Add a duress secret (opens a harmless decoy instead)")
        lay.addWidget(self.duress_check)
        self.duress_box = QWidget()
        dl = QVBoxLayout(self.duress_box)
        dl.setContentsMargins(16, 0, 0, 0)
        self.duress = _SecretFields(blank=False, confirm=True)
        self.duress.method.setCurrentIndex(vlt.METHODS.index("pin"))
        dl.addWidget(self.duress)
        self.duress_action = QComboBox()
        self.duress_action.addItem("Show the decoy only", "decoy")
        self.duress_action.addItem("Show the decoy AND silently erase the real key", "wipe")
        dl.addWidget(self.duress_action)
        decoy_row = QHBoxLayout()
        self.decoy_edit = QLineEdit()
        self.decoy_edit.setPlaceholderText("Decoy folder (optional — otherwise a harmless note)")
        btn = QPushButton("Browse")
        btn.setObjectName("secondary")
        btn.clicked.connect(self._pick_decoy)
        decoy_row.addWidget(self.decoy_edit, 1)
        decoy_row.addWidget(btn)
        dl.addLayout(decoy_row)
        self.duress_box.setVisible(False)
        self.duress_check.toggled.connect(self.duress_box.setVisible)
        lay.addWidget(self.duress_box)

        note = QLabel(LIMITS_NOTE)
        note.setWordWrap(True)
        note.setStyleSheet(DIM)
        lay.addWidget(note)

    def _pick_decoy(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Decoy folder")
        if d:
            self.decoy_edit.setText(d)

    def build_options(self) -> vlt.CreateOptions:
        """Validate and return the options; raises ``VaultError`` with a readable message."""
        opts = vlt.CreateOptions(secret=self.main.secret())
        opts.secret.validate(creating=True)
        if self.limit_check.isChecked():
            opts.max_attempts = self.limit_spin.value()
            opts.auto_delete = self.delete_check.isChecked()
        if self.duress_check.isChecked():
            opts.duress = self.duress.secret()
            opts.duress_action = self.duress_action.currentData()
            d = self.decoy_edit.text().strip()
            if d:
                opts.decoy_sources = [Path(d)]
        return opts

    def clear_secrets(self) -> None:
        self.main.clear()
        self.duress.clear()


class ContractPanel(QFrame):
    """In-window (not a pop-up) first-launch contract.  Accepting is logged once, permanently."""

    accepted = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("contract")
        self.setStyleSheet(
            "QFrame#contract { background-color: #1b2538; border: 2px solid #f5c04d; border-radius: 10px; }"
            "QFrame#contract QLabel, QFrame#contract QCheckBox { background: transparent; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        head = QLabel("Owner-or-Nothing")
        head.setStyleSheet("font-size: 18px; font-weight: 700; color: #f5c04d;")
        lay.addWidget(head)
        tag = QLabel("Opens only for you. Anyone else gets noise — and every copy that touches this "
                     "computer's counter dies with the key.")
        tag.setWordWrap(True)
        lay.addWidget(tag)
        body = QLabel(CONTRACT_TEXT)
        body.setWordWrap(True)
        body.setStyleSheet("font-weight: 600;")
        lay.addWidget(body)
        fine = QLabel(CONTRACT_FINE_PRINT)
        fine.setWordWrap(True)
        fine.setStyleSheet(DIM)
        lay.addWidget(fine)
        row = QHBoxLayout()
        self.check = QCheckBox("I understand.")
        self.btn = QPushButton("Continue")
        self.btn.setObjectName("gold")
        self.btn.setEnabled(False)
        self.check.toggled.connect(self.btn.setEnabled)
        self.btn.clicked.connect(self._accept)
        row.addWidget(self.check)
        row.addStretch()
        row.addWidget(self.btn)
        lay.addLayout(row)

    def _accept(self) -> None:
        try:
            default_store().accept_contract()
        except Exception:
            logger.exception("could not record contract acceptance")
        self.hide()
        self.accepted.emit()


class VaultPage(QWidget):
    """Open a .volumax vault: pick the method (blank by default), unlock, browse, extract."""

    def __init__(self, parent=None, store=None) -> None:
        super().__init__(parent)
        self._store = store
        self._session = None
        self._path: Path | None = None
        self._busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        title = QLabel("Vault")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        lay.addWidget(title)
        sub = QLabel("Open a .volumax vault. It is recognised by its contents, not its file name. "
                     "Volumax never tells you — or anyone — which unlock method a vault uses.")
        sub.setWordWrap(True)
        sub.setStyleSheet(DIM)
        lay.addWidget(sub)

        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Vault file…")
        b = QPushButton("Browse")
        b.setObjectName("secondary")
        b.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(b)
        lay.addLayout(row)

        self.fields = _SecretFields(blank=True, confirm=False)
        lay.addWidget(self.fields)
        self.btn_unlock = QPushButton("Unlock")
        self.btn_unlock.setObjectName("gold")
        self.btn_unlock.clicked.connect(self.unlock)
        self.fields.text.returnPressed.connect(self.unlock)
        lay.addWidget(self.btn_unlock)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Size"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(180)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)

        acts = QHBoxLayout()
        self.btn_all = QPushButton("Extract all…")
        self.btn_sel = QPushButton("Extract selected…")
        self.btn_prev = QPushButton("Preview selected")
        self.btn_lock = QPushButton("Lock")
        self.btn_log = QPushButton("Security log")
        for w in (self.btn_all, self.btn_sel, self.btn_prev, self.btn_lock, self.btn_log):
            w.setObjectName("secondary")
            acts.addWidget(w)
        self.btn_all.clicked.connect(lambda: self._extract(False))
        self.btn_sel.clicked.connect(lambda: self._extract(True))
        self.btn_prev.clicked.connect(self._preview)
        self.btn_lock.clicked.connect(self.lock)
        self.btn_log.clicked.connect(self._show_log)
        lay.addLayout(acts)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumHeight(140)
        lay.addWidget(self.out)
        self._set_open(False)

    # ---------------------------------------------------------------- helpers
    @property
    def store(self):
        return self._store or default_store()

    def _set_open(self, is_open: bool) -> None:
        for w in (self.table, self.btn_all, self.btn_sel, self.btn_prev, self.btn_lock):
            w.setEnabled(is_open)

    def _say(self, text: str, bad: bool = False) -> None:
        self.status.setText(("✖ " if bad else "✔ ") + text if text else "")
        self.status.setStyleSheet("color: #ff8a8f; font-weight: 600;" if bad else "color: #6fdc8c; font-weight: 600;")

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open vault", "", "All files (*)")
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> None:
        """Called for a file chosen or dropped; any file whose signature matches is accepted."""
        self.lock()
        self.path_edit.setText(str(path))
        self._path = Path(path)
        if not vlt.sniff(self._path):
            self._say("This is not a Volumax vault.", True)

    # ----------------------------------------------------------------- unlock
    def unlock(self) -> None:
        if self._busy:
            return
        p = Path(self.path_edit.text().strip())
        if not safe_is_file(p):
            self._say("Choose a vault file first.", True)
            return
        try:
            secret = self.fields.secret()
            secret.validate(creating=False)
        except vlt.VaultError as exc:
            self._say(str(exc), True)       # nothing was tried, so nothing is counted
            return
        self._busy = True
        self.btn_unlock.setEnabled(False)
        self._say("Checking… (this takes a moment on purpose)")
        self.status.setStyleSheet(DIM)
        self.lock()
        store = self.store
        harden = vlt.harden_process

        def work():
            harden()
            return store.guarded_open(p, secret)

        def done(out) -> None:
            self._busy = False
            self.btn_unlock.setEnabled(True)
            self.fields.clear()
            if out.status != "ok":
                self._say(out.message, True)
                return
            self._path = p
            self._session = out.session
            self._say(f"Unlocked — {len(out.session.entries)} item(s).")
            self._fill(out.session.entries)
            self._set_open(True)

        def failed(msg: str) -> None:
            self._busy = False
            self.btn_unlock.setEnabled(True)
            self._say(f"Could not open the vault: {msg}", True)

        run_in_background(work, done, failed)

    def _fill(self, entries) -> None:
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            name = QTableWidgetItem(e["p"] + ("/" if e.get("d") else ""))
            name.setData(Qt.ItemDataRole.UserRole, e["p"])
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem("" if e.get("d") else f"{e['s']:,} bytes"))

    def lock(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        self.table.setRowCount(0)
        self.out.clear()
        self._set_open(False)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)       # leaving the page keeps it unlocked only until you leave
        self.lock()

    # -------------------------------------------------------------- operations
    def _selected(self) -> list[str]:
        rows = {i.row() for i in self.table.selectedItems()}
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in sorted(rows)]

    def _extract(self, only_selected: bool) -> None:
        sess = self._session
        if sess is None:
            return
        sel = self._selected() if only_selected else None
        job_sess = sess.clone()
        if only_selected and not sel:
            self._say("Select something first.", True)
            return
        dest = QFileDialog.getExistingDirectory(self, "Decrypt into folder")
        if not dest:
            return
        name = self._path.name if self._path else "vault"

        def job(progress=None, cancel=None, pause=None):
            try:
                n = job_sess.extract(Path(dest), sel, progress=progress, cancel=cancel)
            except vlt.Cancelled:
                return BackendResult(False, "Cancelled.")
            except vlt.VaultError as exc:
                return BackendResult(False, str(exc))
            except OSError as exc:
                return BackendResult(False, f"Could not write the files: {exc}")
            finally:
                job_sess.close()
            return BackendResult(True, f"{n} file(s) decrypted to {dest}")

        j = get_job_queue().submit(f"Decrypt {name}", job)
        self._say(f"Queued as job {j.id} — progress is in the Job Queue.")

    def _preview(self) -> None:
        sess = self._session
        sel = self._selected()
        if sess is None or not sel:
            self._say("Select a file to preview.", True)
            return

        view = sess.clone()

        def work():
          try:
            data = view.read_member(sel[0], max_bytes=256 * 1024)
            if b"\x00" in data[:4096]:
                return f"Binary file, {len(data):,} bytes (not shown)."
            for enc in ("utf-8", "utf-16", "cp1252"):
                try:
                    return data.decode(enc)
                except UnicodeError:
                    continue
            return "Not displayable as text."
          finally:
            view.close()

        run_in_background(work, self.out.setPlainText, lambda m: self._say(m, True))

    def _show_log(self) -> None:
        ok, recs, msg = self.store.read_audit()
        lines = [("✔ " if ok else "✖ TAMPERING SUSPECTED — ") + msg, ""]
        names = {"ok": "unlocked", "fail": "failed attempt", "fail+destroyed": "failed — key erased",
                 "destroyed-on-open": "key erased on open", "contract-accepted": "contract accepted"}
        for r in recs[-100:]:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["t"]))
            lines.append(f"{when}   {names.get(r['e'], r['e']):<22} {r.get('id', '')}")
        self.out.setPlainText("\n".join(lines))
