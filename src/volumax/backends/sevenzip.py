"""Official 7-Zip backend adapter."""

from __future__ import annotations

import io
import dataclasses
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Sequence

from ..compression import analyze_sources, plan_compression
from ..config import find_7zip_exe
from .base import (
    ArchiveBackend,
    ArchiveEntry,
    BackendCapabilities,
    BackendResult,
    CancelCheck,
    ProgressCallback,
)

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger("volumax.backends.sevenzip")

_PERCENT_RE = re.compile(r"^\s*(\d{1,3})%")
_SPLIT_RE = re.compile(r"[\x08\r\n]+")

# 7-Zip would otherwise sit waiting on a console prompt for encrypted archives.
# A throw-away password turns that into an immediate "wrong password" error.
_NO_PASSWORD = "-pVOLUMAX-NO-PASSWORD-GIVEN"

_PASSWORD_HINTS = (
    "wrong password",
    "enter password",
    "cannot open encrypted archive",
    "can not open encrypted archive",
)

# Compressed-tar names: 7-Zip only sees the single inner .tar for these, so they
# need a two-stage pipeline (decompress | tar) to see/extract the real files.
_TAR_CODECS = {
    ".tar.gz": "gzip", ".tgz": "gzip",
    ".tar.bz2": "bzip2", ".tbz2": "bzip2", ".tbz": "bzip2",
    ".tar.xz": "xz", ".txz": "xz",
}


