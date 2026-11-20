# The package's layout

Paths on this page are inside `src/datanuggets_flow/`.

## Facades

### `datanuggets_flow.pipeline`

The library a backend runs the flow pipeline with. It holds no code of its own. Behind it, in `_pipeline/`:

| Part | Job |
|---|---|
| `fcs` | reading an FCS file's events, names and labels; flowio loads only when a file is read |
| `records` | the records the steps pass along and return, and the types of a reader and of an event callback |
| `selection` | `--pops` read as population numbers file by file, the events they keep, and `--groups` |
| `gating` | the gate step: each file gated with the finder, and its populations counted and described |
| `cofactor` | the arcsinh cofactor for a run: a number as given, or `auto`, picked per channel from the raw values of the cells the run clusters |
| `clustering` | the channels to cluster, each file's kept cells as nuggets, every file's nuggets clustered together by weighted k-means or the hierarchical tree, and the t-SNE |
| `tables` | `selection.csv` and the run's result tables, and the CSV files they are written to |
| `stages` | `gate_stage` and `cluster_stage`, which run the steps in order and save the figures; the only part that draws |

### `datanuggets_flow.pick`

The `datanuggets-flow` command. `pick.py` keeps `main`, the run in each mode, the figures it shows, and the reader every step reads through. Behind it, in `_pick/`:

| Part | Job |
|---|---|
| `args` | the flags, the FCS paths they name, the settings they give, checked before any file is read, and the rules each mode holds them to |
| `prompt` | the question of which populations to keep, asked at the terminal while the figures stay responsive, or read from `--pops` |

The reader, `pick.read_fcs`, and the gate step, `pick._gate_files`, stay in `pick.py` with the code that calls them. Tests stand in for them by patching `pick`, and a patch reaches a caller only in the module where the caller looks the name up. `args` and `prompt` call the library through the `pipeline` facade, which reaches the drawing `stages`, so both are in `DRAWS` though neither draws itself.

## Adding a flow stage

A stage is a step a run takes between reading the files and writing its results. For example, a step that drops cells before they become nuggets.

1. **Its settings.** The default goes in `_defaults.py`, the field and its check in `GateSettings` or `ClusterSettings` in `settings.py`, and the flag in `_pick/args.py`. Document the flag in [cli.md](../cli.md).
2. **The step.** It goes in `_pipeline/`, in the part whose job it extends or in a new part named for its job. It reports progress as a `StageEvent` through `on_event`, refuses bad input with a `FlowError` that names the setting, and never prints or asks. Optional packages are imported inside it. A new record it returns joins `records.py`.
3. **Its outputs.** Tables go in `tables.py`, or in `outputs.py` when only the viewer reads them. Figures go in `figures.py`, drawn on the `figure=` they are given. What a gate folder or `run.json` records goes in `state.py`.
4. **The wiring.** `stages.py` calls the step in its place in `gate_stage` or `cluster_stage`. A new public name is re-exported from `pipeline.py` and listed in the library's table in [api.md](../api.md), which puts it under `test_public_paths.py`. The command needs no change unless the step asks something; a question goes in `_pick/prompt.py`.
5. **Its tests.** Test the step alone in `tests/flow/test_flow_pipeline.py`, and the run in `test_flow_stages.py` and `test_flow_pick.py`. A step that changes the run's tables changes the digests the end-to-end tests pin. Record those again only for a change made on purpose. The import graph test fails if the new part imports `figures` or matplotlib. Leave drawing to `stages.py`.
