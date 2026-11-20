"""The web's module boundaries, read from the sources (docs/architecture/web.md).

app/web is static ES modules with no build step, so nothing else stops one feature from reaching
into another. The rules:

1. A module in features/<name>/ imports only its own folder and shared/.
2. shared/ imports nothing outside shared/.
3. main.js, the composition root, is the only module that imports features, and only their
   index.js; every feature has an index.js that exports mount(), and main.js mounts each one.
4. Every import is a relative specifier naming a file in app/web, spelled with its exact case.
5. Every emit() and subscribe() names an event declared in shared/events.js as EV.<name>, and
   every declared event has a sender and a listener.
6. Each stylesheet is linked once from index.html, the shared styles before any feature's.

Standard library only: it parses import and export-from specifiers with regular expressions and
fails closed when a line starting with `import` is one it could not parse.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
NOT_SOURCE = {"vendor", "fixtures", "tools"}

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)
# Static imports and re-exports start a line; their clause may span lines but holds no quote.
FROM = re.compile(
    r"^(?P<kw>import|export)\b[^;'\"]*?\bfrom\s*(['\"])(?P<spec>[^'\"]+)\2", re.MULTILINE
)
SIDE_EFFECT = re.compile(r"^import\s*(['\"])(?P<spec>[^'\"]+)\1", re.MULTILINE)
IMPORT_LINE = re.compile(r"^import\b(?!\s*\()", re.MULTILINE)
DYNAMIC = re.compile(r"\bimport\s*\(\s*(?:(['\"])(?P<spec>[^'\"]+)\1\s*\))?")
CALL = re.compile(r"(?<![\w$])(?P<def>function\s+)?(?P<fn>emit|subscribe)\s*\(\s*(?P<arg>[^,)]*)")
EV_BLOCK = re.compile(r"export const EV = Object\.freeze\(\{(?P<body>.*?)\}\);", re.DOTALL)
EV_ENTRY = re.compile(r"^\s*(?P<key>[A-Za-z_$][\w$]*)\s*:\s*'(?P<name>[^']+)'", re.MULTILINE)
STYLESHEET = re.compile(r"<link\s+rel=\"stylesheet\"\s+href=\"(?P<href>[^\"]+)\"")
MODULE_SCRIPT = re.compile(r"<script\b[^>]*\btype=\"module\"[^>]*\bsrc=\"(?P<src>[^\"]+)\"")
MOUNT = re.compile(
    r"^export\s+(?:async\s+)?function\s+mount\s*\(|^export\s+const\s+mount\s*=", re.MULTILINE
)


def rel(path: Path) -> str:
    return path.relative_to(WEB).as_posix()


def code_of(path: Path) -> str:
    """The module's text without its comments, so prose and JSDoc types are not read as code."""
    return LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", path.read_text(encoding="utf-8")))


@cache
def modules() -> tuple[Path, ...]:
    found = sorted(p for p in WEB.rglob("*.js") if p.relative_to(WEB).parts[0] not in NOT_SOURCE)
    assert WEB / "main.js" in found and len(found) > 10, f"no web sources under {WEB}"
    return tuple(found)


@cache
def features() -> tuple[str, ...]:
    names = tuple(sorted(p.name for p in (WEB / "features").iterdir() if p.is_dir()))
    assert names, "no feature folders"
    return names


def area(path: Path) -> str:
    """'root', 'shared', 'feature:<name>' or 'other' for a file under app/web."""
    parts = path.relative_to(WEB).parts
    if parts == ("main.js",):
        return "root"
    if parts[0] == "shared":
        return "shared"
    if parts[0] == "features" and len(parts) > 2:
        return f"feature:{parts[1]}"
    return "other"


def exact_case(path: Path) -> bool:
    """True when every part of path, below app/web, is spelled as on disk (servers are
    case-sensitive even where this checkout's file system is not)."""
    here = WEB
    for part in path.relative_to(WEB).parts:
        if part not in {p.name for p in here.iterdir()}:
            return False
        here = here / part
    return True


@cache
def imports() -> dict[Path, tuple[tuple[str, Path | None], ...]]:
    """Each module's import and export-from specifiers, with the file each names (None when the
    specifier is not relative or names no file in app/web)."""
    table = {}
    for path in modules():
        code = code_of(path)
        froms = list(FROM.finditer(code))
        bare = list(SIDE_EFFECT.finditer(code))
        parsed = sum(m["kw"] == "import" for m in froms) + len(bare)
        assert parsed == len(IMPORT_LINE.findall(code)), (
            f"{rel(path)}: an import the test cannot parse"
        )
        specs = [m["spec"] for m in froms + bare]
        for m in DYNAMIC.finditer(code):
            assert m["spec"], (
                f"{rel(path)}: import() of a computed specifier, which this test cannot follow"
            )
            specs.append(m["spec"])
        out = []
        for spec in specs:
            target = None
            if spec.startswith(("./", "../")):
                cand = (path.parent / spec).resolve()
                if cand.is_file() and cand.is_relative_to(WEB) and exact_case(cand):
                    target = cand
            out.append((spec, target))
        table[path] = tuple(out)
    return table


