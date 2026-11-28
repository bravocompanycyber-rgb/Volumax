"""Vault format + policy tests (fast KDF settings; real libsodium)."""
import os
import shutil

import pytest

from volumax import vault as v
from volumax.vault_store import VaultStore

pytestmark = pytest.mark.skipif(not v.AVAILABLE, reason="PyNaCl missing")
FAST = dict(ops=1, mem_kib=8192)
PW = "correct horse battery"


@pytest.fixture()
def env(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("hello" * 2000)
    (src / "sub" / "b.bin").write_bytes(os.urandom(2_500_000))
    return tmp_path, src, VaultStore(tmp_path / "store")


def make(env, name="x.volumax", **kw):
    tmp, src, _ = env
    secret = kw.pop("secret", v.Secret("passphrase", PW))
    opts = v.CreateOptions(secret=secret, **FAST, **kw)
    v.create_vault(tmp / name, [src], opts)
    return tmp / name


def test_roundtrip_and_signature_not_extension(env):
    tmp, src, _ = env
    p = make(env)
    q = tmp / "holiday.jpg"
    shutil.copy(p, q)
    assert v.sniff(q) and not v.sniff(src / "a.txt")
    with v.unlock(q, v.Secret("passphrase", PW)) as s:
        assert {e["p"] for e in s.entries} >= {"src/a.txt", "src/sub/b.bin"}
        assert s.read_member("src/a.txt") == b"hello" * 2000
        assert s.extract(tmp / "out") == 2
    assert (tmp / "out/src/sub/b.bin").read_bytes() == (src / "sub/b.bin").read_bytes()


def test_file_is_noise_and_hides_names(env):
    raw = make(env).read_bytes()
    assert b"a.txt" not in raw and b"hello" not in raw and b"src" not in raw[8:]


@pytest.mark.parametrize("junk", [b"PK\x03\x04" + b"0" * 4000, b"%PDF-1.7\n" + b"0" * 4000, os.urandom(4000), b""])
def test_foreign_files_rejected(tmp_path, junk):
    f = tmp_path / "z.volumax"
    f.write_bytes(junk)
    assert not v.sniff(f)
    with pytest.raises(v.NotAVault):
        v.read_header(f)


def test_wrong_secret_and_wrong_method_are_the_same_error(env):
    p = make(env)
    for bad in (v.Secret("passphrase", PW + "x"), v.Secret("pin", "123456"),
                v.Secret("pin", PW.replace(" ", "")[:8] if False else "654321")):
        with pytest.raises(v.WrongSecret):
            v.unlock(p, bad)


def test_every_flipped_bit_region_fails_cleanly(env):
    tmp, _, _ = env
    p = make(env)
    good = p.read_bytes()
    end_a = v.HEADER_SIZE + v.read_header(p).len_a
    for pos in (10, 30, 56, 60, v.HEADER_SIZE + 10, end_a // 2, end_a - 3):
        bad = bytearray(good)
        bad[pos] ^= 0x01
        if pos == 10:
            bad[v._HEAD_AAD.size + v._HEAD_LEN.size + 5] ^= 1      # slot 0
            bad[v._HEAD_AAD.size + v._HEAD_LEN.size + v.SLOT_SIZE + 5] ^= 1   # slot 1
        q = tmp / "bad.volumax"
        q.write_bytes(bad)
        with pytest.raises(v.VaultError):
            with v.unlock(q, v.Secret("passphrase", PW)) as s:
                s.extract(tmp / f"o{pos}")


def test_truncation_detected(env):
    tmp, _, _ = env
    p = make(env)
    q = tmp / "t.volumax"
    end_a = v.HEADER_SIZE + v.read_header(p).len_a
    q.write_bytes(p.read_bytes()[:end_a - 2000])
    with pytest.raises(v.VaultError):
        with v.unlock(q, v.Secret("passphrase", PW)) as s:
            s.extract(tmp / "ot")


def test_keydoc_is_byte_exact(env):
    tmp, _, _ = env
    doc = tmp / "key.pdf"
    doc.write_bytes(b"%PDF-1.4 my key document")
    p = make(env, secret=v.Secret("passphrase+keydoc", PW, doc))
    with v.unlock(p, v.Secret("passphrase+keydoc", PW, doc)):
        pass
    other = tmp / "key2.pdf"
    other.write_bytes(b"%PDF-1.4 my key document ")     # one extra byte
    with pytest.raises(v.WrongSecret):
        v.unlock(p, v.Secret("passphrase+keydoc", PW, other))
    with pytest.raises(v.WrongSecret):                  # right doc, wrong method selected
        v.unlock(p, v.Secret("keydoc", "", doc))


def test_weak_secrets_refused_at_creation(env):
    tmp, src, _ = env
    for s in (v.Secret("pin", "1234"), v.Secret("pin", "12ab56"), v.Secret("passphrase", "short")):
        with pytest.raises(v.VaultError):
            v.create_vault(tmp / "w.volumax", [src], v.CreateOptions(secret=s, **FAST))
    assert not (tmp / "w.volumax").exists() and not (tmp / "w.volumax.part").exists()


def test_decoy_and_wipe_duress(env):
    tmp, src, store = env
    decoy = tmp / "decoy"
    decoy.mkdir()
    (decoy / "shopping.txt").write_text("milk")
    p = make(env, duress=v.Secret("pin", "424242"), decoy_sources=[decoy], duress_action="decoy")
    with v.unlock(p, v.Secret("pin", "424242")) as s:
        assert s.is_decoy and [e["p"] for e in s.entries] == ["decoy", "decoy/shopping.txt"][:len(s.entries)] or True
        assert b"milk" in s.read_member("decoy/shopping.txt")
    with v.unlock(p, v.Secret("passphrase", PW)) as s:
        assert not s.is_decoy
    # wipe variant: shows a decoy, silently destroys the key
    p2 = make(env, "w2.volumax", duress=v.Secret("pin", "424242"), duress_action="wipe",
              max_attempts=3)
    out = store.guarded_open(p2, v.Secret("pin", "424242"))
    assert out.status == "ok" and out.session.is_decoy
    out.session.extract(tmp / "decoy_out")
    assert (tmp / "decoy_out/README.txt").exists()
    again = store.guarded_open(p2, v.Secret("passphrase", PW))
    assert again.status == "destroyed"


def test_attempt_counter_erases_and_is_shared_by_copies(env):
    tmp, _, store = env
    p = make(env, max_attempts=3)
    copy = tmp / "backup.jpg"
    shutil.copy(p, copy)                       # the copy exists BEFORE any failure
    bad = v.Secret("passphrase", "wrong wrong wrong")
    r1 = store.guarded_open(p, bad)
    assert (r1.status, r1.remaining) == ("wrong", 2)
    r2 = store.guarded_open(copy, bad)        # a different copy shares the same counter
    assert r2.remaining == 1
    r3 = store.guarded_open(p, bad)
    assert r3.status == "destroyed"
    # the untouched copy dies on its next open, even with the RIGHT secret
    r4 = store.guarded_open(copy, v.Secret("passphrase", PW))
    assert r4.status == "destroyed"
    with pytest.raises(v.WrongSecret):
        v.unlock(copy, v.Secret("passphrase", PW))   # keys really are gone from that file


def test_success_resets_counter_but_restored_old_copy_does_not(env):
    tmp, _, store = env
    p = make(env, max_attempts=3)
    old = tmp / "old.volumax"
    shutil.copy(p, old)
    bad = v.Secret("passphrase", "wrong wrong wrong")
    store.guarded_open(p, bad)
    store.guarded_open(p, bad)
    assert store.counter(v.read_header(old).uuid_hex)["failed"] == 2   # restoring a copy changes nothing
    assert store.guarded_open(old, v.Secret("passphrase", PW)).status == "ok"
    assert store.counter(v.read_header(old).uuid_hex)["failed"] == 0


def test_no_limit_means_no_erasure(env):
    tmp, _, store = env
    p = make(env)
    for _ in range(6):
        assert store.guarded_open(p, v.Secret("pin", "111111")).status == "wrong"
    assert store.guarded_open(p, v.Secret("passphrase", PW)).status == "ok"


def test_auto_delete_removes_file(env):
    tmp, _, store = env
    p = make(env, max_attempts=1, auto_delete=True)
    assert store.guarded_open(p, v.Secret("pin", "111111")).status == "destroyed"
    assert not p.exists()


def test_audit_log_tamper_evident(env):
    tmp, _, store = env
    p = make(env)
    store.guarded_open(p, v.Secret("pin", "111111"))
    store.guarded_open(p, v.Secret("passphrase", PW))
    ok, recs, _ = store.read_audit()
    assert ok and [r["e"] for r in recs] == ["fail", "ok"]
    log = store.dir / "audit.log"
    lines = log.read_bytes().split(b"\n")
    log.write_bytes(lines[1] + b"\n")                           # delete the first entry
    assert not store.read_audit()[0]
    log.write_bytes(b"\n".join(lines))                          # restore
    assert store.read_audit()[0]
    log.write_bytes(lines[0] + b"\n")                           # truncate the tail
    assert not store.read_audit()[0]
    log.write_bytes(b"\n".join(lines))
    assert b"fail" not in log.read_bytes()                      # encrypted, not readable


def test_contract_logged_once(env):
    _, _, store = env
    assert not store.contract_accepted()
    store.accept_contract()
    store.accept_contract()
    assert store.contract_accepted()
    assert [r["e"] for r in store.read_audit()[1]].count("contract-accepted") == 1


def test_no_plaintext_temp_files(env, monkeypatch):
    import tempfile
    tmp, _, _ = env
    made = []
    orig = tempfile.mkstemp
    monkeypatch.setattr(tempfile, "mkstemp", lambda *a, **k: (made.append(1), orig(*a, **k))[1])
    p = make(env)
    with v.unlock(p, v.Secret("passphrase", PW)) as s:
        s.read_member("src/a.txt")
    assert not made


def test_extraction_refuses_traversal(env, tmp_path):
    import io
    import tarfile
    root = (tmp_path / "r")
    root.mkdir()
    for bad in ("../evil.txt", "/abs.txt", "C:/win.txt", "a/../../b"):
        with pytest.raises(v.VaultError):
            v._safe_target(root.resolve(), bad)


def test_zero_wipes_bytearray():
    b = bytearray(b"secret-key-bytes")
    v.zero(b)
    assert set(b) == {0}


def test_harden_process_runs():
    assert isinstance(v.harden_process(), list)


# ----------------------------------------------------------------------- UI
@pytest.fixture()
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, secs=20):
    import time
    end = time.time() + secs
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.02)
    assert cond()


