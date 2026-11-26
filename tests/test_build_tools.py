"""The build orchestrator's own logic (naming, PE checks, ISCC discovery, error paths)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_all", ROOT / "tools" / "build_all.py")
ba = importlib.util.module_from_spec(_spec)
sys.modules["build_all"] = ba  # @dataclass looks its module up here
_spec.loader.exec_module(ba)  # type: ignore[union-attr]


def test_three_targets_with_expected_stacks():
    assert set(ba.TARGETS) == {"modern-x64", "legacy-x64", "legacy-x86"}
    assert ba.TARGETS["modern-x64"].flavor == "modern" and ba.TARGETS["modern-x64"].arch == "x64"
    for k in ("legacy-x64", "legacy-x86"):
        assert ba.TARGETS[k].python_versions == ("3.8",)        # last Python that runs on Windows 8
        assert ba.TARGETS[k].requirements.endswith("legacy.txt")
    assert ba.TARGETS["legacy-x86"].arch == "x86"


def test_artifact_names_are_unique_and_labeled():
    names = set()
    for t in ba.TARGETS.values():
        for kind in ("Setup", "Portable"):
            n = ba.artifact_name(kind, "1.2.3", t)
            assert n.startswith("VOLUMAX-1.2.3-" + kind + "-")
            assert n.endswith(".exe" if kind == "Setup" else ".zip")
            assert " " not in n
            names.add(n)
    assert len(names) == 6
    assert "VOLUMAX-1.2.3-Setup-Modern-Win10-11-x64.exe" in names
    assert "VOLUMAX-1.2.3-Setup-Legacy-Win8-8.1-x86.exe" in names


def test_version_reading_and_validation():
    assert re.fullmatch(r"\d+\.\d+\.\d+", ba.read_version(None))
    assert ba.read_version("9.8.7") == "9.8.7"
    with pytest.raises(ba.BuildError):
        ba.read_version("1.2")


def test_version_info_resource():
    txt = ba.version_info_text("1.2.3", ba.TARGETS["legacy-x86"])
    assert "filevers=(1, 2, 3, 0)" in txt and "32-bit" in txt and "Bravo Projects" in txt
    compile(txt.split("\n", 1)[1], "version", "eval")  # valid Python expression for PyInstaller


def test_pe_machine_detects_bundled_engine_is_x64():
    exe = ROOT / "engines" / "7zip" / "7z.exe"
    assert ba.pe_machine(exe) == "x64"
    assert ba.pe_machine(ROOT / "README.md") == "unknown"


def test_pe_machine_x86_and_arm(tmp_path: Path):
    import struct

    def fake(machine: int) -> Path:
        p = tmp_path / f"f{machine:x}.exe"
        data = bytearray(256)
        data[0:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", data, 0x84, machine)
        p.write_bytes(bytes(data))
        return p

    assert ba.pe_machine(fake(0x014C)) == "x86"
    assert ba.pe_machine(fake(0x8664)) == "x64"
    assert ba.pe_machine(fake(0xAA64)) == "arm64"


def test_iscc_discovery(tmp_path: Path, monkeypatch):
    fake = tmp_path / "Inno Setup 7" / "ISCC.exe"
    fake.parent.mkdir()
    fake.write_text("x")
    assert ba.locate_iscc(str(fake)) == fake
    monkeypatch.setenv("ISCC", str(fake))
    assert ba.locate_iscc(None) == fake
    monkeypatch.delenv("ISCC")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "Programs").mkdir()
    shutil_target = tmp_path / "Programs" / "Inno Setup 7"
    fake.parent.rename(shutil_target)
    assert ba.locate_iscc(None) == shutil_target / "ISCC.exe"


def test_engine_hash_pin_is_trust_on_first_use(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ba, "ROOT", tmp_path)
    (tmp_path / "tools").mkdir()
    f = tmp_path / "a.exe"
    f.write_bytes(b"one")
    log = ba.Log(tmp_path / "l.txt", dry=True)
    ba._check_pinned_hash("a.exe", f, log)           # first sight: recorded
    pins = json.loads((tmp_path / "tools" / "engine-hashes.json").read_text())
    assert pins["a.exe"] == ba.sha256(f)
    ba._check_pinned_hash("a.exe", f, log)           # same file: fine
    f.write_bytes(b"tampered")
    with pytest.raises(ba.BuildError, match="pinned"):
        ba._check_pinned_hash("a.exe", f, log)       # changed download: build aborts


def test_engine_architecture_mismatch_is_rejected(tmp_path: Path):
    log = ba.Log(tmp_path / "l.txt", dry=False)
    # x64 engine offered for the 32-bit target must fail the build, not ship a broken package
    with pytest.raises(ba.BuildError, match="needs x86"):
        ba.prepare_engine(ba.TARGETS["legacy-x86"], {"legacy-x86": ROOT / "engines" / "7zip"}, log)
    log.close()


def test_cli_errors_and_list(capsys):
    assert ba.main(["--list"]) == 0
    assert "legacy-x86" in capsys.readouterr().out
    assert ba.main(["--targets", "nonsense", "--dry-run"]) == 2
    assert ba.main(["--engine", "bad", "--dry-run"]) == 2
    assert ba.main(["--version", "x", "--dry-run"]) == 2


def test_dry_run_changes_nothing(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(ba, "BUILD", tmp_path / "build")
    monkeypatch.setattr(ba, "RELEASE", tmp_path / "release")
    assert ba.main(["--dry-run", "--no-installer", "--targets", "modern-x64"]) == 0
    assert not (tmp_path / "build").exists() and not (tmp_path / "release").exists()
    assert "PyInstaller" in capsys.readouterr().out


def test_portable_zip_contents(tmp_path: Path):
    import zipfile

    folder = tmp_path / "VOLUMAX"
    (folder / "_internal").mkdir(parents=True)
    (folder / "VOLUMAX.exe").write_bytes(b"MZ")
    (folder / "_internal" / "x.dll").write_bytes(b"d")
    log = ba.Log(tmp_path / "l.txt", dry=False)
    z = ba.make_portable(ba.TARGETS["legacy-x64"], folder, "1.0.0", tmp_path / "out", log)
    log.close()
    names = zipfile.ZipFile(z).namelist()
    root = "VOLUMAX-1.0.0-Portable-Legacy-Win8-8.1-x64/"
    assert root + "VOLUMAX.exe" in names and root + "portable.flag" in names
    assert root + "_internal/x.dll" in names


def test_installer_script_is_consistent():
    iss = (ROOT / "installer" / "volumax.iss").read_text(encoding="utf-8")
    for needle in ("x64compatible", "x86compatible", "MinVersion=10.0.17763", "PrivilegesRequired=lowest",
                   "ChangesAssociations=yes", "WizardImageFile", "--extract-here", "--add-to 7z", "usPostUninstall"):
        assert needle in iss, needle
    assert "ArchitecturesAllowed=x64\r" not in iss  # deprecated identifier
    # every command registered for Explorer must be a verb the CLI actually parses
    from volumax import cli
    for verb in re.findall(r'--(extract-here|extract-to-folder|add-to|add)\b', iss):
        assert verb in ("extract-here", "extract-to-folder", "add-to", "add")
    assert cli.parse(["--add-to", "7z", "x"]).kind == cli.ADD_TO


def _fake_pe(path, machine: int):
    import struct
    head = bytearray(256)
    head[0:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x80)
    head[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", head, 0x84, machine)
    path.write_bytes(bytes(head))


def test_pe_machine_detects_architectures(tmp_path):
    for machine, name in ((0x8664, "x64"), (0x014C, "x86"), (0xAA64, "arm64")):
        f = tmp_path / f"{name}.dll"
        _fake_pe(f, machine)
        assert ba.pe_machine(f) == name
    (tmp_path / "junk.dll").write_bytes(b"not a pe")
    assert ba.pe_machine(tmp_path / "junk.dll") == "unknown"


def test_engine_smoke_runs_the_real_engine_and_rejects_a_broken_one(tmp_path):
    import os, shutil
    real = shutil.which("7z")
    if real is None or os.name == "nt":
        import pytest
        pytest.skip("needs a runnable 7z on PATH")
    log = ba.Log(tmp_path / "b.log", False)
    ba._engine_smoke(Path(real), log)                       # healthy engine passes
    broken = tmp_path / "7z"
    broken.write_text("#!/bin/sh\necho 'ERROR:\nUnsupported archive type'\nexit 2\n")
    broken.chmod(0o755)
    import pytest
    with pytest.raises(ba.BuildError, match="cannot create"):
        ba._engine_smoke(broken, log)
