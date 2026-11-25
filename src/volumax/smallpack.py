"""Small-file packs: Zstandard with a *trained dictionary*.

Generic compressors struggle with many tiny, similar files (logs, JSON/config, source
snippets): each file is too short to learn from.  Zstandard can first *learn* the shared
vocabulary from samples and then compress every file against that dictionary.  Files are
compressed independently, so any single file can be read back without unpacking the rest.

Container ``.vxsp`` (VOLUMAX small-file pack)::

    b"VXSP1\\n" | u32 header_len | header JSON | dictionary | frame0 | frame1 ...

The feature needs the optional ``zstandard`` package; everything degrades cleanly without it.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence

MAGIC = b"VXSP1\n"
EXT = ".vxsp"
MAX_SAMPLE = 128 * 1024          # bigger files gain nothing from a dictionary
DICT_BYTES = 112 * 1024          # 64-128 KB is the useful range
MIN_SAMPLES_FOR_DICT = 8
MAX_UNPACK_FILES = 5_000_000
MIN_GAIN_KEEP = 0.80            # dictionary must save >= 20% or it is not used


def available() -> bool:
    try:
        import zstandard  # noqa: F401
        return True
    except Exception:
        return False


class SmallPackError(Exception):
    pass


@dataclass
class PackResult:
    success: bool
    message: str = ""
    archive: Path | None = None
    files: int = 0
    original_bytes: int = 0
    packed_bytes: int = 0
    used_dictionary: bool = False
    skipped: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.packed_bytes / self.original_bytes if self.original_bytes else 1.0


def _zstd():
    try:
        import zstandard

        return zstandard
    except Exception as exc:
        raise SmallPackError(
            "The 'zstandard' package is not installed. Install it with:  pip install zstandard"
        ) from exc


def _collect(sources: Sequence[Path]) -> list[tuple[Path, str]]:
    """(real path, archive name) for every regular file; symlinks are never followed."""
    out: list[tuple[Path, str]] = []
    for src in sources:
        src = Path(src)
        if src.is_symlink():
            continue
        if src.is_file():
            out.append((src, src.name))
        elif src.is_dir():
            base = src.parent
            for root, dirs, files in os.walk(src, followlinks=False):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
                for name in files:
                    p = Path(root) / name
                    if p.is_symlink() or not p.is_file():
                        continue
                    out.append((p, PurePosixPath(*p.relative_to(base).parts).as_posix()))
    return out


def _safe_name(name: str) -> str:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or PurePosixPath(name).is_absolute() or ".." in parts or ":" in parts[0]:
        raise SmallPackError(f"Unsafe path in pack: {name!r}")
    return "/".join(parts)


def train_dictionary(samples: Sequence[bytes], size: int = DICT_BYTES) -> bytes | None:
    """Train a dictionary; None when there is too little data to learn from."""
    z = _zstd()
    samples = [s for s in samples if 0 < len(s) <= MAX_SAMPLE]
    if len(samples) < MIN_SAMPLES_FOR_DICT:
        return None
    total = sum(len(s) for s in samples)
    size = max(4096, min(size, total // 4))  # a dictionary bigger than the data is pointless
    try:
        return z.train_dictionary(size, samples).as_bytes()
    except Exception:
        return None  # zstd refuses degenerate sample sets; fall back to plain compression


def create_pack(
    sources: Sequence[Path],
    archive: Path,
    *,
    level: int = 19,
    use_dictionary: bool = True,
    progress: Callable[[int, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> PackResult:
    try:
        z = _zstd()
    except SmallPackError as exc:
        return PackResult(False, str(exc))
    archive = Path(archive)
    items = _collect(sources)
    if not items:
        return PackResult(False, "Nothing to pack.")
    skipped: list[str] = []
    data: list[tuple[str, bytes]] = []
    for path, name in items:
        if cancel and cancel():
            return PackResult(False, "Cancelled")
        try:
            data.append((_safe_name(name), path.read_bytes()))
        except (OSError, SmallPackError) as exc:
            skipped.append(f"{name}: {exc}")
    if not data:
        return PackResult(False, "No readable files.", skipped=skipped)

    lvl = max(1, min(22, level))
    cctx = z.ZstdCompressor(level=lvl, write_checksum=True)
    frames = []
    for i, (name, blob) in enumerate(data):
        if cancel and cancel():
            return PackResult(False, "Cancelled")
        frames.append(cctx.compress(blob))
        if progress:
            progress(int(50 * (i + 1) / len(data)), name)
    dict_bytes = None
    if use_dictionary and sum(len(b) for _, b in data) <= 200 * 1024 * 1024:
        cand = train_dictionary([b for _, b in data])
        if cand:
            dctx_c = z.ZstdCompressor(level=lvl, dict_data=z.ZstdCompressionDict(cand), write_checksum=True)
            dframes = []
            for i, (name, blob) in enumerate(data):
                if cancel and cancel():
                    return PackResult(False, "Cancelled")
                dframes.append(dctx_c.compress(blob))
                if progress:
                    progress(50 + int(50 * (i + 1) / len(data)), name)
            # Promote the dictionary ONLY if it pays for itself (incl. its own size) by >= 20%.
            if sum(map(len, dframes)) + len(cand) <= MIN_GAIN_KEEP * sum(map(len, frames)):
                frames, dict_bytes = dframes, cand
    index, offset, orig = [], 0, 0
    for (name, blob), frame in zip(data, frames):
        index.append({"path": name, "size": len(blob), "offset": offset, "clen": len(frame),
                      "sha256": hashlib.sha256(blob).hexdigest()})
        offset += len(frame)
        orig += len(blob)

    header = json.dumps({"v": 1, "dict": len(dict_bytes or b""), "files": index},
                        ensure_ascii=False).encode("utf-8")
    tmp = archive.with_name(archive.name + ".part")
    try:
        archive.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(MAGIC + struct.pack("<I", len(header)) + header + (dict_bytes or b""))
            for fr in frames:
                f.write(fr)
        os.replace(tmp, archive)  # atomic: no half-written pack is ever visible
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        return PackResult(False, f"Could not write the pack: {exc}")
    size = archive.stat().st_size
    return PackResult(True, f"Packed {len(data)} files ({'dictionary' if dict_bytes else 'no dictionary'})",
                      archive, len(data), orig, size, bool(dict_bytes), skipped)


def _read_header(f) -> tuple[dict, bytes, int]:
    if f.read(len(MAGIC)) != MAGIC:
        raise SmallPackError("Not a VOLUMAX small-file pack.")
    (hlen,) = struct.unpack("<I", f.read(4))
    if hlen > 512 * 1024 * 1024:
        raise SmallPackError("Pack header is implausibly large (damaged file?).")
    try:
        header = json.loads(f.read(hlen).decode("utf-8"))
    except ValueError as exc:
        raise SmallPackError("Pack header is damaged.") from exc
    d = f.read(int(header.get("dict", 0)))
    if len(d) != int(header.get("dict", 0)):
        raise SmallPackError("Pack is truncated.")
    return header, d, f.tell()


def list_pack(archive: Path) -> list[dict]:
    with open(archive, "rb") as f:
        header, _, _ = _read_header(f)
    return list(header["files"])


def extract_pack(
    archive: Path,
    dest: Path,
    *,
    progress: Callable[[int, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> PackResult:
    try:
        z = _zstd()
    except SmallPackError as exc:
        return PackResult(False, str(exc))
    dest = Path(dest)
    try:
        with open(archive, "rb") as f:
            header, d, base = _read_header(f)
            files = header["files"]
            if len(files) > MAX_UNPACK_FILES:
                return PackResult(False, "Too many files in pack.")
            dctx = z.ZstdDecompressor(dict_data=z.ZstdCompressionDict(d) if d else None)
            dest_root = dest.resolve()
            dest.mkdir(parents=True, exist_ok=True)
            total, bad = 0, []
            for i, ent in enumerate(files):
                if cancel and cancel():
                    return PackResult(False, "Cancelled")
                name = _safe_name(ent["path"])
                target = (dest_root / name).resolve()
                if dest_root != target and dest_root not in target.parents:
                    raise SmallPackError(f"Unsafe path in pack: {name!r}")
                f.seek(base + int(ent["offset"]))
                frame = f.read(int(ent["clen"]))
                try:
                    blob = dctx.decompress(frame, max_output_size=int(ent["size"]) or 1)
                except Exception:
                    bad.append(name)
                    continue
                if hashlib.sha256(blob).hexdigest() != ent.get("sha256", hashlib.sha256(blob).hexdigest()):
                    bad.append(name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
                total += len(blob)
                if progress:
                    progress(int(100 * (i + 1) / len(files)), name)
    except SmallPackError as exc:
        return PackResult(False, str(exc))
    except OSError as exc:
        return PackResult(False, f"Could not read/write: {exc}")
    if bad:
        return PackResult(False, f"{len(bad)} file(s) failed verification: {', '.join(bad[:3])}",
                          files=len(files) - len(bad), original_bytes=total)
    return PackResult(True, f"Extracted {len(files)} files", archive, len(files), total)


def benchmark(sources: Sequence[Path], level: int = 19) -> dict:
    """Measure dictionary vs. plain Zstandard on the same files (for honest reporting)."""
    z = _zstd()
    blobs = [p.read_bytes() for p, _ in _collect(sources)]
    plain = z.ZstdCompressor(level=level)
    plain_total = sum(len(plain.compress(b)) for b in blobs)
    d = train_dictionary(blobs)
    if d is None:
        return {"files": len(blobs), "plain": plain_total, "dict": plain_total, "gain": 0.0}
    c = z.ZstdCompressor(level=level, dict_data=z.ZstdCompressionDict(d))
    with_dict = sum(len(c.compress(b)) for b in blobs) + len(d)
    return {"files": len(blobs), "original": sum(map(len, blobs)), "plain": plain_total,
            "dict": with_dict, "gain": 1 - with_dict / plain_total if plain_total else 0.0}
