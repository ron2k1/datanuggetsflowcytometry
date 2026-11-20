"""List the license of every Python package installed for the interpreter that runs this script.

The Docker build runs it with the image's own Python after the last install, and the image keeps
the list as /app/python-package-licenses.txt. Each package gets its name, version and license as
the package itself declares it: the SPDX License-Expression when there is one, else a License
field that fits on one short line, else its License classifiers. Then come the paths of the
license files it ships, relative to the site-packages folder named at the top.

With --strict the exit code is 1 when a package declares no license and ships no license file,
so the image build stops instead of bundling a package nobody has checked.

Standard library only.

    python -I app/scripts/list_licenses.py                          # print the list
    python -I app/scripts/list_licenses.py --strict --out FILE      # what the Docker build runs
"""

from __future__ import annotations

import argparse
import sys
import sysconfig
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

SHORT_FIELD = 60  # a License field longer than this, or on several lines, is the license text
CLASSIFIER_PREFIX = "License :: "
LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE")  # when no License-File is declared

HEADER = """\
Python packages in this image and the licenses they declare.
Written at build time by app/scripts/list_licenses.py. The full license texts ship with each
package, at the paths listed under it, relative to
  {site}
"""
PYTHON_LICENSE = "The Python interpreter's own license is in {path}"
DEBIAN_DOCS = Path("/usr/share/doc")
DEBIAN_LICENSES = "Each Debian package's license is in /usr/share/doc/<package>/copyright"


@dataclass(frozen=True)
class Entry:
    name: str
    version: str
    license: str | None
    files: tuple[str, ...]


def declared_license(meta) -> str | None:
    """The shortest name the package gives its own license, or None when it gives none."""
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    field = (meta.get("License") or "").strip()
    if field and "\n" not in field and len(field) <= SHORT_FIELD and field != "UNKNOWN":
        return field
    classifiers = [
        c.rsplit(" :: ", 1)[-1]
        for c in meta.get_all("Classifier") or []
        if c.startswith(CLASSIFIER_PREFIX)
    ]
    if classifiers:
        return ", ".join(classifiers)
    first = field.splitlines()[0].strip() if field else ""
    return first if first and first != "UNKNOWN" else None


def license_files(dist: metadata.Distribution) -> tuple[str, ...]:
    """The license files the package ships in its .dist-info folder."""
    declared = {Path(p).as_posix() for p in dist.metadata.get_all("License-File") or []}
    found = []
    for f in dist.files or []:
        parts = f.parts
        if not parts or not parts[0].endswith(".dist-info"):
            continue
        inside = "/".join(parts[1:]).removeprefix("licenses/")
        wanted = inside in declared if declared else f.name.upper().startswith(LICENSE_NAMES)
        if wanted:
            found.append(f.as_posix())
    return tuple(sorted(found))


def collect() -> list[Entry]:
    entries: dict[str, Entry] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name or name.lower() in entries:
            continue  # the first copy on sys.path is the one Python imports
        entries[name.lower()] = Entry(
            name, dist.version, declared_license(dist.metadata), license_files(dist)
        )
    return [entries[k] for k in sorted(entries)]


def site_folder() -> str:
    for dist in metadata.distributions():
        return str(dist.locate_file(""))
    return "(no packages installed)"


def other_licenses() -> list[str]:
    """Where the interpreter's and the operating system's licenses are, when they are there."""
    found = []
    python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if python_license.is_file():
        found.append(PYTHON_LICENSE.format(path=python_license.as_posix()))
    if DEBIAN_DOCS.is_dir():
        found.append(DEBIAN_LICENSES)
    return found


def render(entries: list[Entry], site: str) -> str:
    lines = [HEADER.format(site=site) + "".join(f"{line}.\n" for line in other_licenses())]
    for e in entries:
        lines.append(f"{e.name} {e.version}")
        lines.append(f"  license: {e.license or 'not declared'}")
        lines.extend(f"  file: {f}" for f in e.files)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="write the list here instead of printing it")
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 for a package with no license and no file"
    )
    args = parser.parse_args(argv)
    entries = collect()
    text = render(entries, site_folder())
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    bare = [f"{e.name} {e.version}" for e in entries if not e.license and not e.files]
    for b in bare:
        print(f"list_licenses: {b} declares no license and ships no license file", file=sys.stderr)
    return 1 if args.strict and bare else 0


if __name__ == "__main__":
    sys.exit(main())