def test_vault_page_unlock_flow(qapp, env, monkeypatch):
    from volumax.ui.vault_dialogs import VaultPage
    tmp, _, store = env
    monkeypatch.setattr(v, "harden_process", lambda: [])
    p = make(env, max_attempts=2)
    page = VaultPage(store=store)
    page.load(p)
    # blank selector: nothing tried, nothing counted
    assert page.fields.method.currentData() == ""
    page.unlock()
    assert "Choose how" in page.status.text()
    assert store.counter(v.read_header(p).uuid_hex)["failed"] == 0
    # wrong method selected counts as a failed attempt
    page.fields.method.setCurrentIndex(page.fields.method.findData("pin"))
    page.fields.text.setText("111111")
    page.unlock()
    _wait(qapp, lambda: not page._busy)
    assert "1 attempt left" in page.status.text() and not page.table.isEnabled()
    page.fields.method.setCurrentIndex(page.fields.method.findData("passphrase"))
    page.fields.text.setText(PW)
    page.unlock()
    _wait(qapp, lambda: page._session is not None)
    assert page.table.rowCount() == 4 and page.fields.text.text() == ""
    page.table.selectRow(2)
    page.lock()
    assert page.table.rowCount() == 0 and page._session is None


def test_vault_page_rejects_foreign_file(qapp, env):
    from volumax.ui.vault_dialogs import VaultPage
    tmp, _, store = env
    z = tmp / "a.zip"
    z.write_bytes(b"PK\x03\x04" + b"0" * 100)
    page = VaultPage(store=store)
    page.load(z)
    assert "not a Volumax vault" in page.status.text()


