"""The server's import boundaries, read from its source with ast, so nothing is imported to check
them (docs/architecture/server.md explains the layout they keep):

1. a module under features/<a>, its tests included, imports from dnapp only dnapp.core and
   dnapp.features.<a>: never another feature, and never main.py, which wires them all;
2. only core/package imports datanuggets or datanuggets_flow;
3. core imports no feature, and not main.py.

Relative imports are resolved, and importlib.import_module("...") or __import__("...") with a
literal name counts as an import."""

from __future__ import annotations

import ast
from pathlib import Path

DNAPP = Path(__file__).resolve().parents[2] / "server" / "dnapp"
FEATURES = DNAPP / "features"
CORE = DNAPP / "core"
PACKAGE = CORE / "package"
PACKAGES = ("datanuggets", "datanuggets_flow")  # the library and the flow package built on it


def package_of(path: Path) -> list[str]:
    """The package a file's relative imports start from: its folder, for a module and for an
    __init__.py alike."""
    return ["dnapp", *path.relative_to(DNAPP).parent.parts]


def imports(path: Path) -> list[tuple[int, str]]:
    """(line, absolute module) for each import in path; `from m import n` yields m and m.n,
    since n may be a submodule."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = package_of(path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            found.append((node.lineno, mod))
            found += [(node.lineno, f"{mod}.{a.name}") for a in node.names if a.name != "*"]
        elif isinstance(node, ast.Call) and node.args:
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            arg = node.args[0]
            if name in ("import_module", "__import__") and isinstance(arg, ast.Constant):
                found.append((node.lineno, str(arg.value)))
    return found


def sources(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def under(mod: str, prefix: str) -> bool:
    return mod == prefix or mod.startswith(prefix + ".")


def where(path: Path, line: int, mod: str) -> str:
    return f"{path.relative_to(DNAPP).as_posix()}:{line} imports {mod}"


def test_a_feature_imports_only_core_and_itself():
    features = sorted(p for p in FEATURES.iterdir() if (p / "__init__.py").is_file())
    assert len(features) >= 13, [f.name for f in features]
    seen, bad = 0, []
    for feature in features:
        own = f"dnapp.features.{feature.name}"
        for path in sources(feature):
            for line, mod in imports(path):
                if not under(mod, "dnapp"):
                    continue
                seen += 1
                if not (under(mod, "dnapp.core") or under(mod, own)):
                    bad.append(where(path, line, mod))
    assert seen > 50, seen  # the scan saw the features' dnapp imports at all
    assert not bad, "a feature reaches past core and its own folder:\n" + "\n".join(bad)


def test_only_core_package_imports_the_two_packages():
    """datanuggets_flow is a package of its own, not a submodule of datanuggets, so each is
    looked for by name."""
    seen, bad = dict.fromkeys(PACKAGES, 0), []
    for path in sources(DNAPP):
        for line, mod in imports(path):
            for name in PACKAGES:
                if under(mod, name):
                    if PACKAGE in path.parents:
                        seen[name] += 1
                    else:
                        bad.append(where(path, line, mod))
    assert all(seen.values()), seen  # core/package imports both, so the scan would see a stray one
    assert not bad, "only core/package may import these packages:\n" + "\n".join(bad)


def test_core_imports_no_feature():
    seen, bad = 0, []
    for path in sources(CORE):
        for line, mod in imports(path):
            if under(mod, "dnapp"):
                seen += 1
                if under(mod, "dnapp.features") or under(mod, "dnapp.main"):
                    bad.append(where(path, line, mod))
    assert seen > 10, seen
    assert not bad, "core must not depend on a feature:\n" + "\n".join(bad)


def test_main_wires_every_feature():
    """The other side of rule 1: main.py is where the features meet, so it imports each."""
    wired = {
        mod.split(".")[2]
        for _, mod in imports(DNAPP / "main.py")
        if under(mod, "dnapp.features") and mod.count(".") >= 2
    }
    on_disk = {p.name for p in FEATURES.iterdir() if (p / "__init__.py").is_file()}
    assert on_disk <= wired, sorted(on_disk - wired)