def tar_codec(path: Path | str) -> str | None:
    name = str(path).lower()
    for suffix, codec in _TAR_CODECS.items():
        if name.endswith(suffix):
            return codec
    return None


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class SevenZipBackend(ArchiveBackend):
    def __init__(self, exe_path: Path | None = None) -> None:
        self.exe = Path(exe_path) if exe_path else find_7zip_exe()
        if self.exe is None or not self.exe.is_file():
            raise FileNotFoundError(
                "7-Zip engine not found. Place 7z.exe in engines/7zip/ "
                "or install 7-Zip system-wide."
            )
        logger.info("7-Zip backend: %s", self.exe)

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="7-Zip",
            formats_create=("zip", "7z", "tar", "tar.gz", "tar.bz2", "tar.xz", "gzip", "bzip2", "xz"),
            formats_extract=("zip", "7z", "tar", "gzip", "bzip2", "xz", "rar", "cab", "iso", "wim", "001"),
            supports_password=True,
            supports_encrypt_filenames=True,
            supports_volumes=True,
            supports_solid=True,
            supports_update=True,
        )

    # ------------------------------------------------------------------ process
    def _env(self) -> dict[str, str] | None:
        lib_dir = self.exe.parent
        if (lib_dir / "7z.so").exists() or (lib_dir / "7z.dll").exists():
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = str(lib_dir) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
            return env
        return None

    def _popen(self, args: Sequence[str], *, text: bool, stdin=subprocess.DEVNULL) -> subprocess.Popen:
        # Don't flash a console window on Windows
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        kwargs: dict = {}
        if text:
            kwargs.update(text=True, encoding="utf-8", errors="replace")
        return subprocess.Popen(
            [str(self.exe), *args],
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
            creationflags=flags,
            **kwargs,
        )

    @staticmethod
    def _set_suspended(procs: list[subprocess.Popen], suspended: bool) -> None:
        if psutil is None:
            return
        for p in procs:
            try:
                proc = psutil.Process(p.pid)
                proc.suspend() if suspended else proc.resume()
            except Exception:  # process may already be gone
                pass

    def _run(
        self,
        args: Sequence[str],
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
        pause: CancelCheck | None = None,
        timeout: int | None = None,
        pipe_to: Sequence[str] | None = None,
    ) -> BackendResult:
        """Run 7-Zip (optionally ``args | pipe_to``), draining pipes continuously."""
        logger.debug("CMD: %s %s", self.exe, " ".join(args))
        procs: list[subprocess.Popen] = []
        out_chunks: list[str] = []
        err_lines: list[str] = []
        threads: list[threading.Thread] = []

        try:
            if pipe_to:
                p1 = self._popen(args, text=False)
                procs.append(p1)
                p2 = self._popen(pipe_to, text=True, stdin=p1.stdout)
                procs.append(p2)
                assert p1.stdout is not None
                p1.stdout.close()  # p2 owns the read end now
            else:
                p2 = p1 = self._popen(args, text=True)
                procs.append(p1)
        except OSError as exc:
            for p in procs:
                p.kill()
            return BackendResult(False, f"Cannot start 7-Zip: {exc}")

        def pump(stream, sink: list[str], track: bool) -> None:
            """Drain ``stream``; parse 7-Zip's backspace-redrawn percentages if ``track``."""
            if not track:
                sink.append(stream.read())
                return
            last = -1
            buf = ""

            def handle(part: str) -> None:
                nonlocal last
                m = _PERCENT_RE.match(part)
                if m:
                    pct = min(100, int(m.group(1)))
                    if progress and pct != last:
                        last = pct
                        try:
                            progress(pct, part.strip()[:120])
                        except Exception:  # a UI callback must never kill the pump
                            logger.exception("progress callback failed")
                elif part.strip():
                    sink.append(part + "\n")

            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                parts = _SPLIT_RE.split(buf + chunk)
                buf = parts.pop()
                for part in parts:
                    handle(part)
            handle(buf)

        track_stdout = "-bsp1" in args and not pipe_to
        if pipe_to:
            assert p1.stderr is not None and p2.stdout is not None and p2.stderr is not None
            p1_err = io.TextIOWrapper(p1.stderr, encoding="utf-8", errors="replace")
            # In a pipeline the first stage's progress arrives on stderr (-bsp2)
            streams = [(p1_err, err_lines, "-bsp2" in args), (p2.stdout, out_chunks, False),
                       (p2.stderr, err_lines, False)]
        else:
            assert p1.stdout is not None and p1.stderr is not None
            streams = [(p1.stdout, out_chunks, track_stdout), (p1.stderr, err_lines, False)]
        for stream, sink, track in streams:
            t = threading.Thread(target=pump, args=(stream, sink, track), daemon=True)
            t.start()
            threads.append(t)

        deadline = time.monotonic() + timeout if timeout else None
        suspended = False
        result: BackendResult | None = None
        try:
            while any(p.poll() is None for p in procs):
                if cancel and cancel():
                    for p in procs:
                        p.terminate()
                    for p in procs:
                        try:
                            p.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            p.kill()
                    result = BackendResult(False, "Cancelled by user", -1)
                    break
                if deadline and time.monotonic() > deadline:
                    for p in procs:
                        p.kill()
                    result = BackendResult(False, f"7-Zip timed out after {timeout}s", -2)
                    break
                want_pause = bool(pause and pause())
                if want_pause != suspended:
                    self._set_suspended(procs, want_pause)
                    suspended = want_pause
                time.sleep(0.05) if suspended else self._wait_any(procs)
        finally:
            if suspended:
                self._set_suspended(procs, False)
            for t in threads:
                t.join(timeout=5)

        if result is not None:
            return result

        stdout = "".join(out_chunks)
        stderr = "".join(err_lines)
        code = next((p.returncode for p in procs if p.returncode), 0)
        success = code == 0
        msg = "OK" if success else (stderr or stdout or f"Exit {code}").strip()
        res = BackendResult(
            success=success, message=msg[:2000], returncode=code, stdout=stdout, stderr=stderr
        )
        if not success:
            low = (stderr + stdout).lower()
            res.extra["needs_password"] = any(h in low for h in _PASSWORD_HINTS)
        return res

    @staticmethod
    def _wait_any(procs: list[subprocess.Popen]) -> None:
        # Poll the first still-running process with a short timeout (cheap, responsive).
        for p in procs:
            if p.poll() is None:
                try:
                    p.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
                return

    @staticmethod
    def _auth(password: str | None) -> list[str]:
        return [f"-p{password}"] if password else [_NO_PASSWORD]

    # ------------------------------------------------------------------ listing
    def list_archive(
        self, archive: Path, password: str | None = None, detailed: bool = False
    ) -> BackendResult:
        """List contents. The compact format is ~10x less text to parse than -slt;
        use ``detailed=True`` only when CRC / encryption flags are required."""
        archive = Path(archive)
        fmt_args = ["-slt"] if detailed else []
        codec = tar_codec(archive)
        if codec:
            result = self._run(
                ["x", "-so", "-y", "-bd", *self._auth(password), str(archive)],
                pipe_to=["l", "-ba", "-ttar", "-si", "-sccUTF-8", *fmt_args],
            )
        else:
            result = self._run(
                ["l", "-ba", "-sccUTF-8", *fmt_args, *self._auth(password), str(archive)]
            )
        if result.success:
            result.entries = (
                self._parse_list(result.stdout) if detailed else self._parse_compact(result.stdout)
            )
        return result

    @staticmethod
    def _parse_compact(text: str) -> list[ArchiveEntry]:
        """Parse ``7z l -ba`` fixed-width rows:  date(0-18) attr(20-24) size(26-37) packed(39-50) name(53-)."""
        entries: list[ArchiveEntry] = []
        append = entries.append
        for line in text.splitlines():
            if len(line) < 54:
                continue
            name = line[53:].replace("\\", "/")
            if not name:
                continue
            attr = line[20:25]
            try:
                size = int(line[26:38]) if line[26:38].strip() else 0
                packed = int(line[39:51]) if line[39:51].strip() else 0
            except ValueError:
                continue
            is_dir = "D" in attr
            append(
                ArchiveEntry(
                    path=name,
                    size=size,
                    compressed_size=packed,
                    is_dir=is_dir,
                    timestamp=line[:19].strip() or None,
                )
            )
        return entries

    @staticmethod
    def _parse_list(text: str) -> list[ArchiveEntry]:
        entries: list[ArchiveEntry] = []
        current: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                if current.get("Path"):
                    entries.append(SevenZipBackend._to_entry(current))
                current = {}
                continue
            if " = " in line:
                k, _, v = line.partition(" = ")
                current[k.strip()] = v.strip()
        if current.get("Path"):
            entries.append(SevenZipBackend._to_entry(current))
        return entries

    @staticmethod
    def _to_entry(d: dict[str, str]) -> ArchiveEntry:
        path = d.get("Path", "").replace("\\", "/")
        attrs = d.get("Attributes", "")
        is_dir = "D" in attrs or path.endswith("/")
        return ArchiveEntry(
            path=path,
            size=int(d.get("Size") or 0),
            compressed_size=int(d.get("Packed Size") or 0),
            is_dir=is_dir,
            timestamp=d.get("Modified"),
            crc=d.get("CRC"),
            encrypted=d.get("Encrypted", "").upper() in ("+", "YES", "TRUE"),
        )

    # ------------------------------------------------------------------- create
    def create_archive(
        self,
        archive: Path,
        sources: Sequence[Path],
        *,
        format: str = "7z",
        level: int = 5,
        preset: str | None = None,
        password: str | None = None,
        encrypt_filenames: bool = False,
        solid: bool = True,
        volume_size: str | None = None,
        threads: int = 0,
        dictionary_mb: int | None = None,
        max_dictionary_mb: int = 512,
        smart: bool = True,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
        pause: CancelCheck | None = None,
    ) -> BackendResult:
        archive = Path(archive)
        archive.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()

        fmt = format.lower().lstrip(".")
        codec = {"tar.gz": "gzip", "tgz": "gzip", "tar.bz2": "bzip2", "tbz2": "bzip2",
                 "tar.xz": "xz", "txz": "xz"}.get(fmt)
        profile = analyze_sources(sources, cancel)
        plan = plan_compression(
            codec or fmt,
            preset=preset,
            level=level,
            profile=profile,
            solid=solid,
            threads=threads,
            max_dictionary_mb=max_dictionary_mb,
            dictionary_mb=dictionary_mb,
            smart=smart,
        )

        if codec:
            if password:
                return BackendResult(
                    False, "tar.gz / tar.bz2 / tar.xz cannot be password-protected. Use 7z or zip."
                )
            result = self._create_tar_compressed(
                archive, sources, codec, plan.args, progress, cancel, pause
            )
        else:
            args: list[str] = ["a", f"-t{fmt}", *plan.args, "-y", "-bsp1", "-sccUTF-8", "-snl"]
            if password:
                args.append(f"-p{password}")
                if encrypt_filenames and fmt == "7z":
                    args.append("-mhe=on")
                if fmt == "zip":
                    args.append("-mem=AES256")  # AES-256, not weak ZipCrypto
            if volume_size:
                args.append(f"-v{volume_size}")
            args.append(str(archive))
            args.extend(str(s) for s in sources)
            result = self._run(args, progress=progress, cancel=cancel, pause=pause)

        if result.success:
            result.output_path = archive
            try:
                if volume_size:
                    out = sum(p.stat().st_size for p in archive.parent.glob(archive.name + ".[0-9][0-9][0-9]"))
                else:
                    out = archive.stat().st_size
                secs = time.monotonic() - started
                ratio = (out / profile.total_bytes * 100) if profile.total_bytes else 100.0
                result.message = (
                    f"{archive.name}: {_human(profile.total_bytes)} → {_human(out)} "
                    f"({ratio:.1f}%) in {secs:.1f}s [{plan.description}]"
                )
                result.extra.update(
                    input_bytes=profile.total_bytes, output_bytes=out, plan=plan.description
                )
            except OSError:
                pass
        return result

    def _create_tar_compressed(
        self, archive, sources, codec, method_args, progress, cancel, pause
    ) -> BackendResult:
        """tar.gz / tar.bz2 / tar.xz: 7-Zip's gzip/bzip2/xz formats hold ONE stream, so
        build the .tar first (same volume as the output), then compress it."""

        def scaled(lo: int, hi: int):
            if not progress:
                return None
            return lambda pct, msg="": progress(lo + (hi - lo) * pct // 100, msg)

        tmp_dir = Path(tempfile.mkdtemp(prefix=".volumax_tmp_", dir=archive.parent))
        try:
            inner = archive.name
            for suffix in (".gz", ".bz2", ".xz", ".tgz", ".tbz2", ".tbz", ".txz"):
                if inner.lower().endswith(suffix):
                    inner = inner[: -len(suffix)]
                    inner += ".tar" if suffix in (".tgz", ".tbz2", ".tbz", ".txz") else ""
                    break
            if not inner.lower().endswith(".tar"):
                inner += ".tar"
            tar_path = tmp_dir / inner
            res = self._run(
                ["a", "-ttar", "-y", "-bsp1", "-sccUTF-8", "-snl", str(tar_path), *map(str, sources)],
                progress=scaled(0, 40), cancel=cancel, pause=pause,
            )
            if not res.success:
                return res
            if archive.exists():
                archive.unlink()
            return self._run(
                ["a", f"-t{codec}", *method_args, "-y", "-bsp1", "-sccUTF-8", str(archive), str(tar_path)],
                progress=scaled(40, 100), cancel=cancel, pause=pause,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------ extract
    @staticmethod
    def _tolerate_skipped_links(res: BackendResult) -> BackendResult:
        """7-Zip refuses archive symlinks that point outside the target (good!) but
        then exits 2 for the whole job. Skipping an unsafe link is the safe outcome,
        so when that is the ONLY complaint, report success with a note."""
        if res.success or res.returncode != 2:
            return res
        text = (res.stderr or "") + (res.stdout or "")
        errs = [ln for ln in text.splitlines() if ln.startswith(("ERROR", "WARNING"))]
        if errs and all("Dangerous link path was ignored" in ln for ln in errs):
            return dataclasses.replace(
                res, success=True, message=f"Extracted; {len(errs)} unsafe link(s) skipped"
            )
        return res

    def extract_archive(
        self,
        archive: Path,
        destination: Path,
        *,
        password: str | None = None,
        selected_files: Sequence[str] | None = None,
        overwrite: bool = True,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
        pause: CancelCheck | None = None,
    ) -> BackendResult:
        archive = Path(archive)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        mode = "-aoa" if overwrite else "-aos"
        listfile: Path | None = None
        names: list[str] = []
        if selected_files:
            # Names go through a UTF-8 list file with wildcard matching OFF, so file names
            # containing * ? [ ] or non-ASCII characters are matched literally, and
            # thousands of selected files don't overflow the command line.
            fd, tmp = tempfile.mkstemp(prefix="volumax_sel_", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(selected_files) + "\n")
            listfile = Path(tmp)
            names = ["-spd", "-scsUTF-8", f"@{listfile}"]
        try:
            if tar_codec(archive):
                return self._tolerate_skipped_links(self._run(
                    ["x", "-so", "-y", "-bd", "-bsp2", "-mmt=on", str(archive)],
                    pipe_to=["x", "-si", "-ttar", "-y", mode, f"-o{destination}", "-sccUTF-8", *names],
                    progress=progress, cancel=cancel, pause=pause,
                ))
            args = ["x", "-y", "-mmt=on", "-bsp1", "-sccUTF-8", mode, *self._auth(password),
                    f"-o{destination}", str(archive), *names]
            return self._tolerate_skipped_links(
                self._run(args, progress=progress, cancel=cancel, pause=pause)
            )
        finally:
            if listfile is not None:
                listfile.unlink(missing_ok=True)

    def test_archive(
        self,
        archive: Path,
        password: str | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
        pause: CancelCheck | None = None,
    ) -> BackendResult:
        args = ["t", "-mmt=on", "-bsp1", "-sccUTF-8", *self._auth(password), str(archive)]
        return self._run(args, progress=progress, cancel=cancel, pause=pause)
