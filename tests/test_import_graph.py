"""The package's import graph, read from its source with every import counted: those inside
functions and under TYPE_CHECKING too, since each is an edge a later change can turn into a
load-time one. The graph has no cycles, and only the modules that draw reach matplotlib,
datanuggets_flow.plot or the library's datanuggets.plot, so the numerical core never depends on a
plotting library."""

import ast
from pathlib import Path

import datanuggets

import datanuggets_flow

# The source of the package the tests import: src/datanuggets_flow in a checkout, and the
# installed wheel's when package.yml runs the sdist's tests with src/ deleted
PACKAGE = Path(datanuggets_flow.__file__).resolve().parent
# The installed library's source, read only for its module names, so a library import resolves
# to the module it names
LIBRARY = Path(datanuggets.__file__).resolve().parent

# The modules that draw, or run something that draws: the flow run's figures and the stages that
# save them, and the datanuggets-flow command. No other module may import matplotlib or a plot
# module, directly or through another module.
DRAWS = {
    "datanuggets_flow.figures",
    "datanuggets_flow._pipeline.stages",
    "datanuggets_flow.pipeline",
    "datanuggets_flow.pick",
    "datanuggets_flow._pick.args",
    "datanuggets_flow._pick.prompt",
}
PLOT = ("datanuggets.plot", "datanuggets_flow.plot")


def _is_plot(name: str) -> bool:
    return name in PLOT or name.startswith(tuple(p + "." for p in PLOT))


def _modules(package: Path) -> dict[str, tuple[Path, bool]]:
    """Each module's dotted name, its file and whether it is a package's __init__."""
    found = {}
    for path in sorted(package.rglob("*.py")):
        parts = list(path.relative_to(package.parent).with_suffix("").parts)
        is_init = parts[-1] == "__init__"
        found[".".join(parts[:-1] if is_init else parts)] = (path, is_init)
    return found


LIBRARY_MODULES = set(_modules(LIBRARY))


def _graph() -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    """Each module's imports of the package's modules, its imports of other top-level packages,
    datanuggets among them, and its imports of the library's modules by their full dotted names.
    An imported name that is a submodule counts as that module; any other counts as the module it
    is imported from."""
    modules = _modules(PACKAGE)
    inside, outside, lib = {}, {}, {}
    for name, (path, package) in modules.items():
        edges, others, library = set(), set(), set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    here = name.split(".") if package else name.split(".")[:-1]
                    here = here[: len(here) - node.level + 1]
                    base = ".".join([*here, *([node.module] if node.module else [])])
                known = LIBRARY_MODULES if base.split(".")[0] == "datanuggets" else modules
                targets = [
                    f"{base}.{a.name}" if f"{base}.{a.name}" in known else base for a in node.names
                ]
            else:
                continue
            for target in targets:
                top = target.split(".")[0]
                if top == "datanuggets":
                    others.add(top)
                    while target not in LIBRARY_MODULES:  # ends at datanuggets at the latest
                        target = target.rsplit(".", 1)[0]
                    library.add(target)
                    continue
                if top != "datanuggets_flow":
                    others.add(top)
                    continue
                while target not in modules:
                    target = target.rsplit(".", 1)[0]
                if target != name:
                    edges.add(target)
        inside[name], outside[name], lib[name] = edges, others, library
    return inside, outside, lib


INSIDE, OUTSIDE, LIB = _graph()


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """The graph's strongly connected components of more than one module (Tarjan's)."""
    index, low, stack, on, found = {}, {}, [], set(), []

    def visit(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        on.add(v)
        for w in sorted(graph[v]):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return found


def _draws_directly(name: str) -> bool:
    return "matplotlib" in OUTSIDE[name] or any(_is_plot(t) for t in INSIDE[name] | LIB[name])


def _reaching_draw() -> set[str]:
    """The modules that import matplotlib or a plot module, or import one that does."""
    reach = {name for name in INSIDE if _draws_directly(name)}
    grown = True
    while grown:
        grown = False
        for name, edges in INSIDE.items():
            if name not in reach and edges & reach:
                reach.add(name)
                grown = True
    return reach


def test_the_graph_is_read_from_the_source():
    """The reader fails closed: it finds the modules and the edges the checks rest on, so a
    reader that silently found nothing can't pass them."""
    assert {"datanuggets_flow", "datanuggets_flow.pipeline", "datanuggets_flow.plot"} <= set(INSIDE)
    assert "datanuggets_flow._pipeline.stages" in INSIDE["datanuggets_flow.pipeline"]
    assert "datanuggets.plot" in LIB["datanuggets_flow.figures"]
    assert (
        "datanuggets_flow.figures" in INSIDE["datanuggets_flow._pipeline.stages"]
    )  # in a function
    assert "matplotlib" in OUTSIDE["datanuggets_flow.plot"]
    assert _cycles({"a": {"b"}, "b": {"a"}, "c": {"a"}}) == [["a", "b"]]


def test_the_package_has_no_import_cycles():
    assert _cycles(INSIDE) == []


def test_only_the_modules_that_draw_reach_matplotlib_or_plot():
    reach = _reaching_draw()
    assert {"datanuggets_flow.figures", "datanuggets_flow.plot"} <= reach
    core = sorted(n for n in reach if n not in DRAWS and not _is_plot(n))
    assert core == [], f"these modules reach matplotlib or a plot module: {core}"


def test_the_flow_package_imports_no_drawing_module():
    """datanuggets_flow, what import datanuggets_flow loads, reaches no module that draws,
    through any import."""
    reach = _reaching_draw()
    assert {"datanuggets_flow"}.isdisjoint(reach)
