"""Both locks, uv.lock and app/uv.lock, take the library from PyPI: the datanuggets that
pyproject.toml requires is the published one, never a path or a git checkout. The sdist ships no
lock, so there the test skips."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCKS = [ROOT / "uv.lock", ROOT / "app" / "uv.lock"]
PYPI = {"registry": "https://pypi.org/simple"}


@pytest.mark.parametrize("lock", LOCKS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_the_lock_takes_datanuggets_from_pypi(lock):
    if not lock.is_file():
        pytest.skip(f"{lock.name} isn't here, as in the sdist")
    with lock.open("rb") as f:
        packages = tomllib.load(f)["package"]
    found = [p for p in packages if p["name"] == "datanuggets"]
    assert len(found) == 1, found  # one entry, so a second source can't hide behind the first
    assert found[0]["source"] == PYPI
    # and the flow is the checkout's own, so the test reads the lock it means to
    flow = [p for p in packages if p["name"] == "datanuggets-flow"]
    assert len(flow) == 1 and "editable" in flow[0]["source"], flow