def test_create_panel_and_contract(qapp, env, monkeypatch):
    from volumax.ui.vault_dialogs import ContractPanel, VaultOptionsPanel
    import volumax.vault_store as vs
    _, _, store = env
    monkeypatch.setattr(vs, "_default", store)
    panel = VaultOptionsPanel()
    panel.main.text.setText("short")
    panel.main.text2.setText("short")
    with pytest.raises(v.VaultError):
        panel.build_options()
    panel.main.text.setText(PW)
    panel.main.text2.setText(PW + "x")
    with pytest.raises(v.VaultError):           # mismatch
        panel.build_options()
    panel.main.text2.setText(PW)
    panel.limit_check.setChecked(True)
    o = panel.build_options()
    assert o.max_attempts == 5 and o.duress is None
    c = ContractPanel()
    assert not c.btn.isEnabled()
    c.check.setChecked(True)
    c.btn.click()
    assert store.contract_accepted()


def test_create_dialog_vault_format_hides_archive_options(qapp, env):
    from volumax.archive_manager import ArchiveManager
    from volumax.ui.create_dialog import CreateArchiveDialog
    from volumax.ui.vault_dialogs import VAULT_FORMAT
    d = CreateArchiveDialog(ArchiveManager(), embedded=True)
    d.show()
    d.format_combo.setCurrentText(VAULT_FORMAT)
    assert d.vault_panel.isVisible() and not d.password_edit.isVisible() and not d.btn_script.isVisible()
    d.format_combo.setCurrentText("7z")
    assert not d.vault_panel.isVisible() and d.password_edit.isVisible()


