"""The flow's boundary with the library. Every Python file of the package, the tests, the app and
the flow benchmarks is read with ast, and its imports of the library (datanuggets and its
submodules; datanuggets_flow is a package of its own) must:

1. name no module with a part starting with "_", the library's private modules;
2. import no name starting with "_" (dunder names such as __version__ are not counted);
3. a. stay inside library_uses.FLOW_USES, b. whose every name resolves in the installed library,
   c. which equals the library's own FLOW_USES where a source for one is given;
4. include the edges in EDGES, so a reader that finds nothing fails instead of passing.

The package root is the imported package's folder, so an sdist run reads the installed wheel. The
other roots are taken from the repo root and skipped where they don't exist, as in the sdist."""

from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path

import pytest

import datanuggets_flow
from library_uses import FLOW_USES

REPO = Path(__file__).resolve().parents[2]
ROOTS = {
    "package": Path(datanuggets_flow.__file__).resolve().parent,
    **{
        name: REPO / name
        for name in ("tests", "app/server", "app/tests", "app/web/tools", "benchmarks/flow")
    },
}
SKIP_DIRS = {".venv", "node_modules", "__pycache__"}
# (file relative to its root, library module, name): one import per root that has any
EDGES = {
    "package": [
        ("figures.py", "datanuggets", "plot"),
        ("_pipeline/clustering.py", "datanuggets", "create_dn"),
        ("livecells.py", "datanuggets.filters", "parse_filter"),
    ],
    "tests": [("flow/test_flow_pipeline.py", "datanuggets", "create_dn")],
    "app/server": [("dnapp/core/package/filters.py", "datanuggets.filters", "parse_filter")],
    "app/web/tools": [("fixturegen/colors.py", "datanuggets.colors", "cluster_colors")],
}


def _library(module: str) -> bool:
    return module == "datanuggets" or module.startswith("datanuggets.")


def _imports(root: Path) -> list[tuple[str, str | None, str, int]]:
    """(module, name, file, line) for each library import under root, file relative to root.
    name is None for a bare import of the module."""
    found = []
    for path in sorted(root.rglob("*.py")):
        if SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if _library(node.module):
                    found += [(node.module, a.name, rel, node.lineno) for a in node.names]
            elif isinstance(node, ast.Import):
                found += [(a.name, None, rel, node.lineno) for a in node.names if _library(a.name)]
    return found


@pytest.fixture(scope="module")
def scan() -> dict[str, list[tuple[str, str | None, str, int]]]:
    return {name: _imports(root) for name, root in ROOTS.items() if root.is_dir()}


def _where(root: str, rel: str, line: int) -> str:
    return f"{rel}:{line}" if root == "package" else f"{root}/{rel}:{line}"


def test_no_private_library_module_is_imported(scan):
    """1."""
    bad = [
        f"{_where(root, rel, line)} {module}"
        for root, found in scan.items()
        for module, _, rel, line in found
        if any(part.startswith("_") for part in module.split("."))
    ]
    assert not bad, bad


def test_no_private_library_name_is_imported(scan):
    """2."""
    bad = [
        f"{_where(root, rel, line)} {module}.{name}"
        for root, found in scan.items()
        for module, name, rel, line in found
        if name and name.startswith("_") and not (name.startswith("__") and name.endswith("__"))
    ]
    assert not bad, bad


def test_every_library_import_is_in_the_contract(scan):
    """3a. A bare import needs its module as a key."""
    bad = []
    for root, found in scan.items():
        for module, name, rel, line in found:
            listed = module in FLOW_USES if name is None else name in FLOW_USES.get(module, ())
            if not listed:
                bad.append(f"{_where(root, rel, line)} {module} {name or '(module)'}")
    assert not bad, bad


def test_every_name_in_the_contract_is_in_the_installed_library():
    """3b. getattr first, then the name as a submodule, so plot, which import datanuggets never
    loads, passes whatever ran before."""
    assert FLOW_USES
    missing = []
    for module, names in sorted(FLOW_USES.items()):
        assert names, module
        mod = importlib.import_module(module)
        for name in sorted(names):
            if hasattr(mod, name):
                continue
            try:
                importlib.import_module(f"{module}.{name}")
            except ImportError:
                missing.append(f"{module}.{name}")
    assert not missing, missing


def _library_uses(path: Path) -> dict | None:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "FLOW_USES" for t in targets):
            return ast.literal_eval(node.value)
    return None


def test_the_copy_equals_the_librarys_own_where_one_is_given():
    """3c. datanuggets 0.1.0a3's tests keep no FLOW_USES, so the copy is the contract and 3b is
    what checks it against the library. DN_LIBRARY_USES may name a library test file that defines
    one, such as a later sdist's tests/test_public_paths.py; the copy must then equal it."""
    source = os.environ.get("DN_LIBRARY_USES")
    if not source:
        pytest.skip(
            "DN_LIBRARY_USES is not set: datanuggets 0.1.0a3 keeps no FLOW_USES, so "
            "library_uses.FLOW_USES is the contract and 3b checks it"
        )
    theirs = _library_uses(Path(source))
    assert theirs is not None, f"DN_LIBRARY_USES names a file with no FLOW_USES: {source}"
    assert FLOW_USES == theirs


def test_the_reader_sees_the_known_edges(scan):
    """4. A required edge in each root that exists fails closed better than a count. app/tests
    and benchmarks/flow have no library import, but are scanned for 1 to 3."""
    assert "package" in scan and "tests" in scan
    for root, edges in EDGES.items():
        if root not in scan:
            continue
        seen = {(rel, module, name) for module, name, rel, _ in scan[root]}
        for edge in edges:
            assert edge in seen, (root, edge)
