"""CLI parsing, output planning and single-instance merging. Both Qt stacks."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import volumax  # noqa: F401
from volumax import cli


def test_parse_variants():
    assert cli.parse([]).kind == ""
    assert cli.parse(["a.7z"]).kind == cli.OPEN
    c = cli.parse(["--extract-here", "a.zip", "b.zip"])
    assert c.kind == cli.EXTRACT_HERE and [p.name for p in c.paths] == ["a.zip", "b.zip"]
    c = cli.parse(["--add-to", "zip", "x", "y"])
    assert (c.kind, c.fmt, len(c.paths)) == (cli.ADD_TO, "zip", 2)
    assert cli.parse(["--add-to", "rar", "x"]).kind == ""        # unsupported -> ignored
    assert cli.parse(["--bogus-flag"]).kind == ""                 # never fatal
    assert cli.parse(["--add", "C:\\Users\\a b\\file name.txt"]).paths[0].name.endswith("file name.txt")


@pytest.mark.parametrize("name,stem", [
    ("photos.tar.gz", "photos"), ("a.b.7z", "a.b"), ("x.zip", "x"),
    ("backup.tar.xz", "backup"), ("big.7z.001", "big"), ("NOEXT", "NOEXT"),
])
def test_archive_stem(name, stem):
    assert cli.archive_stem(name) == stem


def test_extract_destination_is_smart_and_safe(tmp_path: Path):
    arc = tmp_path / "pack.7z"
    arc.write_bytes(b"x")
    # one top-level folder -> next to the archive
    dest, _ = cli.plan_extract_destination(arc, ["proj/a.txt", "proj/sub/b.txt"], cli.EXTRACT_HERE)
    assert dest == tmp_path
    # many top-level items -> own folder, avoids a mess
    dest, _ = cli.plan_extract_destination(arc, ["a.txt", "b.txt"], cli.EXTRACT_HERE)
    assert dest == tmp_path / "pack"
    # target already exists -> never merge/overwrite silently
    (tmp_path / "proj").mkdir()
    dest, _ = cli.plan_extract_destination(arc, ["proj/a.txt"], cli.EXTRACT_HERE)
    assert dest == tmp_path / "pack"
    (tmp_path / "pack").mkdir()
    dest, _ = cli.plan_extract_destination(arc, ["a.txt", "b.txt"], cli.EXTRACT_FOLDER)
    assert dest == tmp_path / "pack (1)"


def test_quick_archive_naming(tmp_path: Path):
    f = tmp_path / "report.docx"
    f.write_text("x")
    assert cli.plan_quick_archive("7z", [f]) == tmp_path / "report.7z"
    (tmp_path / "report.7z").write_text("taken")
    assert cli.plan_quick_archive("7z", [f]) == tmp_path / "report (1).7z"
    g = tmp_path / "other.txt"
    g.write_text("y")
    assert cli.plan_quick_archive("zip", [f, g]) == tmp_path / f"{tmp_path.name}.zip"


def test_single_instance_merges_multiselect(tmp_path: Path):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from volumax.single_instance import COLLECT_MS, InstanceServer, send_to_running

    got = []
    name = f"VOLUMAX-test-{os.getpid()}"
    srv = InstanceServer(got.append, name=name)
    assert srv.listen()
    for i in range(5):  # Explorer launches one process per selected file
        assert send_to_running(cli.Command(cli.ADD_TO, [tmp_path / f"f{i}.txt"], "7z"), name=name)
    end = time.monotonic() + 5
    while not got and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    time.sleep(COLLECT_MS / 1000 + 0.2)
    app.processEvents()
    srv.close()
    assert len(got) == 1, "5 forwarded launches must become ONE command"
    assert len(got[0].paths) == 5
    assert not send_to_running(cli.Command(cli.OPEN, [tmp_path]), name=name)   # server closed