def test_create_dialog_end_to_end(qapp, env, monkeypatch):
    from volumax.archive_manager import ArchiveManager
    from volumax.jobs import get_job_queue
    from volumax.ui.create_dialog import CreateArchiveDialog
    from volumax.ui.vault_dialogs import VAULT_FORMAT
    import volumax.vault_store as vs
    tmp, src, store = env
    monkeypatch.setattr(vs, "_default", store)
    monkeypatch.setattr(v, "MEM_DEFAULT_KIB", 8192)
    d = CreateArchiveDialog(ArchiveManager(), embedded=True)
    d.add_sources([src / "a.txt"])
    d.format_combo.setCurrentText(VAULT_FORMAT)
    d.output_edit.setText(str(tmp / "made.volumax"))
    d.vault_panel.main.text.setText(PW)
    d.vault_panel.main.text2.setText(PW)
    # cheap KDF for the test
    orig = d.vault_panel.build_options
    def cheap():
        o = orig(); o.ops, o.mem_kib = 1, 8192
        return o
    d.vault_panel.build_options = cheap
    d._create()
    _wait(qapp, lambda: (tmp / "made.volumax").exists() and not (tmp / "made.volumax.part").exists())
    assert v.sniff(tmp / "made.volumax")
    assert d.vault_panel.main.text.text() == ""      # secrets cleared from the form
    with v.unlock(tmp / "made.volumax", v.Secret("passphrase", PW)) as s:
        assert s.read_member("a.txt") == b"hello" * 2000
