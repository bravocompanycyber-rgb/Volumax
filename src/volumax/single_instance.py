"""One running VOLUMAX per user. Later launches forward their command to it.

Explorer starts one process per selected file, so "Add to .7z" on ten files would
otherwise create ten archives. The first instance collects 'add' requests for a short
window and merges them into one.
"""

from __future__ import annotations

import getpass
import json
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .cli import ADD, ADD_TO, Command

logger = logging.getLogger("volumax.single")

COLLECT_MS = 700  # how long to wait for the rest of a multi-select


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"VOLUMAX-single-{user}"


def send_to_running(cmd: Command, name: Optional[str] = None, timeout_ms: int = 300) -> bool:
    """Forward ``cmd`` to an already-running instance. True if someone received it."""
    sock = QLocalSocket()
    sock.connectToServer(name or server_name())
    if not sock.waitForConnected(timeout_ms):
        return False
    payload = json.dumps({"kind": cmd.kind, "fmt": cmd.fmt, "paths": [str(p) for p in cmd.paths]})
    sock.write(payload.encode("utf-8"))
    ok = sock.waitForBytesWritten(2000)
    sock.disconnectFromServer()
    return bool(ok)


class InstanceServer(QObject):
    """Listens for forwarded commands; merges bursts of 'add' requests."""

    def __init__(self, handler: Callable[[Command], None], name: Optional[str] = None) -> None:
        super().__init__()
        self._handler = handler
        self._name = name or server_name()
        self._server = QLocalServer(self)
        self._buffers: Dict[object, bytearray] = {}
        self._pending: Dict[Tuple[str, str], List[Path]] = {}
        self._timers: Dict[Tuple[str, str], QTimer] = {}
        self._server.newConnection.connect(self._on_connection)

    def listen(self) -> bool:
        QLocalServer.removeServer(self._name)  # stale pipe/socket from a crash
        ok = self._server.listen(self._name)
        if not ok:
            logger.warning("Single-instance server not started: %s", self._server.errorString())
        return ok

    def close(self) -> None:
        self._server.close()

    # ------------------------------------------------------------------ internals
    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._buffers[s].extend(bytes(s.readAll())))
            sock.disconnected.connect(lambda s=sock: self._finish(s))

    def _finish(self, sock) -> None:
        data = bytes(self._buffers.pop(sock, b"")) + bytes(sock.readAll())
        sock.deleteLater()
        try:
            msg = json.loads(data.decode("utf-8"))
            cmd = Command(msg["kind"], [Path(p) for p in msg.get("paths", [])], msg.get("fmt", "7z"))
        except Exception:
            logger.warning("Ignoring malformed instance message")
            return
        self.dispatch(cmd)

    def dispatch(self, cmd: Command) -> None:
        if cmd.kind not in (ADD, ADD_TO):
            self._handler(cmd)
            return
        key = (cmd.kind, cmd.fmt)
        self._pending.setdefault(key, []).extend(cmd.paths)
        timer = self._timers.get(key)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda k=key: self._flush(k))
            self._timers[key] = timer
        timer.start(COLLECT_MS)  # restart: wait until the burst ends

    def _flush(self, key) -> None:
        paths = self._pending.pop(key, [])
        if paths:
            seen, uniq = set(), []
            for p in paths:
                if str(p) not in seen:
                    seen.add(str(p))
                    uniq.append(p)
            self._handler(Command(key[0], uniq, key[1]))
