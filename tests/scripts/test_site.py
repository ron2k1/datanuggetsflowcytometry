"""site/index.html against pyproject.toml and docs/images. The page is published by
.github/workflows/pages.yml and isn't in the sdist, which leaves this folder out, so these tests
run only from a clone."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = r"(\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?)"


def _page():
    return (ROOT / "site" / "index.html").read_text(encoding="utf-8")


def test_page_names_the_released_version():
    """The pip pin, the image tag and the alpha label on the page must name the version that
    pyproject.toml releases, or the page sends a reader to a release that isn't this one."""
    with (ROOT / "pyproject.toml").open("rb") as f:
        want = tomllib.load(f)["project"]["version"]
    page = _page()
    pins = re.findall(r"datanuggets-flow==" + VERSION, page)
    tags = re.findall(r"ghcr\.io/ron2k1/datanuggets-flow:" + VERSION, page)
    labels = re.findall(r"Research alpha\D{0,20}" + VERSION, page)
    assert pins, "the page shows no pip pin"
    assert tags, "the page shows no image tag"
    assert labels, "the page shows no alpha label"
    assert set(pins + tags + labels) == {want}


def test_page_files_exist():
    """pages.yml copies docs/images/*.png next to the page as images/, so every picture the page
    names has to be in docs/images, and its stylesheet has to be in site/."""
    page = _page()
    pictures = set(re.findall(r"images/([\w.-]+\.png)", page))
    assert pictures, "the page shows no screenshot"
    missing = sorted(name for name in pictures if not (ROOT / "docs" / "images" / name).is_file())
    assert not missing, missing
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', page)
    assert sheets, "the page links no stylesheet"
    assert all((ROOT / "site" / sheet).is_file() for sheet in sheets)
