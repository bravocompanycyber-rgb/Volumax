import random
import pytest
from pathlib import Path
from volumax import smallpack as sp

pytestmark = pytest.mark.skipif(not sp.available(), reason="zstandard not installed")


def _corpus(d: Path, n: int, seed=1):
    random.seed(seed); d.mkdir()
    for i in range(n):
        lines = [f'10.0.{random.randint(0,9)}.{random.randint(1,99)} "GET /api/v1/{random.choice(["a","b","c"])}" {random.choice([200,404])}' for _ in range(random.randint(5, 40))]
        (d / f"f{i}.log").write_text("\n".join(lines))


def test_roundtrip_and_gate_small(tmp_path):
    src = tmp_path / "logs"; _corpus(src, 30)
    r = sp.create_pack([src], tmp_path / "a.vxsp")
    assert r.success and not r.used_dictionary        # tiny set: dictionary does not pay -> not used
    e = sp.extract_pack(tmp_path / "a.vxsp", tmp_path / "out")
    assert e.success
    for f in src.iterdir():
        assert (tmp_path / "out" / "logs" / f.name).read_bytes() == f.read_bytes()


def test_dictionary_used_when_it_pays(tmp_path):
    src = tmp_path / "logs"; _corpus(src, 2500)
    r = sp.create_pack([src], tmp_path / "b.vxsp")
    assert r.success and r.used_dictionary
    assert sp.extract_pack(tmp_path / "b.vxsp", tmp_path / "o").success


def test_corrupt_and_traversal_rejected(tmp_path):
    bad = tmp_path / "bad.vxsp"; bad.write_bytes(b"nope")
    assert not sp.extract_pack(bad, tmp_path / "x").success
    assert not sp.extract_pack(tmp_path / "missing.vxsp", tmp_path / "x").success
    with pytest.raises(sp.SmallPackError):
        sp._safe_name("../evil")
    with pytest.raises(sp.SmallPackError):
        sp._safe_name("/abs")
