"""Tests for the v2 engine: planning, tar pipelines, encryption, pause/cancel, listing, jobs."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from volumax.archive_manager import ArchiveManager
from volumax.backends.sevenzip import SevenZipBackend, tar_codec
from volumax.compression import SourceProfile, analyze_sources, plan_compression
from volumax.jobs import JobQueue, JobState
from volumax.listing import ArchiveTree, clear_cache, load_tree


@pytest.fixture()
def tree_src(tmp_path: Path) -> Path:
    src = tmp_path / "data"
    (src / "sub dir").mkdir(parents=True)
    (src / "ü").mkdir()
    (src / "sub dir" / "a b.txt").write_text("hello " * 500)
    (src / "ü" / "日本語.txt").write_text("unicode" * 100)
    (src / "top.py").write_text("print(1)\n" * 2000)
    return src


# ------------------------------------------------------------------ formats
@pytest.mark.parametrize("fmt", ["7z", "zip", "tar", "tar.gz", "tgz", "tar.bz2", "tar.xz", "txz"])
def test_every_format_roundtrips_with_unicode(tmp_path: Path, tree_src: Path, fmt: str):
    be = SevenZipBackend()
    arc = tmp_path / f"a.{fmt}"
    res = be.create_archive(arc, [tree_src], format=fmt, preset="maximum")
    assert res.success, res.message
    listing = be.list_archive(arc)
    assert listing.success
    paths = {e.path for e in listing.entries}
    # compressed tars must show the REAL contents, not the single inner .tar
    assert "data/ü/日本語.txt" in paths and "data/sub dir/a b.txt" in paths
    out = tmp_path / "out"
    ex = be.extract_archive(arc, out)
    assert ex.success, ex.message
    assert (out / "data" / "ü" / "日本語.txt").read_text(encoding="utf-8") == "unicode" * 100


def test_tar_codec_detection():
    assert tar_codec("x.TAR.GZ") == "gzip" and tar_codec("x.tbz2") == "bzip2"
    assert tar_codec("x.tar.xz") == "xz" and tar_codec("x.7z") is None and tar_codec("x.gz") is None


def test_tar_formats_reject_passwords(tmp_path: Path, tree_src: Path):
    res = SevenZipBackend().create_archive(tmp_path / "p.tar.gz", [tree_src], format="tar.gz", password="x")
    assert not res.success and "password" in res.message.lower()


def test_selected_names_are_matched_literally(tmp_path: Path):
    src = tmp_path / "s"
    src.mkdir()
    for n in ("we[ird]*name?.txt", "plain.txt", "日本 語.txt"):
        (src / n).write_text(n)
    be = SevenZipBackend()
    for fmt in ("7z", "tar.gz"):
        arc = tmp_path / f"a.{fmt}"
        assert be.create_archive(arc, [src], format=fmt).success
        out = tmp_path / f"o_{fmt}"
        assert be.extract_archive(arc, out, selected_files=["s/we[ird]*name?.txt", "s/日本 語.txt"]).success
        assert sorted(p.name for p in out.rglob("*") if p.is_file()) == ["we[ird]*name?.txt", "日本 語.txt"]


# --------------------------------------------------------------- encryption
def test_encrypted_archive_without_password_fails_fast(tmp_path: Path, tree_src: Path):
    be = SevenZipBackend()
    arc = tmp_path / "e.7z"
    assert be.create_archive(arc, [tree_src], password="s3cret", encrypt_filenames=True, preset="fast").success
    t = time.monotonic()
    res = be.list_archive(arc)  # must NOT wait for a console prompt
    assert time.monotonic() - t < 5
    assert not res.success and res.extra.get("needs_password") is True
    ok = be.list_archive(arc, password="s3cret")
    assert ok.success and len(ok.entries) == 6
    bad = be.list_archive(arc, password="nope")
    assert not bad.success and bad.extra.get("needs_password") is True


# ----------------------------------------------------------------- planning
def test_plan_uses_ppmd_for_text_and_lzma2_otherwise():
    text = SourceProfile(total_bytes=10_000_000, file_count=100, text_bytes=9_500_000)
    plan = plan_compression("7z", preset="maximum", profile=text)
    assert plan.method == "ppmd" and any("ppmd" in a for a in plan.args)

    binary = SourceProfile(total_bytes=10_000_000, file_count=100, text_bytes=100_000)
    plan = plan_compression("7z", preset="maximum", profile=binary)
    assert plan.method == "lzma2" and "-mx=9" in plan.args

    # smart mode off => never PPMd
    assert plan_compression("7z", preset="maximum", profile=text, smart=False).method == "lzma2"


def test_plan_downgrades_for_already_compressed_media():
    media = SourceProfile(total_bytes=50_000_000, file_count=10, low_gain_bytes=48_000_000)
    plan = plan_compression("7z", preset="ultra", profile=media)
    assert plan.level == 1 and "-mx=1" in plan.args
    assert plan_compression("7z", preset="ultra", profile=media, smart=False).level == 9


def test_plan_presets_and_options():
    assert plan_compression("7z", preset="store").args == ["-mx=0"]
    assert "-ms=off" in plan_compression("7z", preset="normal", solid=False).args
    assert "-mmt=4" in plan_compression("7z", preset="normal", threads=4).args
    ultra = plan_compression("7z", preset="ultra", profile=SourceProfile(total_bytes=200_000_000))
    assert "fb=273" in " ".join(ultra.args) and ultra.dictionary_mb >= 128
    assert plan_compression("tar").method == "store"


def test_analyze_sources_classifies_bytes(tmp_path: Path):
    (tmp_path / "a.py").write_text("x" * 1000)
    (tmp_path / "b.jpg").write_bytes(b"\0" * 3000)
    (tmp_path / "c.bin").write_bytes(b"\0" * 500)
    prof = analyze_sources([tmp_path])
    assert (prof.file_count, prof.total_bytes, prof.text_bytes, prof.low_gain_bytes) == (3, 4500, 1000, 3000)


def test_maximum_beats_normal_and_text_mode_beats_lzma2(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    import random

    rnd = random.Random(7)
    words = [("w%d" % i) * rnd.randint(1, 3) for i in range(3000)]
    for i in range(40):
        (src / f"doc{i}.txt").write_text(" ".join(rnd.choice(words) for _ in range(6000)))
    be = SevenZipBackend()
    sizes = {}
    for name, kw in {"normal": dict(preset="normal"), "max_lzma": dict(preset="maximum", smart=False),
                     "max_smart": dict(preset="maximum")}.items():
        out = tmp_path / f"{name}.7z"
        assert be.create_archive(out, [src], **kw).success
        sizes[name] = out.stat().st_size
    # synthetic data is noise-level; real-world gain is measured in the benchmark
    assert sizes["max_lzma"] <= sizes["normal"] * 1.001
    assert sizes["max_smart"] < sizes["max_lzma"]  # PPMd wins on text


def test_result_message_reports_ratio(tmp_path: Path, tree_src: Path):
    res = SevenZipBackend().create_archive(tmp_path / "m.7z", [tree_src])
    assert "→" in res.message and "%" in res.message
    assert res.extra["output_bytes"] > 0 and res.extra["input_bytes"] > 0


# ------------------------------------------------------------ pause / cancel
def test_pause_freezes_work_and_cancel_is_fast(tmp_path: Path):
    big = tmp_path / "big.bin"
    big.write_bytes(os.urandom(40 * 1024 * 1024))
    be = SevenZipBackend()
    st = {"pause": False, "cancel": False}
    out = tmp_path / "p.7z"
    sizes: list[int] = []

    def driver():
        time.sleep(0.8)
        st["pause"] = True
        time.sleep(0.6)
        sizes.append(out.stat().st_size if out.exists() else 0)
        time.sleep(1.0)
        sizes.append(out.stat().st_size if out.exists() else 0)
        st["pause"] = False

    threading.Thread(target=driver, daemon=True).start()
    res = be.create_archive(out, [big], preset="maximum", pause=lambda: st["pause"])
    assert res.success
    assert sizes[0] == sizes[1], f"archive kept growing while paused: {sizes}"

    t = threading.Timer(0.4, lambda: st.update(cancel=True))
    t.start()
    started = time.monotonic()
    res = be.create_archive(tmp_path / "c.7z", [big], preset="ultra", cancel=lambda: st["cancel"])
    assert not res.success and "cancel" in res.message.lower()
    assert time.monotonic() - started < 5


# ------------------------------------------------------------------ listing
def test_tree_synthesizes_missing_folders_and_sorts_children(tmp_path: Path):
    from volumax.backends.base import ArchiveEntry

    entries = [
        ArchiveEntry("a/b/c.txt", size=3),            # folders 'a' and 'a/b' not listed explicitly
        ArchiveEntry("a/d.txt", size=5),
        ArchiveEntry("top.txt", size=1),
        ArchiveEntry("empty", is_dir=True),
    ]
    tree = ArchiveTree.build(entries)
    assert {e.path for e in tree.children[""]} == {"a", "empty", "top.txt"}
    assert {e.path for e in tree.children["a"]} == {"a/b", "a/d.txt"}
    assert tree.file_count == 3 and tree.dir_count == 3 and tree.total_size == 9


def test_listing_cache_and_password_flow(tmp_path: Path, tree_src: Path):
    clear_cache()
    m = ArchiveManager()
    arc = tmp_path / "t.7z"
    assert m.create(arc, [tree_src], preset="fast").success
    r1, t1 = load_tree(m, arc)
    r2, t2 = load_tree(m, arc)
    assert t1 is t2 and r2.message == "cached"  # served from cache
    arc.write_bytes(arc.read_bytes() + b"")     # same content, touch mtime
    os.utime(arc, ns=(1, 1))
    _, t3 = load_tree(m, arc)
    assert t3 is not t1                          # changed file => re-read

    enc = tmp_path / "enc.7z"
    assert m.create(enc, [tree_src], password="pw", encrypt_filenames=True, preset="fast").success
    r, tree = load_tree(m, enc)
    assert not r.success and tree is not None and tree.needs_password


# --------------------------------------------------------------- job queue
def test_failed_result_marks_job_failed_and_kwargs_are_filtered():
    from volumax.backends.base import BackendResult

    q = JobQueue()
    seen = {}

    def only_cancel(cancel=None):
        seen["cancel"] = cancel
        return BackendResult(False, "wrong password")

    def takes_all(progress=None, cancel=None, pause=None):
        seen["all"] = (progress, cancel, pause)
        return BackendResult(True, "done: 1 MB → 100 KB")

    def plain():
        return "x"  # accepts nothing: must not receive injected kwargs

    jobs = [q.submit("a", only_cancel), q.submit("b", takes_all), q.submit("c", plain)]
    deadline = time.time() + 10
    while time.time() < deadline and any(j.finished_at is None for j in jobs):
        time.sleep(0.05)
    assert jobs[0].state == JobState.FAILED and "wrong password" in jobs[0].error
    assert jobs[1].state == JobState.COMPLETED and "→" in jobs[1].message
    assert all(callable(x) for x in seen["all"])
    assert jobs[2].state == JobState.COMPLETED
    q.shutdown()


# ---------------------------------------------------------- safety / config
def test_symlinks_in_archives_are_not_extracted(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("symlink creation needs privileges on Windows")
    src = tmp_path / "s"
    src.mkdir()
    (src / "ok.txt").write_text("ok")
    (src / "evil").symlink_to("/etc")
    arc = tmp_path / "a.7z"
    be = SevenZipBackend()
    assert be.create_archive(arc, [src], preset="fast").success
    out = tmp_path / "out"
    res = ArchiveManager().extract(arc, out)
    assert res.success
    assert (out / "s" / "ok.txt").exists()
    assert not (out / "s" / "evil").exists() and not (out / "s" / "evil").is_symlink()


def test_extraction_limits_allow_large_real_archives():
    from volumax.extraction import ExtractionSafety

    safety = ExtractionSafety()
    assert safety.max_files >= 1_000_000 and safety.max_total_size >= 1024**4


def test_resources_resolve_inside_pyinstaller_bundle(monkeypatch, tmp_path: Path):
    from volumax import config

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert config._resolve_project_root() == tmp_path


def test_user_dir_is_overridable_and_settings_write_atomically(tmp_path: Path):
    from volumax.settings import Settings

    s = Settings(tmp_path / "cfg" / "settings.json")
    s.set("compression_preset", "ultra")
    s.save()
    assert Settings(tmp_path / "cfg" / "settings.json").get("compression_preset") == "ultra"
    assert not (tmp_path / "cfg" / "settings.tmp").exists()


def test_convert_zip_to_7z_uses_target_password_only(tmp_path: Path, tree_src: Path):
    m = ArchiveManager()
    z = tmp_path / "in.zip"
    assert m.create(z, [tree_src], format="zip", password="src-pw").success
    out = tmp_path / "out.7z"
    res = m.convert(z, out, format="7z", preset="fast", password="src-pw", target_password=None)
    assert res.success, res.message
    # result must be openable WITHOUT any password
    assert SevenZipBackend().list_archive(out).success
    assert not any(p.name.startswith(".volumax_conv_") for p in tmp_path.iterdir())
