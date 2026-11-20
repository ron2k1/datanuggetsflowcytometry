"""The web's /config and /health fixtures are what their generator, fixturegen/config.py, writes
today: a new setting in ClusterSettings or GateSettings reaches the generator by itself, and this
fails until the checked-in fixtures are rebuilt with it. And no fixture says where it was built."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "web" / "tools"
FIXTURES = TOOLS.parent / "fixtures"


@pytest.mark.parametrize("name", ["GET__config.json", "GET__config.local.json", "GET__health.json"])
def test_config_fixtures_match_their_generator(tmp_path, monkeypatch, name):
    monkeypatch.syspath_prepend(str(TOOLS))
    from fixturegen.config import write_config

    write_config(tmp_path)
    made = json.loads((tmp_path / name).read_text(encoding="utf-8"))
    assert json.loads((FIXTURES / name).read_text(encoding="utf-8")) == made


def test_the_generator_takes_the_version_the_server_reports(tmp_path, monkeypatch):
    """/config's package_version names the image and the release tag, so the generator writes
    the flow package's version, as the server does, and not the library's."""
    monkeypatch.syspath_prepend(str(TOOLS))
    from dnapp.core.package import runtime
    from fixturegen.config import write_config

    versions = {"datanuggets-flow": "9.9.9", "datanuggets": "1.1.1"}
    monkeypatch.setattr(runtime, "version", versions.__getitem__)
    write_config(tmp_path)
    made = json.loads((tmp_path / "GET__config.json").read_text(encoding="utf-8"))
    assert made["package_version"] == "9.9.9"
    assert made["docker_command"].endswith("ghcr.io/ron2k1/datanuggets-flow:9.9.9")


def test_config_only_rewrites_just_the_version_bearing_fixtures(tmp_path):
    """A version bump changes only what write_config writes, so build_fixtures.py --config-only
    rewrites those three files, needs none of the demo runs a full build reads, and leaves the
    other fixtures where they are."""
    out = tmp_path / "fixtures"
    out.mkdir()
    (out / "GET__runs.json").write_text("{}", encoding="utf-8")
    command = [sys.executable, str(TOOLS / "build_fixtures.py"), "--config-only", "--out", str(out)]
    subprocess.run(command, check=True, capture_output=True, timeout=300)
    names = ["GET__config.json", "GET__config.local.json", "GET__health.json"]
    assert sorted(p.name for p in out.iterdir()) == sorted([*names, "GET__runs.json"])
    assert (out / "GET__runs.json").read_text(encoding="utf-8") == "{}"
    for name in names:
        made = json.loads((out / name).read_text(encoding="utf-8"))
        assert json.loads((FIXTURES / name).read_text(encoding="utf-8")) == made, name
    # a full build still needs its inputs
    full = subprocess.run(
        command[:2] + ["--out", str(out)], check=False, capture_output=True, text=True, timeout=300
    )
    assert full.returncode == 2 and "--mockup" in full.stderr


@pytest.fixture
def common(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    from fixturegen import common

    return common


def test_no_committed_fixture_says_where_it_was_built(common):
    texts = [p for p in FIXTURES.rglob("*") if p.suffix in (".json", ".csv")]
    assert len(texts) > 60
    found = {p.relative_to(FIXTURES).as_posix(): common.leak(p.read_text("utf-8")) for p in texts}
    assert {k: v for k, v in found.items() if v} == {}


def test_the_leak_check_needs_no_private_value(common, monkeypatch):
    """The check finds home folders, drive paths, a path made into a folder name, the running
    user's name and digested words, and says only which kind it found."""
    for text, kind in [
        (json.dumps({"p": "C:\\Users\\someone\\data\\x.fcs"}), "a home-folder path"),
        ('"/home/someone/x.csv"', "a home-folder path"),
        ('"/Users/someone/x.csv"', "a home-folder path"),
        ('"D:/data/x.csv"', "a drive path"),
        (json.dumps("E:\\x.csv"), "a drive path"),
        ('"projects/E--Users-someone/x"', "a path made into a folder name"),
    ]:
        assert common.leak(text) == kind, text
    monkeypatch.setattr(common, "HOME_NAME", "someone")
    assert common.leak('{"op": "Someone"}') == "the user's own name"
    word = hashlib.sha256(b"zqxlab").hexdigest()
    monkeypatch.setattr(common, "DENY", frozenset({word}))
    assert common.leak('"bigZqxlab-ab"') == f"a denied word (sha256 {word[:12]})"
    for clean in [
        '{"url": "https://doi.org/10.5281/zenodo.22079206"}',
        '{"mode": "local", "name": "190.fcs", "note": "Files stay on this computer."}',
        '{"t": "2026-10-01T12:00:00Z", "ratio": "3:1"}',
    ]:
        assert common.leak(clean) is None, clean
    with pytest.raises(SystemExit, match="a drive path") as e:
        common.refuse_leaks('"D:/data/x.csv"', "x.json")
    assert "data" not in str(e.value)
