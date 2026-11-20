"""app/scripts/list_licenses.py: the Docker build runs it to write the license of every Python
package in the image to a file the image keeps."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from email.message import Message
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "list_licenses.py"


@pytest.fixture(scope="module")
def ll():
    spec = importlib.util.spec_from_file_location("list_licenses", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # its dataclass looks its own module up while it is defined
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        del sys.modules[spec.name]


def meta(**fields: str | list[str]) -> Message:
    m = Message()
    for key, value in fields.items():
        for v in value if isinstance(value, list) else [value]:
            m[key.replace("_", "-")] = v
    return m


BSD = "License :: OSI Approved :: BSD License"
LONG = "BSD 3-Clause License\n\nCopyright (c) 2019, someone\nAll rights reserved."


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"License_Expression": "MIT", "License": "BSD", "Classifier": [BSD]}, "MIT"),
        ({"License": "Apache-2.0", "Classifier": [BSD]}, "Apache-2.0"),
        ({"License": LONG, "Classifier": [BSD, "Programming Language :: Python"]}, "BSD License"),
        ({"License": LONG}, "BSD 3-Clause License"),
        ({"License": "UNKNOWN"}, None),
        ({}, None),
    ],
)
def test_the_declared_license_is_the_shortest_honest_name(ll, fields, expected):
    assert ll.declared_license(meta(**fields)) == expected


def test_every_installed_package_is_listed_once_with_a_license_or_its_files(ll):
    entries = ll.collect()
    names = [e.name.lower() for e in entries]
    assert names == sorted(set(names))
    assert all(e.license or e.files for e in entries)
    by = {e.name.lower(): e for e in entries}
    assert by["python-multipart"].license == "Apache-2.0"
    assert by["datanuggets-app"].license == "GPL-2.0-only"
    assert "\n" not in by["flowio"].license
    assert any(Path(f).name == "LICENSE" and ".dist-info/" in f for f in by["datanuggets"].files)


def test_strict_refuses_a_package_with_no_license_and_no_license_file(ll, monkeypatch, tmp_path):
    bare = ll.Entry(name="mystery", version="1.0", license=None, files=())
    monkeypatch.setattr(ll, "collect", lambda: [bare])
    out = tmp_path / "licenses.txt"
    assert ll.main(["--out", str(out)]) == 0
    assert "mystery 1.0" in out.read_text(encoding="utf-8")
    assert ll.main(["--strict", "--out", str(out)]) == 1


def test_the_build_command_writes_the_list(tmp_path):
    out = tmp_path / "python-package-licenses.txt"
    run = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--strict", "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    text = out.read_text(encoding="utf-8")
    assert re.search(r"^python-multipart \S+\n  license: Apache-2\.0$", text, re.MULTILINE)
    assert re.search(r"^datanuggets-app \S+\n  license: GPL-2\.0-only$", text, re.MULTILINE)
    assert "site-packages" in text
