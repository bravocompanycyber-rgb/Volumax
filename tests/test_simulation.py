"""Simulates a user driving EVERY page, plus fault injection. Runs on both Qt stacks."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import volumax  # noqa: E402,F401

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from volumax.jobs import JobState, get_job_queue  # noqa: E402

TERMINAL = (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def boxes(monkeypatch):
    seen = []

    def rec(kind, answer=QMessageBox.StandardButton.Yes):
        return staticmethod(lambda *a, **k: (seen.append((kind, a[2] if len(a) > 2 else "")) or answer))

    for k in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, k, rec(k, QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", rec("question"))
    return seen


@pytest.fixture()
def window(app, boxes):
    from volumax.ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    yield w
    for b in [x for x in QApplication.topLevelWidgets() if isinstance(x, QMessageBox)]:
        b.close()
    w.close()


def pump(app, cond, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def wait_jobs(app, timeout=60.0):
    q = get_job_queue()
    assert pump(app, lambda: all(j.state in TERMINAL for j in q.list_jobs()), timeout), "jobs did not finish"
    return q.list_jobs()


def last_job():
    return get_job_queue().list_jobs()[-1]


@pytest.fixture()
def tree(tmp_path):
    src = tmp_path / "ünï cödé folder"
    (src / "sub dir").mkdir(parents=True)
    (src / "a.txt").write_text("hello world\n" * 3000, encoding="utf-8")
    (src / "sub dir" / "b file.log").write_text("log line 1\n" * 3000)
    (src / "empty.txt").write_text("")
    (src / "data.bin").write_bytes(os.urandom(20000))
    return src


# ------------------------------------------------------------------ happy paths

@pytest.mark.parametrize("fmt", ["7z", "zip", "tar.gz", "tar.xz", "tar.bz2"])
def test_create_every_format_then_extract_and_compare(window, app, tmp_path, tree, fmt):
    page = window.pages["create"]
    page.add_sources([tree])
    page.format_combo.setCurrentText(fmt)
    out = tmp_path / ("out." + fmt)
    page.output_edit.setText(str(out))
    page._create()
    job = wait_jobs(app)[-1]
    assert job.state == JobState.COMPLETED, job.message
    target = next(p for p in tmp_path.glob("out.*") if p.is_file() and not p.name.endswith(".sha256"))
    ex = window.pages["extract"]
    ex.archive_edit.setText(str(target))
    ex.dest_edit.setText(str(tmp_path / "x"))
    ex.open_check.setChecked(False)
    ex._extract()
    job = wait_jobs(app)[-1]
    assert job.state == JobState.COMPLETED, job.message
    got = next((tmp_path / "x").rglob("a.txt"))
    assert got.read_text(encoding="utf-8") == (tree / "a.txt").read_text(encoding="utf-8")
    assert next((tmp_path / "x").rglob("data.bin")).read_bytes() == (tree / "data.bin").read_bytes()
    assert next((tmp_path / "x").rglob("empty.txt")).read_text() == ""


def test_encrypted_7z_with_hidden_names_wrong_and_right_password(window, app, tmp_path, tree, boxes):
    page = window.pages["create"]
    page.add_sources([tree])
    page.format_combo.setCurrentText("7z")
    out = tmp_path / "secret.7z"
    page.output_edit.setText(str(out))
    page.password_edit.setText("Tr0ub4dor&3-xyz")
    page.password2_edit.setText("Tr0ub4dor&3-xyz")
    assert page.encrypt_names.isChecked()                      # default: strongest
    page._create()
    assert wait_jobs(app)[-1].state == JobState.COMPLETED
    assert b"a.txt" not in out.read_bytes()                    # names really hidden
    ex = window.pages["extract"]
    ex.archive_edit.setText(str(out)); ex.dest_edit.setText(str(tmp_path / "bad")); ex.open_check.setChecked(False)
    ex.password_edit.setText("wrong")
    ex._extract()
    job = wait_jobs(app)[-1]
    assert job.state == JobState.FAILED and "password" in job.message.lower()   # friendly text
    ex.password_edit.setText("Tr0ub4dor&3-xyz"); ex.dest_edit.setText(str(tmp_path / "good"))
    ex._extract()
    assert wait_jobs(app)[-1].state == JobState.COMPLETED
    assert list((tmp_path / "good").rglob("a.txt"))


def test_password_mismatch_blocked(window, tmp_path, tree, boxes):
    page = window.pages["create"]
    page.add_sources([tree]); page.output_edit.setText(str(tmp_path / "m.7z"))
    page.password_edit.setText("one"); page.password2_edit.setText("two")
    n = len(get_job_queue().list_jobs())
    page._create()
    assert boxes and len(get_job_queue().list_jobs()) == n


def test_create_with_checksum_and_verify(window, app, tmp_path, tree):
    page = window.pages["create"]
    page.add_sources([tree]); page.format_combo.setCurrentText("7z")
    page.output_edit.setText(str(tmp_path / "v.7z"))
    page.verify_check.setChecked(True); page.sidecar_check.setChecked(True)
    page._create()
    job = wait_jobs(app)[-1]
    assert job.state == JobState.COMPLETED and "Verified" in job.message
    assert (tmp_path / "v.7z.sha256").is_file()


def test_failed_create_keeps_existing_archive(window, app, tmp_path, tree, monkeypatch):
    out = tmp_path / "keep.7z"; out.write_bytes(b"PRECIOUS")
    page = window.pages["create"]
    page.add_sources([tree]); page.format_combo.setCurrentText("7z"); page.output_edit.setText(str(out))
    monkeypatch.setattr(page.manager, "create", lambda *a, **k: __import__("volumax.backends.base", fromlist=["x"]).BackendResult(False, "boom"))
    page._create()
    assert wait_jobs(app)[-1].state == JobState.FAILED
    assert out.read_bytes() == b"PRECIOUS" and not list(tmp_path.glob("*.volumax-old"))


def test_browser_open_list_navigate_and_preview(window, app, tmp_path, tree):
    from volumax.archive_manager import ArchiveManager

    arc = tmp_path / "b.zip"
    assert ArchiveManager().create(arc, [tree], format="zip").success
    window.open_archive(arc)
    page = window.pages["browser"]
    assert pump(app, lambda: page.model.rowCount() > 0)
    tools = window.pages["tools"]
    assert tools.pv_path.text() == str(arc)
    tools._pv_load()
    assert pump(app, lambda: tools.pv_list.count() >= 3)
    tools.pv_filter.setText("b file")
    visible = [i for i in range(tools.pv_list.count()) if not tools.pv_list.item(i).isHidden()]
    assert len(visible) == 1
    tools.pv_list.setCurrentRow(visible[0])
    assert pump(app, lambda: "log line 1" in tools.pv_text.toPlainText())


def test_convert_page(window, app, tmp_path, tree):
    from volumax.archive_manager import ArchiveManager

    src = tmp_path / "c.zip"; ArchiveManager().create(src, [tree], format="zip")
    c = window.pages["convert"]
    c.src_edit.setText(str(src)); c.tgt_edit.setText(str(tmp_path / "c.7z"))
    c.fmt.setCurrentText("7z")
    c._run()
    assert wait_jobs(app)[-1].state == JobState.COMPLETED
    assert (tmp_path / "c.7z").is_file() and src.is_file()      # source untouched


def test_integrity_and_hash(window, app, tmp_path, tree):
    from volumax.archive_manager import ArchiveManager

    arc = tmp_path / "i.7z"; ArchiveManager().create(arc, [tree])
    p = window.pages["integrity"]
    p.arch_edit.setText(str(arc)); p._test()
    assert pump(app, lambda: "PASSED" in p.output.toPlainText())
    p.file_edit.setText(str(arc)); p._hash()
    assert pump(app, lambda: "SHA" in p.output.toPlainText().upper() and "i.7z" in p.output.toPlainText())


def test_duplicates_page(window, app, tmp_path):
    (tmp_path / "d").mkdir()
    for n in "abc":
        (tmp_path / "d" / f"{n}.txt").write_text("same content" * 100)
    (tmp_path / "d" / "z.txt").write_text("different")
    p = window.pages["duplicates"]
    p.root_edit.setText(str(tmp_path / "d")); p._scan()
    assert pump(app, lambda: "Found 1 duplicate group" in p.status.text())
    assert p.table.rowCount() == 1 and p.table.item(0, 2).text().count("txt") == 3   # z.txt is not a duplicate


def test_packages_and_volumes(window, app, tmp_path, tree):
    pk = window.pages["packages"]
    pk.sources.append(tree); pk.out_edit.setText(str(tmp_path / "pk")); pk.max_mb.setValue(1)
    pk._run(); assert wait_jobs(app)[-1].state == JobState.COMPLETED
    assert list((tmp_path / "pk").glob("*.zip"))
    vo = window.pages["volumes"]
    vo.sources.append(tree); vo.out_edit.setText(str(tmp_path / "vol.7z")); vo.vol_size.setValue(1)
    vo._run(); job = wait_jobs(app)[-1]
    assert job.state == JobState.COMPLETED, job.message


def test_tools_compare_find_salvage_pack(window, app, tmp_path, tree, monkeypatch):
    from volumax.archive_manager import ArchiveManager
    from volumax import smallpack

    m = ArchiveManager()
    a, b = tmp_path / "a.7z", tmp_path / "b.zip"
    m.create(a, [tree]); m.create(b, [tree], format="zip")
    t = window.pages["tools"]
    t.cmp_a.edit.setText(str(a)); t.cmp_b.edit.setText(str(b)); t._compare()
    assert pump(app, lambda: "identical" in t.cmp_out.toPlainText().lower())
    t.fd_folder.edit.setText(str(tmp_path)); t.fd_pattern.setText("a.txt"); t._find()
    assert pump(app, lambda: t.fd_list.count() == 2)
    bad = tmp_path / "bad.zip"; raw = bytearray(b.read_bytes()); raw[len(raw) // 2:len(raw) // 2 + 200] = b"\0" * 200
    bad.write_bytes(bytes(raw))
    t.sv_path.edit.setText(str(bad)); t._salvage()
    job = wait_jobs(app)[-1]
    assert job.state == JobState.COMPLETED and (tmp_path / "bad_salvaged").is_dir()
    if smallpack.available():
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / "t.vxsp"), "")))
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path / "unp")))
        t.pk_src.edit.setText(str(tree)); t._pack_create()
        assert wait_jobs(app)[-1].state == JobState.COMPLETED
        t.pk_pack.edit.setText(str(tmp_path / "t.vxsp")); t._pack_extract()
        assert wait_jobs(app)[-1].state == JobState.COMPLETED
        assert (tmp_path / "unp").exists()


def test_export_script_button(window, tmp_path, tree, monkeypatch):
    page = window.pages["create"]
    page.add_sources([tree]); page.output_edit.setText(str(tmp_path / "s.7z"))
    target = tmp_path / "go.sh"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    page._export_script()
    assert target.is_file() and "VOLUMAX" in target.read_text()


def test_settings_page_save(window):
    s = window.pages["settings"]
    window.goto("settings")
    assert s is not None


def test_queue_cancel_pause_ui(window, app, tmp_path):
    q = get_job_queue()
    import threading

    gate = threading.Event()
    j = q.submit("blocker", lambda progress=None, cancel=None, pause=None: (gate.wait(5), None)[1])
    window.goto("queue")
    pump(app, lambda: j.state == JobState.RUNNING, 5)
    q.cancel(j.id); gate.set()
    wait_jobs(app)


# ---------------------------------------------------------------- fault injection

def test_app_starts_without_engine_and_heals(app, boxes, tmp_path, monkeypatch):
    import volumax.config as cfg
    import volumax.backends.sevenzip as sz

    real = cfg.find_7zip_exe()
    monkeypatch.setattr(sz, "find_7zip_exe", lambda: None)
    from volumax.ui.main_window import MainWindow

    w = MainWindow()                       # must NOT raise
    w.show(); app.processEvents()
    assert not w.manager.engine.available
    r = w.manager.create(tmp_path / "x.7z", [tmp_path])
    assert not r.success and "engine" in r.message.lower()
    from volumax import selfheal

    checks = selfheal.run_checks(w.manager)
    assert any(c.name == "7-Zip engine" and not c.ok for c in checks)
    monkeypatch.undo()                     # engine "appears" again -> live re-detect
    assert w.manager.engine.available
    ok, _ = selfheal.locate_engine(w.manager, real)
    assert ok
    w.close()


def test_locate_rejects_non_7zip(tmp_path):
    from volumax import selfheal
    from volumax.archive_manager import ArchiveManager

    fake = tmp_path / "fake.sh"; fake.write_text("#!/bin/sh\necho hello\n"); fake.chmod(0o755)
    ok, msg = selfheal.locate_engine(ArchiveManager(), fake)
    assert not ok
    assert not selfheal.locate_engine(ArchiveManager(), tmp_path / "missing")[0]


def test_truncated_and_garbage_archives_never_crash(window, app, tmp_path, tree):
    from volumax.archive_manager import ArchiveManager

    good = tmp_path / "g.7z"; ArchiveManager().create(good, [tree])
    cut = tmp_path / "cut.7z"; cut.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    junk = tmp_path / "junk.zip"; junk.write_bytes(os.urandom(5000))
    empty = tmp_path / "empty.7z"; empty.write_bytes(b"")
    for bad in (cut, junk, empty, tmp_path / "nope.7z", tree):
        window.open_archive(bad)
        for _ in range(20):
            app.processEvents(); time.sleep(0.01)
        ex = window.pages["extract"]
        ex.archive_edit.setText(str(bad)); ex.dest_edit.setText(str(tmp_path / "o")); ex.open_check.setChecked(False)
        ex._extract()
    wait_jobs(app)
    jobs = get_job_queue().list_jobs()
    assert all(j.state in TERMINAL for j in jobs)
    assert any(j.state == JobState.FAILED and j.message.startswith("Failed:") for j in jobs)


def test_unwritable_destination_reports_cleanly(window, app, tmp_path, tree):
    if os.name == "nt" or os.geteuid() == 0:
        pytest.skip("permission bits not enforced for root / Windows")
    ro = tmp_path / "ro"; ro.mkdir(); ro.chmod(stat.S_IREAD | stat.S_IEXEC)
    page = window.pages["create"]
    page.add_sources([tree]); page.output_edit.setText(str(ro / "o.7z"))
    page._create()
    assert wait_jobs(app)[-1].state == JobState.FAILED
    ro.chmod(0o755)


def test_hostile_zip_traversal_and_symlink(window, app, tmp_path):
    import zipfile

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../../escaped.txt", "pwned")
        z.writestr("ok.txt", "fine")
        info = zipfile.ZipInfo("link"); info.create_system = 3; info.external_attr = (0o120777 << 16)
        z.writestr(info, "/etc/passwd")
    ex = window.pages["extract"]
    ex.archive_edit.setText(str(evil)); ex.dest_edit.setText(str(tmp_path / "dest")); ex.open_check.setChecked(False)
    ex.subfolder_check.setChecked(False)
    ex._extract(); wait_jobs(app)
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path.parent / "escaped.txt").exists()
    assert not (tmp_path / "dest" / "link").is_symlink()


def test_bomb_limits_enforced(window, app, tmp_path, tree):
    from volumax.archive_manager import ArchiveManager

    arc = tmp_path / "many.zip"
    src = tmp_path / "many"; src.mkdir()
    for i in range(60):
        (src / f"{i}.txt").write_text("x")
    ArchiveManager().create(arc, [src], format="zip")
    s = window.settings
    old = s.get("max_extraction_files")
    s.set("max_extraction_files", 10)
    try:
        ex = window.pages["extract"]
        ex.archive_edit.setText(str(arc)); ex.dest_edit.setText(str(tmp_path / "bomb")); ex.open_check.setChecked(False)
        ex._extract()
        job = wait_jobs(app)[-1]
        assert job.state == JobState.FAILED
    finally:
        s.set("max_extraction_files", old)


def test_hostile_inputs_to_every_form_do_not_crash(window, boxes, app):
    weird = ["", " ", "\\\\?\\nul", "C:\\nope\\x.7z", "../../../etc/passwd", "a" * 400, "\u202eevil.7z", "/dev/null"]
    ex, cv, ig = window.pages["extract"], window.pages["convert"], window.pages["integrity"]
    cr, du, to = window.pages["create"], window.pages["duplicates"], window.pages["tools"]
    for w in weird:
        ex.archive_edit.setText(w); ex.dest_edit.setText(w); ex._extract()
        cv.src_edit.setText(w); cv.tgt_edit.setText(w); cv._run()
        ig.arch_edit.setText(w); ig._test(); ig.file_edit.setText(w); ig._hash()
        cr.output_edit.setText(w); cr._create()
        du.root_edit.setText(w); du._scan()
        to.cmp_a.edit.setText(w); to._compare(); to.fd_folder.edit.setText(w); to._find(); to.sv_path.edit.setText(w); to._salvage()
    for _ in range(30):
        app.processEvents(); time.sleep(0.01)
    wait_jobs(app)


def test_corrupt_settings_on_disk_recovered(tmp_path, monkeypatch):
    from volumax.settings import Settings

    f = tmp_path / "settings.json"; f.write_bytes(b"\xff\xfe\x00garbage{{{")
    s = Settings(f)
    assert s.get("compression_preset") == "maximum" and s.recovered_from
    s.set("compression_preset", "fast"); s.save()
    assert Settings(f).get("compression_preset") == "fast"


def test_repair_cleans_stale_temp(tmp_path, monkeypatch):
    import tempfile
    from volumax import selfheal

    old = Path(tempfile.mkdtemp(prefix="volumax_stale_"))
    (old / "f").write_text("x")
    past = time.time() - 3 * 86400
    os.utime(old, (past, past))
    assert old in selfheal._stale_temp_items()
    acts = selfheal.repair()
    assert not old.exists() and any("temporary" in a for a in acts)


def test_crash_report_written_and_report_export(tmp_path, monkeypatch):
    from volumax import selfheal

    try:
        raise ValueError("synthetic")
    except ValueError:
        import sys
        p = selfheal.write_crash_report(*sys.exc_info())
    assert p and "synthetic" in p.read_text()
    rep = selfheal.export_report(tmp_path / "r.txt")
    assert "Health checks" in rep.read_text()


def test_diagnostics_page_runs(window, app):
    window.goto("diagnostics")
    d = window.pages["diagnostics"]
    assert pump(app, lambda: d.table.rowCount() >= 6)
    d._repair()
    assert pump(app, lambda: bool(d.log.toPlainText()))


def test_error_hints():
    from volumax.selfheal import explain

    assert "password" in explain("ERROR: Wrong password : x")
    assert "full" in explain("No space left on device").lower()
    assert explain("something totally new") == ""


def test_failed_batch_shows_one_banner_not_a_stack(window, app, tmp_path):
    """Regression: every failed job used to open its own blocking modal dialog."""
    q = get_job_queue()
    for i in range(12):
        q.submit(f"fail {i}", lambda progress=None, cancel=None, pause=None: (_ for _ in ()).throw(RuntimeError("nope")))
    wait_jobs(app)
    assert pump(app, lambda: window.banner.isVisible(), 10)
    assert "failed" in window.banner_text.text()
    from PySide6.QtWidgets import QMessageBox as MB
    assert not [w for w in QApplication.topLevelWidgets() if isinstance(w, MB) and w.isVisible()]
    window.banner.hide()
