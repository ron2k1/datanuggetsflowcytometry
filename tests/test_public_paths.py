"""Every name a user or a script imports by module stays importable from that module: the names
docs/api.md documents, every __all__, every name the two facades (pipeline and pick) defined before
their parts moved behind them, and the private names code outside the package imports. A split that moves a name must re-export it from its old module, keeping one
implementation of it."""

import ast
import importlib
import re
from pathlib import Path

import pytest

import datanuggets_flow

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "docs" / "api.md"
# The source of the package the tests import: src/datanuggets_flow in a checkout, and the
# installed wheel's when package.yml runs the sdist's tests with src/ deleted
PACKAGE = Path(datanuggets_flow.__file__).resolve().parent

# api.md's sections whose `### `name`` headings document a name of one module
SECTION_MODULES = {
    "Flow utilities": "datanuggets_flow",
    "Plotting": "datanuggets_flow.plot",
}
# headings whose ```text block lists one module's names, a line each; a heading that is a
# module's name in backticks lists that module's
BLOCK_MODULES = {
    "Flow settings": "datanuggets_flow.settings",
    "Live cells": "datanuggets_flow.livecells",
}
# the section whose table lists each pipeline module's public names
TABLE_SECTION = "The flow pipeline library"

# The names each facade defined itself before its parts moved behind it, private ones included,
# and the two pick re-exported from pipeline. Tests and scripts reach some of the private ones.
FACADES = {
    "datanuggets_flow.pipeline": (
        "MIN_KEPT_EVENTS MIN_OCCUPIED_NUGGETS read_fcs StageEvent Reader OnEvent PopStats Sample "
        "Kept Pool Tables RunResult parse_pops pick_events selection_choices parse_selection "
        "parse_groups pops_spec population_stats population_table gate_files gate_stage "
        "resolve_channels selection_table make_nuggets _kept_cells cluster_nuggets "
        "tsne_embedding result_tables write_tables cluster_stage"
    ),
    "datanuggets_flow.pick": (
        "per_file read_fcs _fcs_paths _parser _live_input _ask _pyplot _given _mode_rules _flags "
        "_settings groups_for _out _check_args _print_event _read DRAWN _print_drawn _gate_files "
        "_draw_gates _choose_pops _channel_names _choose_channels main _marked _run "
        "_note_versions _from_gates parse_pops pick_events"
    ),
}

# Private names that code outside the package imports: Prof. Cabrera's flow benchmarks (the
# finder's _finder, MSIZE, bin_mask and sqrt_coords).
OUTSIDE = {
    "datanuggets_flow.gate": ("_finder", "MSIZE", "bin_mask"),
    "datanuggets_flow.grid": ("sqrt_coords",),
}

HEADING = re.compile(r"^(#{2,3}) (.+?)\s*$")
TICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
MODULE_HEADING = re.compile(r"^`(datanuggets_flow(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`$")
NAME_HEADING = re.compile(r"^`([A-Za-z_][A-Za-z0-9_]*)`$")
BLOCK_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\b")
TABLE_ROW = re.compile(r"^\| `(datanuggets_flow(?:\.[A-Za-z_][A-Za-z0-9_]*)*)` \| (.+) \|$")


def _documented() -> dict[str, set[str]]:
    """Each module api.md documents names of, and those names, from its name headings, its
    ```text blocks of signatures and the pipeline library's table."""
    found: dict[str, set[str]] = {}
    section = heading = None
    fence = None  # the fence's language while inside one
    for line in API.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fence = line[3:].strip() if fence is None else None
            continue
        if fence is not None:
            module = BLOCK_MODULES.get(heading)
            if module is None and heading and MODULE_HEADING.match(heading):
                module = heading.strip("`")
            name = BLOCK_LINE.match(line)
            if fence == "text" and module and name:
                found.setdefault(module, set()).add(name.group(1))
            continue
        m = HEADING.match(line)
        if m:
            level, text = m.groups()
            if level == "##":
                section, heading = text, None
            else:
                heading = text
                name = NAME_HEADING.match(text)
                if name and section in SECTION_MODULES:
                    found.setdefault(SECTION_MODULES[section], set()).add(name.group(1))
            continue
        row = TABLE_ROW.match(line)
        if row and section == TABLE_SECTION:
            found.setdefault(row.group(1), set()).update(TICKED.findall(row.group(2)))
    return found


DOCUMENTED = _documented()


def _all_modules() -> list[str]:
    """Every module of the package whose source assigns __all__, found without importing it."""
    names = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assigned = {
            t.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name)
        }
        if "__all__" in assigned:
            parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
            names.append(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return names


def _check(module: str, names) -> None:
    """Every name imports from module, as the one object its defining module holds."""
    mod = importlib.import_module(module)
    missing = [name for name in names if not hasattr(mod, name)]
    assert missing == [], f"{module} no longer has {missing}"
    for name in names:
        obj = getattr(mod, name)
        home = getattr(obj, "__module__", None)
        ours = isinstance(home, str) and home.split(".")[0] == "datanuggets_flow"
        if ours and callable(obj) and getattr(obj, "__name__", None) == name:
            assert getattr(importlib.import_module(home), name) is obj, (module, name, home)


def test_the_docs_are_read_for_every_module_they_document():
    """The reader of api.md fails closed: each module the guide documents yields names, so a
    reworded heading or table can't leave its names unchecked."""
    assert sorted(DOCUMENTED) == sorted(
        {
            "datanuggets_flow",
            "datanuggets_flow.compare",
            "datanuggets_flow.exceptions",
            "datanuggets_flow.figures",
            "datanuggets_flow.livecells",
            "datanuggets_flow.outputs",
            "datanuggets_flow.pipeline",
            "datanuggets_flow.plot",
            "datanuggets_flow.settings",
            "datanuggets_flow.state",
        }
    )
    assert DOCUMENTED["datanuggets_flow.plot"] == {"gates", "peaks"}
    assert {"gate_stage", "cluster_stage", "read_fcs", "OnEvent"} <= DOCUMENTED[
        "datanuggets_flow.pipeline"
    ]
    assert {"lymphmacro_finder", "gate_peaks"} <= DOCUMENTED["datanuggets_flow"]


@pytest.mark.parametrize("module", sorted(DOCUMENTED))
def test_documented_names_import_from_their_documented_module(module):
    _check(module, sorted(DOCUMENTED[module]))


ALL_MODULES = _all_modules()


def test_the_source_is_read_for_every_module_that_assigns_all():
    """The reader of the package's source fails closed: it finds the modules whose __all__ the
    next test checks, so a source tree it can't find can't leave every __all__ unchecked."""
    assert {"datanuggets_flow"} <= set(ALL_MODULES)


@pytest.mark.parametrize("module", ALL_MODULES)
def test_every_all_name_imports_from_its_module(module):
    names = importlib.import_module(module).__all__
    assert names, module
    _check(module, names)


@pytest.mark.parametrize("module", sorted(FACADES))
def test_facades_keep_every_name_they_defined(module):
    _check(module, FACADES[module].split())


@pytest.mark.parametrize("module", sorted(OUTSIDE))
def test_private_names_code_outside_the_package_imports_stay(module):
    _check(module, OUTSIDE[module])