@cache
def declared_events() -> dict[str, str]:
    block = EV_BLOCK.search((WEB / "shared" / "events.js").read_text(encoding="utf-8"))
    assert block, "shared/events.js has no `export const EV = Object.freeze({...});`"
    entries = [(m["key"], m["name"]) for m in EV_ENTRY.finditer(block["body"])]
    assert entries, "shared/events.js declares no events"
    return dict(entries)


def test_every_import_resolves_to_a_file_in_the_web():
    bad = [
        f"{rel(p)}: '{spec}'"
        for p, edges in imports().items()
        for spec, target in edges
        if target is None
    ]
    assert not bad, (
        "imports that are not relative or name no file (with this exact case):\n" + "\n".join(bad)
    )
    assert sum(len(e) for e in imports().values()) > 50, "suspiciously few imports parsed"


def test_features_import_only_their_own_folder_and_shared():
    bad = []
    for path, edges in imports().items():
        src = area(path)
        if not src.startswith("feature:"):
            continue
        for spec, target in edges:
            if target is not None and area(target) not in (src, "shared"):
                bad.append(f"{rel(path)} imports {rel(target)}")
    assert not bad, (
        "features talk through shared/events.js, never by importing each other:\n" + "\n".join(bad)
    )


def test_shared_imports_nothing_outside_shared():
    bad = [
        f"{rel(path)} imports {rel(target)}"
        for path, edges in imports().items()
        if area(path) == "shared"
        for _, target in edges
        if target is not None and area(target) != "shared"
    ]
    assert not bad, "shared/ must not depend on features or the root:\n" + "\n".join(bad)


def test_every_module_lives_in_shared_a_feature_or_the_root():
    bad = [rel(p) for p in modules() if area(p) == "other"]
    assert not bad, "modules outside main.js, shared/ and features/<name>/:\n" + "\n".join(bad)


def test_only_the_root_imports_features_and_mounts_each_one():
    root = WEB / "main.js"
    reached = set()
    for _, target in imports()[root]:
        if target is not None and area(target).startswith("feature:"):
            assert target.name == "index.js", (
                f"main.js imports {rel(target)}, not the feature's index.js"
            )
            reached.add(target.parent.name)
    assert reached == set(features()), (
        f"features main.js does not mount: {sorted(set(features()) - reached)}"
    )
    code = code_of(root)
    imported = re.findall(
        r"^import \* as (\w+) from '\./features/[^']+/index\.js'", code, re.MULTILINE
    )
    assert len(imported) == len(features()), "main.js imports each feature as a namespace"
    listed = re.search(r"const FEATURES = \[(?P<list>[^\]]*)\]", code)
    assert listed, "main.js has no FEATURES list"
    mounted = {n.strip() for n in listed["list"].split(",")}
    missing = sorted(n for n in imported if n not in mounted)
    assert not missing, f"imported in main.js but not in FEATURES: {missing}"
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert MODULE_SCRIPT.findall(html) == ["main.js"], (
        "index.html must load main.js as its only module"
    )


def test_every_feature_has_an_index_that_exports_mount():
    bad = [
        f
        for f in features()
        if not (WEB / "features" / f / "index.js").is_file()
        or not MOUNT.search(code_of(WEB / "features" / f / "index.js"))
    ]
    assert not bad, f"features without index.js exporting mount(): {bad}"


def test_events_are_declared_in_shared_events_and_all_used():
    declared = declared_events()
    assert len(set(declared.values())) == len(declared), "two EV keys share an event name"
    sent, heard, bad = set(), set(), []
    for path in modules():
        for m in CALL.finditer(code_of(path)):
            if m["def"]:
                continue
            arg = m["arg"].strip()
            key = arg[3:] if arg.startswith("EV.") else None
            if key is None or key not in declared:
                bad.append(f"{rel(path)}: {m['fn']}({arg})")
                continue
            (sent if m["fn"] == "emit" else heard).add(key)
    assert not bad, (
        "emit()/subscribe() must name an EV.<key> declared in shared/events.js:\n" + "\n".join(bad)
    )
    assert sent and heard, "no emit() or subscribe() calls found"
    assert not set(declared) - sent, f"declared but never emitted: {sorted(set(declared) - sent)}"
    assert not set(declared) - heard, (
        f"declared but nobody subscribes: {sorted(set(declared) - heard)}"
    )


def test_each_stylesheet_is_linked_once_shared_styles_first():
    hrefs = STYLESHEET.findall((WEB / "index.html").read_text(encoding="utf-8"))
    on_disk = sorted(
        rel(p) for p in WEB.rglob("*.css") if p.relative_to(WEB).parts[0] not in NOT_SOURCE
    )
    assert sorted(hrefs) == on_disk, f"linked {sorted(hrefs)}\non disk {on_disk}"
    places = [
        h.split("/")[0] + ("/styles" if h.startswith("shared/styles/") else "") for h in hrefs
    ]
    assert set(places) <= {"shared/styles", "features"}, (
        f"stylesheets outside shared/styles and features: {hrefs}"
    )
    first_feature = places.index("features")
    assert all(p == "features" for p in places[first_feature:]), (
        "a shared stylesheet is linked after a feature's"
    )
    for h in hrefs:
        parts = h.split("/")
        if parts[0] == "features":
            assert len(parts) == 3, f"{h}: a feature's stylesheet sits in its own folder"
