"""The version is written once, in pyproject.toml, and the package reads it from its metadata. The
datanuggets-flow command is the one console script, pick's main."""

import re
import tomllib
from importlib.metadata import entry_points, version
from pathlib import Path

import datanuggets_flow

# tests/ sits beside pyproject.toml in a clone and in the sdist
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_matches_pyproject():
    with PYPROJECT.open("rb") as f:
        want = tomllib.load(f)["project"]["version"]
    assert datanuggets_flow.__version__ == version("datanuggets-flow") == want


def test_init_holds_no_version_literal():
    # a second copy would agree until the first release that forgets to bump it
    source = Path(datanuggets_flow.__file__).read_text(encoding="utf-8")
    assert not re.search(r"__version__\s*=\s*['\"]", source)


def test_the_command_is_picks_main():
    found = entry_points(group="console_scripts", name="datanuggets-flow")
    assert [e.value for e in found] == ["datanuggets_flow.pick:main"]
