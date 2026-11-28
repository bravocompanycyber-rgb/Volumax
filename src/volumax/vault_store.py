"""Local state for vaults: attempt counters, tamper-evident audit log, first-run contract.

Everything here lives in one folder on THIS computer and is encrypted with a random
machine key kept next to it.  No server, no network.

What this protects, honestly:
  * It stops people from guessing through the VOLUMAX app, and it makes every copy of a
    vault *that is opened on this computer* obey the same counter (it is keyed by the
    vault's random UUID, so restoring an old copy does not reset it).
  * It does NOT stop an attacker who copied the vault file and runs their own guesser:
    that attacker is limited only by Argon2id and the strength of your secret.
  * Someone with full access to this user account could delete this folder and so reset
    the counters; the audit log would then simply be missing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import vault as vlt

CONTRACT_TEXT = (
    "Volumax cannot recover a file you lose, forget, or break. There is no reset, no backdoor, "
    "no support ticket that fixes it. That is not a bug — it is the proof that no one else can "
    "get in. If you lose the key, the data is gone. Do not cry about it. It was your choice."
)
CONTRACT_FINE_PRINT = (
    "Be clear about what this does and does not do:\n"
    "• The attempt limit and self-destruction stop people using the Volumax app. Someone who "
    "copies the file can guess offline; only a strong passphrase or key document stops that.\n"
    "• A copy made before a wipe keeps its own key slots. Wiping one copy cannot reach copies "
    "that were taken elsewhere.\n"
    "• Overwriting on SSDs and journaling file systems may leave old blocks behind.\n"
    "• Keys are wiped from memory on a best-effort basis (the app is written in Python).\n"
    "• This custom container has not had an independent security audit."
)


@dataclass
class Outcome:
    session: Optional[vlt.Session]
    status: str            # ok | wrong | destroyed | damaged | notvault
    message: str
    remaining: Optional[int] = None


class VaultStore:
    def __init__(self, folder: Path) -> None:
        self.dir = Path(folder)
        self._lock = threading.RLock()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._key = self._load_key()

    # ------------------------------------------------------------ machine key
    def _load_key(self) -> bytes:
        kf = self.dir / "store.key"
        try:
            k = kf.read_bytes()
            if len(k) == 32:
                return k
        except OSError:
            pass
        k = os.urandom(32)
        tmp = kf.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(k)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, kf)
        return k

    def _seal(self, obj, aad: bytes) -> bytes:
        return vlt._aead_enc(self._key, json.dumps(obj, separators=(",", ":")).encode(), aad)

    def _unseal(self, blob: bytes, aad: bytes):
        return json.loads(vlt._aead_dec(self._key, blob, aad).decode())

    def _atomic(self, name: str, data: bytes) -> None:
        p = self.dir / name
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            vlt._fsync(f)
        os.replace(tmp, p)

    # --------------------------------------------------------------- database
    def _db(self) -> dict:
        try:
            raw = (self.dir / "attempts.db").read_bytes()
            return self._unseal(raw, b"VLMX-DB1")
        except FileNotFoundError:
            return {"v": {}, "audit": {"n": 0, "head": ""}, "contract": None}
        except Exception:
            # unreadable / tampered: keep a copy for the owner and start fresh, loudly
            try:
                os.replace(self.dir / "attempts.db", self.dir / f"attempts.db.damaged-{int(time.time())}")
            except OSError:
                pass
            return {"v": {}, "audit": {"n": 0, "head": ""}, "contract": None, "reset": True}

    def _save_db(self, db: dict) -> None:
        self._atomic("attempts.db", self._seal(db, b"VLMX-DB1"))

    def counter(self, uuid_hex: str) -> dict:
        with self._lock:
            return dict(self._db()["v"].get(uuid_hex, {"failed": 0, "burned": False}))

    # ------------------------------------------------------------ first-run contract
    def contract_accepted(self) -> bool:
        with self._lock:
            return bool(self._db().get("contract"))

    def accept_contract(self) -> None:
        with self._lock:
            db = self._db()
            if db.get("contract"):
                return
            db["contract"] = int(time.time())
            self._save_db(db)
            self._audit_locked(db, "contract-accepted", "")

    # -------------------------------------------------------------- audit log
    def _audit_locked(self, db: dict, event: str, vault_id: str, detail: str = "") -> None:
        rec = {"t": int(time.time()), "e": event, "id": vault_id[:8], "d": detail,
               "prev": db["audit"]["head"]}
        line = base64.b64encode(self._seal(rec, b"VLMX-AUDIT1"))
        head = hashlib.sha256(line).hexdigest()
        with open(self.dir / "audit.log", "ab") as f:
            f.write(line + b"\n")
            vlt._fsync(f)
        db["audit"] = {"n": db["audit"]["n"] + 1, "head": head}
        self._save_db(db)

    def audit(self, event: str, vault_id: str = "", detail: str = "") -> None:
        with self._lock:
            self._audit_locked(self._db(), event, vault_id, detail)

    def read_audit(self) -> tuple[bool, list[dict], str]:
        """(intact, records, message).  Detects edits, reordering, deletion in the middle and
        truncation of the tail (the expected length and last hash are kept in the encrypted DB)."""
        with self._lock:
            db = self._db()
            try:
                lines = (self.dir / "audit.log").read_bytes().split(b"\n")
            except FileNotFoundError:
                lines = []
            lines = [ln for ln in lines if ln]
            recs, prev = [], ""
            for i, ln in enumerate(lines):
                try:
                    rec = self._unseal(base64.b64decode(ln), b"VLMX-AUDIT1")
                except Exception:
                    return False, recs, f"Entry {i + 1} is damaged or was edited."
                if rec.get("prev") != prev:
                    return False, recs, f"The chain is broken at entry {i + 1} (an entry was removed or reordered)."
                prev = hashlib.sha256(ln).hexdigest()
                recs.append(rec)
            a = db["audit"]
            if db.get("reset") and not recs:
                return False, recs, "The local security database was unreadable and has been reset."
            if len(recs) != a["n"] or (recs and prev != a["head"]):
                return False, recs, "The log is shorter or different than expected (entries were removed)."
            return True, recs, "Log is intact."

    # ---------------------------------------------------------- guarded opening
    def guarded_open(self, path, secret: vlt.Secret) -> Outcome:
        """Open a vault under the attempt policy.  The only way the UI should unlock a vault."""
        try:
            header = vlt.read_header(path)
        except vlt.NotAVault as exc:
            return Outcome(None, "notvault", str(exc))
        except vlt.VaultError as exc:
            return Outcome(None, "damaged", str(exc))
        uid = header.uuid_hex
        with self._lock:
            db = self._db()
            rec = db["v"].setdefault(uid, {"failed": 0, "burned": False})
            if rec.get("burned") and header.erase_enabled:
                self._destroy(path, header)
                self._audit_locked(db, "destroyed-on-open", uid)
                return Outcome(None, "destroyed",
                               "This vault was destroyed after too many failed attempts. "
                               "Its key has been erased and cannot be recovered.")
            try:
                sess = vlt.unlock(path, secret)
            except vlt.WrongSecret:
                rec["failed"] = rec.get("failed", 0) + 1
                left = None
                if header.erase_enabled and header.max_attempts:
                    left = max(0, header.max_attempts - rec["failed"])
                    if left == 0:
                        rec["burned"] = True
                        self._destroy(path, header)
                        self._audit_locked(db, "fail+destroyed", uid)
                        return Outcome(None, "destroyed",
                                       "Too many failed attempts. The vault's key has been erased; "
                                       "this vault can never be opened again.")
                self._save_db(db)
                self._audit_locked(db, "fail", uid)
                msg = "That did not open the vault."
                if left is not None:
                    msg += f"  {left} attempt{'s' if left != 1 else ''} left before it is destroyed."
                return Outcome(None, "wrong", msg, left)
            except vlt.VaultDamaged as exc:
                return Outcome(None, "damaged", str(exc))
            # success
            rec["failed"] = 0
            if sess.duress_wipe:
                rec["burned"] = True
                vlt.erase_keys(path)          # keep the file so the decoy can still be read
            self._save_db(db)
            self._audit_locked(db, "ok", uid)       # duress is deliberately logged as an ordinary success
            return Outcome(sess, "ok", "Unlocked.")

    @staticmethod
    def _destroy(path, header: vlt.Header) -> None:
        if header.auto_delete:
            vlt.destroy_file(path)
        else:
            vlt.erase_keys(path)


_default: Optional[VaultStore] = None


def default_store() -> VaultStore:
    global _default
    if _default is None:
        from .config import USER_DIR
        _default = VaultStore(USER_DIR / "vault")
    return _default
