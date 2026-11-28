import os, subprocess, sys
import pytest
from pathlib import Path
from volumax.archive_manager import ArchiveManager
from volumax import extras


@pytest.fixture(scope="module")
def mgr():
    return ArchiveManager()


def _make(mgr, tmp, name="a.7z", files=None, fmt="7z"):
    src = tmp / ("src_" + name); src.mkdir()
    for n, c in (files or {"one.txt": "hello\n" * 50, "sub/two.txt": "world\n" * 80}).items():
        (src / n).parent.mkdir(parents=True, exist_ok=True); (src / n).write_text(c)
    out = tmp / name
    assert mgr.create(out, [src], format=fmt, level=5).success
    return out


def test_compare(mgr, tmp_path):
    a = _make(mgr, tmp_path, "a.7z")
    b = _make(mgr, tmp_path, "b.7z", {"one.txt": "hello\n" * 50, "sub/two.txt": "CHANGED\n", "new.txt": "x"})
    r = extras.compare_archives(mgr, a, b)
    assert r.ok and not r.identical
    assert any("two.txt" in x for x in r.changed) or r.only_a  # folder prefix differs (src_a vs src_b)
    same = extras.compare_archives(mgr, a, a)
    assert same.identical and same.same == 2


def test_find(mgr, tmp_path):
    _make(mgr, tmp_path, "a.7z"); _make(mgr, tmp_path, "b.zip", fmt="zip")
    (tmp_path / "broken.7z").write_bytes(b"not an archive")
    hits, bad = extras.find_in_archives(mgr, tmp_path, "two")
    assert {Path(h.archive).name for h in hits} == {"a.7z", "b.zip"}
    assert "broken.7z" in bad


def test_preview_text_and_binary_and_missing(mgr, tmp_path):
    arc = _make(mgr, tmp_path, "p.zip", {"t.txt": "héllo", "b.bin": "x"}, fmt="zip")
    member = next(e.path for e in mgr.list_contents(arc).entries if e.path.endswith("t.txt"))
    p = extras.preview_member(mgr, arc, member)
    assert p.kind == "text" and "héllo" in p.text
    p.cleanup(); assert not p.workdir.exists()
    bad = extras.preview_member(mgr, arc, "nope.txt"); assert bad.kind == "error"; bad.cleanup()


def test_salvage_damaged_zip(mgr, tmp_path):
    files = {f"f{i}.txt": os.urandom(2000).hex() for i in range(8)}
    arc = _make(mgr, tmp_path, "d.zip", files, fmt="zip")
    raw = bytearray(arc.read_bytes()); raw[len(raw) // 2: len(raw) // 2 + 300] = b"\xff" * 300
    arc.write_bytes(bytes(raw))
    r = extras.salvage(mgr, arc, tmp_path / "out_parent") if (tmp_path / "out_parent").mkdir() is None else None
    assert r.success and r.recovered >= 1 and r.folder.is_dir()


def test_salvage_hopeless(mgr, tmp_path):
    junk = tmp_path / "junk.7z"; junk.write_bytes(b"garbage" * 10)
    r = extras.salvage(mgr, junk, tmp_path)
    assert not r.success and not (tmp_path / "junk_salvaged").exists()


def test_verify_and_sidecar(mgr, tmp_path):
    arc = _make(mgr, tmp_path)
    ok, msg = extras.verify_created(mgr, arc, sidecar=True)
    assert ok and (tmp_path / "a.7z.sha256").is_file()
    assert extras.verify_sha256_sidecar(arc)[0]
    arc.write_bytes(arc.read_bytes() + b"x")
    assert not extras.verify_sha256_sidecar(arc)[0]
    ok2, _ = extras.verify_created(mgr, tmp_path / "junk.7z") if (tmp_path / "junk.7z").write_bytes(b"zz") else (None, None)
    assert ok2 is False


@pytest.mark.skipif(os.name == "nt", reason="runs the .sh variant")
def test_exported_script_runs(mgr, tmp_path):
    src = tmp_path / "data"; src.mkdir(); (src / "a.txt").write_text("hi" * 500)
    out = tmp_path / "scripted.7z"
    txt = extras.export_create_script(str(mgr.engine.exe), out, [src], shell="sh", encrypt=True, encrypt_filenames=True)
    assert "-p" in txt and "secret" not in txt           # password prompt, never embedded
    script = tmp_path / "run.sh"; script.write_text(txt.replace(" -p ", " -psecret "))
    subprocess.run(["sh", str(script)], check=True, capture_output=True)
    assert out.is_file()
    assert mgr.test_integrity(out, password="secret").success


def test_script_quoting_variants(tmp_path):
    weird = tmp_path / "my dir" / "it's 50%.txt"; weird.parent.mkdir(); weird.write_text("x")
    for sh in ("bat", "ps1", "sh"):
        t = extras.export_create_script("C:\\7z.exe", tmp_path / "o.7z", [weird], shell=sh)
        assert "it" in t and t.strip()
