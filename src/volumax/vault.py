"""The ``.volumax`` vault: an encrypted container only VOLUMAX opens.

Qt-free and policy-free.  This module is the *format* (create / unlock / list / extract /
erase).  Failed-attempt counting, auto-destruction policy and the audit log live in
``vault_store`` and wrap these functions.

Crypto: libsodium through PyNaCl.  Nothing here invents a cipher.
  * KDF .......... Argon2id (``crypto_pwhash``), parameters stored in the header
  * Slots ........ XChaCha20-Poly1305-IETF wraps a random 256-bit data key (DEK)
  * Payload ...... XChaCha20-Poly1305 *secretstream* (chunked, ordered, truncation-proof)
  * Header ....... authenticated as AAD of every slot, so edits make unlocking fail

Layout (all integers little-endian)::

    MAGIC(8) VERSION(2) UUID(16) OPS(4) MEM_KIB(4) SALT(16) MAX_ATTEMPTS(2) FLAGS(2)   <- AAD
    LEN_A(8) LEN_B(8)
    SLOT0(80) SLOT1(80)        # nonce(24) + AEAD(kind(1) DEK(32) pad(7)) + tag(16)
    SECTION_A  SECTION_B       # manifest message + secretstream of an LZMA-compressed tar

Slot 0 and slot 1 look identical (random).  The slot that opens depends on the secret
typed: the real one opens section A, the optional duress secret opens decoy section B.
Section B always exists, so a decoy cannot be detected by size alone.

What is stored about the unlock method: nothing.  The method id is mixed into the KDF
input, so choosing the wrong method simply derives the wrong key.

Honest limits (also in docs/VAULT.md): an attacker holding a *copy* is bounded only by
Argon2id and the strength of your secret; the attempt counter protects against the
VOLUMAX app, not against offline guessing.  The design is unaudited.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import lzma
import os
import struct
import sys
import tarfile
import time
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

AVAILABLE_ERROR: Optional[str] = None

try:  # PyNaCl is a hard requirement of the vault feature only
    import nacl.bindings as _nb
    import nacl.exceptions as _nex
    import nacl.pwhash.argon2id as _argon
    import nacl.utils as _nutils

    AVAILABLE = hasattr(
        _nb, "crypto_secretstream_xchacha20poly1305_init_push"
    )

    if not AVAILABLE:
        AVAILABLE_ERROR = (
            "PyNaCl imported, but the required secretstream API is missing"
        )

except Exception as exc:  # pragma: no cover - reported by diagnostics
    AVAILABLE = False
    AVAILABLE_ERROR = f"{type(exc).__name__}: {exc}"

MAGIC = b"\x89VLMX\r\n\x1a"
VERSION = 1
SUFFIX = ".volumax"
CHUNK = 1024 * 1024
SLOT_SIZE = 80
_HEAD_AAD = struct.Struct("<8sH16sII16sHH")      # magic ver uuid ops mem_kib salt max_attempts flags
_HEAD_LEN = struct.Struct("<QQ")
HEADER_SIZE = _HEAD_AAD.size + _HEAD_LEN.size + 2 * SLOT_SIZE

FLAG_AUTO_DELETE = 1      # delete the whole file after erasing it
FLAG_ERASE_ENABLED = 2    # attempt counter may erase the key slots

KIND_REAL, KIND_DECOY, KIND_WIPE = 1, 2, 3

METHODS = ("pin", "passphrase", "keydoc", "passphrase+keydoc", "pin+keydoc")
METHOD_LABELS = {
    "pin": "PIN",
    "passphrase": "Passphrase",
    "keydoc": "Key document",
    "passphrase+keydoc": "Passphrase + key document",
    "pin+keydoc": "PIN + key document",
}

# Argon2id cost.  Stored in the header so it can be raised later without a format change.
OPS_DEFAULT = 3
MEM_DEFAULT_KIB = (128 if sys.maxsize <= 2 ** 32 else 256) * 1024
MIN_OPS, MIN_MEM_KIB = 1, 8 * 1024          # floor enforced when READING (rejects absurd files)
MAX_MEM_KIB = 2 * 1024 * 1024               # refuse to allocate more than 2 GiB for a header's claim


class VaultError(Exception):
    """Base class.  ``str(e)`` is safe to show to the user."""


class NotAVault(VaultError):
    pass


class WrongSecret(VaultError):
    """Wrong secret, wrong method, wrong key document, or erased header: deliberately one error."""


class VaultDamaged(VaultError):
    pass


class Cancelled(VaultError):
    pass


# ------------------------------------------------------------------ memory hygiene

def zero(buf) -> None:
    """Best-effort wipe of a bytearray/memoryview in place (CPython; immutable bytes cannot be wiped)."""
    try:
        if isinstance(buf, (bytearray, memoryview)) and len(buf):
            arr = (ctypes.c_char * len(buf)).from_buffer(buf)
            ctypes.memset(ctypes.addressof(arr), 0, len(buf))
            del arr
    except Exception:
        try:
            for i in range(len(buf)):
                buf[i] = 0
        except Exception:
            pass


def harden_process() -> list[str]:
    """Disable core dumps / crash dumps for this process.  Returns what was applied."""
    done = []
    try:
        if os.name == "nt":
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX: no WER dialog / dump on fault
            k32.SetErrorMode(0x0001 | 0x0002)
            done.append("windows-error-mode")
        else:
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            done.append("rlimit-core")
            if sys.platform.startswith("linux"):
                libc = ctypes.CDLL(None)
                if libc.prctl(4, 0, 0, 0, 0) == 0:   # PR_SET_DUMPABLE=4
                    done.append("prctl-nodump")
    except Exception:
        pass
    return done


# ------------------------------------------------------------------------- secrets

@dataclass
class Secret:
    """What the user types / supplies.  ``keydoc`` is a path; only its SHA-256 is ever used."""
    method: str
    text: str = ""
    keydoc: Optional[Path] = None

    def validate(self, *, creating: bool) -> None:
        if self.method not in METHODS:
            raise VaultError("Choose how this vault is unlocked.")
        needs_text = self.method in ("pin", "passphrase", "passphrase+keydoc", "pin+keydoc")
        needs_doc = self.method.endswith("keydoc") or self.method == "keydoc"
        if needs_text and not self.text:
            raise VaultError("Enter the " + ("PIN" if self.method.startswith("pin") else "passphrase") + ".")
        if needs_doc and self.keydoc is None:
            raise VaultError("Choose the key document.")
        if creating and needs_text:
            if self.method.startswith("pin"):
                if not self.text.isdigit() or len(self.text) < 6:
                    raise VaultError("A PIN must be at least 6 digits (digits only).  Short PINs can be "
                                     "guessed offline in minutes; use a passphrase or a key document for real protection.")
            elif len(self.text) < 10:
                raise VaultError("Use a passphrase of at least 10 characters.")

    def material(self) -> bytes:
        """Bytes fed to Argon2id: method id, secret text and key-document digest, length-prefixed."""
        parts = [b"VLMX-KDF1", self.method.encode()]
        text = self.text.encode("utf-8")
        parts.append(struct.pack("<I", len(text)) + text)
        if self.method.endswith("keydoc") or self.method == "keydoc":
            parts.append(b"D" + keydoc_digest(self.keydoc))
        else:
            parts.append(b"N")
        return b"\x00".join(parts)


def keydoc_digest(path) -> bytes:
    """SHA-256 of the file, byte-exact.  One changed byte gives a different key."""
    if path is None:
        raise VaultError("Choose the key document.")
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(CHUNK), b""):
                h.update(block)
    except OSError as exc:
        raise VaultError(f"Cannot read the key document: {exc}")
    return h.digest()


# ------------------------------------------------------------------------- header

@dataclass
class Header:
    uuid: bytes
    ops: int
    mem_kib: int
    salt: bytes
    max_attempts: int
    flags: int
    len_a: int
    len_b: int
    slots: tuple
    aad: bytes

    @property
    def uuid_hex(self) -> str:
        return self.uuid.hex()

    @property
    def erase_enabled(self) -> bool:
        return bool(self.flags & FLAG_ERASE_ENABLED)

    @property
    def auto_delete(self) -> bool:
        return bool(self.flags & FLAG_AUTO_DELETE)


def sniff(path) -> bool:
    """True when the file starts with the VOLUMAX signature (extension is irrelevant)."""
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except (OSError, ValueError):
        return False


def read_header(path) -> Header:
    try:
        with open(path, "rb") as f:
            raw = f.read(HEADER_SIZE)
    except (OSError, ValueError) as exc:
        raise NotAVault(f"Cannot read the file: {exc}")
    if len(raw) < HEADER_SIZE or raw[:len(MAGIC)] != MAGIC:
        raise NotAVault("This is not a VOLUMAX vault.")
    magic, ver, uid, ops, mem, salt, maxa, flags = _HEAD_AAD.unpack_from(raw, 0)
    if ver != VERSION:
        raise NotAVault(f"This vault uses format version {ver}; this VOLUMAX understands version {VERSION}.")
    if not (MIN_OPS <= ops <= 64) or not (MIN_MEM_KIB <= mem <= MAX_MEM_KIB):
        raise VaultDamaged("The vault header is damaged (implausible key-derivation settings).")
    la, lb = _HEAD_LEN.unpack_from(raw, _HEAD_AAD.size)
    off = _HEAD_AAD.size + _HEAD_LEN.size
    slots = (raw[off:off + SLOT_SIZE], raw[off + SLOT_SIZE:off + 2 * SLOT_SIZE])
    return Header(uid, ops, mem, salt, maxa, flags, la, lb, slots, raw[:_HEAD_AAD.size + _HEAD_LEN.size])


# ------------------------------------------------------------------------- crypto

def _kdf(secret: Secret, salt: bytes, ops: int, mem_kib: int) -> bytearray:
    mat = bytearray(secret.material())
    try:
        key = _argon.kdf(32, bytes(mat), salt, opslimit=ops, memlimit=mem_kib * 1024)
    finally:
        zero(mat)
    return bytearray(key)


def _aead_enc(key: bytes, plain: bytes, aad: bytes) -> bytes:
    nonce = _nutils.random(24)
    return nonce + _nb.crypto_aead_xchacha20poly1305_ietf_encrypt(plain, aad, nonce, key)


def _aead_dec(key: bytes, blob: bytes, aad: bytes) -> bytes:
    return _nb.crypto_aead_xchacha20poly1305_ietf_decrypt(blob[24:], aad, blob[:24], key)


def _make_slot(kek: Optional[bytes], kind: int, dek: bytes, aad: bytes) -> bytes:
    if kek is None:
        return _nutils.random(SLOT_SIZE)
    blob = _aead_enc(bytes(kek), bytes([kind]) + bytes(dek) + b"\x00" * 7, aad)
    assert len(blob) == SLOT_SIZE
    return blob


def _open_slots(kek: bytes, header: Header):
    for slot in header.slots:
        try:
            plain = _aead_dec(kek, slot, header.aad)
        except Exception:
            continue
        kind, dek = plain[0], bytearray(plain[1:33])
        if kind in (KIND_REAL, KIND_DECOY, KIND_WIPE):
            return kind, dek
    return None


# -------------------------------------------------------------------- tar streaming

class _Sink(io.RawIOBase):
    """File-like target for ``tarfile`` that LZMA-compresses and encrypts as data arrives."""

    def __init__(self, out, dek: bytes, total_hint: int, cancel, progress) -> None:
        self.out = out
        self.comp = lzma.LZMACompressor(format=lzma.FORMAT_XZ, preset=6)
        self.state = _nb.crypto_secretstream_xchacha20poly1305_state()
        hdr = _nb.crypto_secretstream_xchacha20poly1305_init_push(self.state, bytes(dek))
        out.write(hdr)
        self.buf = bytearray()
        self.written = len(hdr)
        self.seen = 0
        self.total = max(1, total_hint)
        self.cancel = cancel
        self.progress = progress

    def writable(self) -> bool:
        return True

    def _emit(self, data: bytes, tag: int) -> None:
        ct = _nb.crypto_secretstream_xchacha20poly1305_push(self.state, data, None, tag)
        self.out.write(struct.pack("<I", len(ct)))
        self.out.write(ct)
        self.written += 4 + len(ct)

    def write(self, b) -> int:  # type: ignore[override]
        if self.cancel and self.cancel():
            raise Cancelled("Cancelled.")
        n = len(b)
        self.seen += n
        self.buf += self.comp.compress(bytes(b))
        while len(self.buf) >= CHUNK:
            self._emit(bytes(self.buf[:CHUNK]), _nb.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE)
            del self.buf[:CHUNK]
        if self.progress:
            self.progress(min(99, int(100 * self.seen / self.total)), "Encrypting")
        return n

    def finish(self) -> int:
        self.buf += self.comp.flush()
        while len(self.buf) > CHUNK:
            self._emit(bytes(self.buf[:CHUNK]), _nb.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE)
            del self.buf[:CHUNK]
        self._emit(bytes(self.buf), _nb.crypto_secretstream_xchacha20poly1305_TAG_FINAL)
        zero(self.buf)
        return self.written


class _Source(io.RawIOBase):
    """File-like decrypt+decompress reader for ``tarfile`` (stream mode)."""

    def __init__(self, f, dek: bytes, length: int, cancel=None, progress=None) -> None:
        self.f = f
        self.left = length
        self.cancel = cancel
        self.progress = progress
        self.length = max(1, length)
        hdr = f.read(24)
        if len(hdr) != 24:
            raise VaultDamaged("The vault is truncated.")
        self.left -= 24
        self.state = _nb.crypto_secretstream_xchacha20poly1305_state()
        _nb.crypto_secretstream_xchacha20poly1305_init_pull(self.state, hdr, bytes(dek))
        self.dec = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        self.pending = bytearray()
        self.final = False

    def readable(self) -> bool:
        return True

    def _pull(self) -> bool:
        if self.final:
            return False
        if self.cancel and self.cancel():
            raise Cancelled("Cancelled.")
        raw = self.f.read(4)
        if len(raw) != 4 or self.left < 4:
            raise VaultDamaged("The vault is truncated or damaged.")
        (n,) = struct.unpack("<I", raw)
        if n > CHUNK + 64 or n > self.left - 4:
            raise VaultDamaged("The vault is damaged (bad frame).")
        ct = self.f.read(n)
        self.left -= 4 + n
        if len(ct) != n:
            raise VaultDamaged("The vault is truncated.")
        try:
            msg, tag = _nb.crypto_secretstream_xchacha20poly1305_pull(self.state, ct, None)
        except Exception:
            raise VaultDamaged("The vault is damaged: an authentication check failed "
                               "(the file was changed or corrupted).")
        if tag == _nb.crypto_secretstream_xchacha20poly1305_TAG_FINAL:
            self.final = True
        try:
            self.pending += self.dec.decompress(msg) if not self.dec.eof else b""
        except lzma.LZMAError:
            raise VaultDamaged("The vault is damaged (decompression failed).")
        if self.progress:
            self.progress(min(99, int(100 * (self.length - self.left) / self.length)), "Decrypting")
        return True

    def read(self, size: int = -1) -> bytes:  # type: ignore[override]
        if size is None or size < 0:
            while self._pull():
                pass
            size = len(self.pending)
        while len(self.pending) < size and self._pull():
            pass
        out = bytes(self.pending[:size])
        del self.pending[:size]
        return out


# ---------------------------------------------------------------------- sources

@dataclass
class _Item:
    arc: str
    path: Optional[Path]
    is_dir: bool
    size: int


def _collect(sources: Sequence[Path], skip: Optional[Path]) -> tuple[list[_Item], int]:
    items: list[_Item] = []
    seen: set[str] = set()

    def add(arc: str, p: Optional[Path], is_dir: bool, size: int) -> None:
        arc = arc.replace("\\", "/").strip("/")
        if arc and arc not in seen:
            seen.add(arc)
            items.append(_Item(arc, p, is_dir, size))

    for src in sources:
        src = Path(src)
        try:
            if src.is_symlink():
                continue
            if src.is_file():
                add(src.name, src, False, src.stat().st_size)
            elif src.is_dir():
                add(src.name, src, True, 0)
                for dp, dns, fns in os.walk(src):
                    dns[:] = [d for d in dns if not os.path.islink(os.path.join(dp, d))]
                    base = Path(dp)
                    for d in dns:
                        add(f"{src.name}/{(base / d).relative_to(src).as_posix()}", base / d, True, 0)
                    for fn in fns:
                        fp = base / fn
                        if fp.is_symlink() or (skip and fp == skip):
                            continue
                        add(f"{src.name}/{fp.relative_to(src).as_posix()}", fp, False, fp.stat().st_size)
        except OSError:
            continue
    return items, sum(i.size for i in items)


def _write_section(out, dek: bytes, items: list[_Item], aad: bytes, cancel, progress) -> int:
    """Manifest message + secretstream payload.  Returns bytes written."""
    start = out.tell()
    manifest = json.dumps(
        [{"p": i.arc, "s": i.size, "d": i.is_dir} for i in items], separators=(",", ":")
    ).encode("utf-8")
    mblob = _aead_enc(bytes(dek), manifest, aad + b"manifest")
    out.write(struct.pack("<I", len(mblob)))
    out.write(mblob)
    total = sum(i.size for i in items)
    sink = _Sink(out, dek, total, cancel, progress)
    tar = tarfile.open(fileobj=sink, mode="w|", format=tarfile.PAX_FORMAT)
    try:
        for it in items:
            ti = tarfile.TarInfo(it.arc)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.mtime = int(it.path.stat().st_mtime) if it.path else int(time.time())
            if it.is_dir:
                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(ti)
            else:
                ti.size, ti.mode = it.size, 0o644
                if it.path is None:
                    tar.addfile(ti, io.BytesIO(b"\x00" * it.size))
                else:
                    with open(it.path, "rb") as f:
                        tar.addfile(ti, f)
    finally:
        tar.close()
    sink.finish()
    return out.tell() - start


def _fsync(f) -> None:
    f.flush()
    try:
        os.fsync(f.fileno())
    except OSError:
        pass


# ---------------------------------------------------------------------- create

@dataclass
class CreateOptions:
    secret: Secret
    max_attempts: int = 0                 # 0 = never erase automatically
    auto_delete: bool = False
    duress: Optional[Secret] = None
    duress_action: str = "decoy"          # "decoy" | "wipe"
    decoy_sources: Sequence[Path] = field(default_factory=list)
    ops: int = OPS_DEFAULT
    mem_kib: int = MEM_DEFAULT_KIB


def create_vault(dest, sources: Sequence[Path], opts: CreateOptions, *,
                 progress: Optional[Callable[[int, str], None]] = None,
                 cancel: Optional[Callable[[], bool]] = None) -> bytes:
    """Write ``dest`` atomically.  Returns the vault UUID (16 bytes)."""
    if not AVAILABLE:
        raise VaultError("The vault needs the PyNaCl (libsodium) package, which is not available.")
    dest = Path(dest)
    opts.secret.validate(creating=True)
    if opts.duress is not None:
        opts.duress.validate(creating=True)
        if opts.duress.material() == opts.secret.material():
            raise VaultError("The duress secret must differ from the real one.")
    if opts.max_attempts and not (1 <= opts.max_attempts <= 99):
        raise VaultError("Attempts must be between 1 and 99.")
    sources = [Path(s) for s in sources]
    if not sources:
        raise VaultError("Add at least one file or folder.")
    items, total = _collect(sources, dest)
    if not items:
        raise VaultError("Nothing readable to store.")

    flags = 0
    if opts.max_attempts:
        flags |= FLAG_ERASE_ENABLED
    if opts.auto_delete:
        flags |= FLAG_AUTO_DELETE
    uid = _uuid.uuid4().bytes
    salt = _nutils.random(16)
    aad = _HEAD_AAD.pack(MAGIC, VERSION, uid, opts.ops, opts.mem_kib, salt, opts.max_attempts, flags)

    dek_a, dek_b = bytearray(_nutils.random(32)), bytearray(_nutils.random(32))
    kek_real = _kdf(opts.secret, salt, opts.ops, opts.mem_kib)
    kek_duress = _kdf(opts.duress, salt, opts.ops, opts.mem_kib) if opts.duress else None
    if opts.duress:
        d_items, _ = _collect([Path(s) for s in opts.decoy_sources], dest) if opts.decoy_sources else ([], 0)
        if not d_items:
            note = b"This vault holds nothing of interest.\n"
            d_items = [_Item("README.txt", None, False, len(note))]
    else:
        d_items = []

    part = dest.with_name(dest.name + ".part")
    try:
        with open(part, "wb") as out:
            out.write(aad)
            out.write(_HEAD_LEN.pack(0, 0))
            out.write(_nutils.random(2 * SLOT_SIZE))       # placeholder until lengths are known
            len_a = _write_section(out, dek_a, items, aad, cancel, progress)
            if opts.duress:
                if d_items[0].path is None:
                    len_b = _write_decoy_note(out, dek_b, aad)
                else:
                    len_b = _write_section(out, dek_b, d_items, aad, cancel, None)
            else:
                blob = _nutils.random(512 + (_nutils.random(1)[0] % 4) * 512)
                out.write(blob)
                len_b = len(blob)
            # Lengths are now known: authenticate header + lengths as the slots' AAD.
            lens = _HEAD_LEN.pack(len_a, len_b)
            full_aad = aad + lens
            slot_real = _make_slot(kek_real, KIND_REAL, dek_a, full_aad)
            if opts.duress:
                kind = KIND_WIPE if opts.duress_action == "wipe" else KIND_DECOY
                slot_duress = _make_slot(kek_duress, kind, dek_b, full_aad)
            else:
                slot_duress = _make_slot(None, 0, b"", full_aad)
            swap = _nutils.random(1)[0] & 1     # position of the real slot reveals nothing
            slots = (slot_duress, slot_real) if swap else (slot_real, slot_duress)
            out.seek(_HEAD_AAD.size)
            out.write(lens)
            out.write(slots[0])
            out.write(slots[1])
            _fsync(out)
        os.replace(part, dest)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    zero(kek_real)
    if kek_duress is not None:
        zero(kek_duress)
    zero(dek_a)
    zero(dek_b)
    if progress:
        progress(100, "Vault written")
    return uid


def _write_decoy_note(out, dek: bytes, aad: bytes) -> int:
    note = b"This vault holds nothing of interest.\n"
    item = _Item("README.txt", None, False, len(note))
    start = out.tell()
    mblob = _aead_enc(bytes(dek), json.dumps([{"p": "README.txt", "s": len(note), "d": False}],
                                             separators=(",", ":")).encode(), aad + b"manifest")
    out.write(struct.pack("<I", len(mblob)))
    out.write(mblob)
    sink = _Sink(out, dek, len(note), None, None)
    tar = tarfile.open(fileobj=sink, mode="w|", format=tarfile.PAX_FORMAT)
    ti = tarfile.TarInfo(item.arc)
    ti.size, ti.mode, ti.mtime = len(note), 0o644, int(time.time())
    tar.addfile(ti, io.BytesIO(note))
    tar.close()
    sink.finish()
    return out.tell() - start


# ----------------------------------------------------------------------- unlock

@dataclass
class Session:
    """An unlocked vault.  Call ``close()`` (or use ``with``) to wipe the key."""
    path: Path
    header: Header
    kind: int
    _dek: bytearray
    entries: list = field(default_factory=list)

    @property
    def is_decoy(self) -> bool:
        return self.kind in (KIND_DECOY, KIND_WIPE)

    @property
    def duress_wipe(self) -> bool:
        return self.kind == KIND_WIPE

    def close(self) -> None:
        zero(self._dek)

    def clone(self) -> "Session":
        """Independent copy with its own key bytes, so a background job survives the UI locking."""
        return Session(self.path, self.header, self.kind, bytearray(self._dek), list(self.entries))

    def __enter__(self):
        return self

    def __exit__(self, *a) -> None:
        self.close()

    # -- internals
    def _section(self):
        h = self.header
        a_off = HEADER_SIZE
        if self.kind == KIND_REAL:
            return a_off, h.len_a
        return a_off + h.len_a, h.len_b

    # -- operations
    def read_member(self, name: str, max_bytes: int = 64 * 1024 * 1024) -> bytes:
        """Return one file's bytes, decrypted in memory only (no temp file)."""
        want = name.replace("\\", "/").strip("/")
        with open(self.path, "rb") as f:
            src = _Source_open(self, f)
            with tarfile.open(fileobj=src, mode="r|") as tar:
                for m in tar:
                    if m.name == want and m.isreg():
                        if m.size > max_bytes:
                            raise VaultError("That file is too large to preview.")
                        data = tar.extractfile(m).read()
                        return data
        raise VaultError("That file is not in the vault.")

    def extract(self, dest, selected: Optional[Iterable[str]] = None, *,
                progress=None, cancel=None, max_total: int = 64 * 1024 ** 3,
                max_files: int = 1_000_000) -> int:
        """Decrypt files into ``dest``.  Returns the number of files written.

        Paths are validated (no absolute paths, no ``..``, no links, no devices).  The
        plaintext is streamed straight to its final location, never through a temp file.
        """
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        want = {s.replace("\\", "/").strip("/") for s in selected} if selected else None
        count = total = 0
        with open(self.path, "rb") as f:
            src = _Source_open(self, f, cancel, progress)
            with tarfile.open(fileobj=src, mode="r|") as tar:
                for m in tar:
                    name = m.name.replace("\\", "/")
                    if not (m.isreg() or m.isdir()):
                        continue
                    if want is not None and not any(name == w or name.startswith(w + "/") for w in want):
                        continue
                    target = _safe_target(root, name)
                    if m.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    count += 1
                    total += m.size
                    if count > max_files or total > max_total:
                        raise VaultError("Extraction stopped: the vault exceeds the safety limits.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target = _unique(target)
                    part = target.with_name(target.name + ".vxpart")
                    try:
                        with open(part, "wb") as out:
                            rd = tar.extractfile(m)
                            for block in iter(lambda: rd.read(CHUNK), b""):
                                out.write(block)
                        os.replace(part, target)
                    except BaseException:
                        try:
                            part.unlink()
                        except OSError:
                            pass
                        raise
        if progress:
            progress(100, "Done")
        return count


def _Source_open(sess: Session, f, cancel=None, progress=None) -> _Source:
    off, length = sess._section()
    f.seek(off)
    (mlen,) = struct.unpack("<I", f.read(4))
    f.seek(off + 4 + mlen)
    return _Source(f, bytes(sess._dek), length - 4 - mlen, cancel, progress)


def _safe_target(root: Path, name: str) -> Path:
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise VaultError(f"Unsafe path inside the vault was refused: {name!r}")
    if any(":" in p for p in parts) or "\x00" in name:
        raise VaultError(f"Unsafe path inside the vault was refused: {name!r}")
    target = root.joinpath(*parts)
    try:
        target.resolve().relative_to(root)
    except ValueError:
        raise VaultError(f"Unsafe path inside the vault was refused: {name!r}")
    return target


def _unique(p: Path) -> Path:
    if not p.exists():
        return p
    n = 1
    while True:
        cand = p.with_name(f"{p.stem} ({n}){p.suffix}")
        if not cand.exists():
            return cand
        n += 1


def unlock(path, secret: Secret) -> Session:
    """Derive the key and open a key slot.  Raises ``WrongSecret`` for *any* mismatch.

    This function does not count attempts; ``vault_store.guarded_open`` does.
    """
    if not AVAILABLE:
        raise VaultError("The vault needs the PyNaCl (libsodium) package, which is not available.")
    secret.validate(creating=False)
    header = read_header(path)
    kek = _kdf(secret, header.salt, header.ops, header.mem_kib)
    try:
        hit = _open_slots(bytes(kek), header)
    finally:
        zero(kek)
    if hit is None:
        raise WrongSecret("That did not open the vault.")
    kind, dek = hit
    sess = Session(Path(path), header, kind, dek)
    try:
        off, length = sess._section()
        with open(path, "rb") as f:
            f.seek(off)
            (mlen,) = struct.unpack("<I", f.read(4))
            blob = f.read(mlen)
        manifest = _aead_dec(bytes(dek), blob, header.aad[:_HEAD_AAD.size] + b"manifest")
        sess.entries = json.loads(manifest.decode("utf-8"))
    except Exception:
        sess.close()
        raise VaultDamaged("The vault opened but its contents are damaged.")
    return sess


# ---------------------------------------------------------------------- erasure

def erase_keys(path) -> bool:
    """Cryptographic erasure: overwrite both key slots with random bytes.

    Without the slots the data key is gone and the ciphertext is permanently noise.
    Limits: copies made earlier keep their own slots; SSD wear-levelling or journalling
    may retain old blocks of THIS file.
    """
    try:
        with open(path, "r+b") as f:
            f.seek(_HEAD_AAD.size + _HEAD_LEN.size)
            for _ in range(3):  # a few passes; cheap and helps on some media
                f.seek(_HEAD_AAD.size + _HEAD_LEN.size)
                f.write(_nutils.random(2 * SLOT_SIZE))
                _fsync(f)
        return True
    except OSError:
        return False


def destroy_file(path) -> bool:
    """Erase the key slots, then try to delete the file itself."""
    ok = erase_keys(path)
    try:
        os.remove(path)
        return True
    except OSError:
        return ok
