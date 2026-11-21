# Getting started

`datanuggets-flow` is a research alpha. Read the [limitations](limitations.md) before you interpret a run.

## Install

Use Python 3.12 or newer. The package installs where `datanuggets` does: Windows x64, Apple silicon Macs running macOS 12 or newer, and Linux x86-64 or ARM64 with glibc 2.27 or newer.

```sh
python -m pip install "datanuggets-flow==0.1.0a6"
```

This also installs `datanuggets`, flowio, pandas, matplotlib and scikit-learn. `0.1.0a6` is a pre-release, and naming the version tells pip to install it.

## A first datanuggets-flow run

```sh
datanuggets-flow path/to/fcs_folder
```

1. **Run from the folder that should hold `outputs/`.** Each run creates a new `outputs/flow-<timestamp>/` folder for its figures and tables. An optional `--out` must name a new folder, and an existing path is refused. A failed or cancelled run leaves an `INCOMPLETE.txt` marker beside any partial results.
2. **Inspect the gates.** The command shows the candidate populations and their counts. You choose populations for each file. The same population number needn't name the same cells in another file.
3. **Review the clustered results.** The kept events are reduced per file, and their nuggets are clustered together. Examine the tables and figures before you read a cluster as a cell type.

Choose at least two distinct fluorescence channels. The command checks this before asking for populations. Clustering also needs at least three occupied nuggets across the kept files. Channel flags use the FCS `$PnN` names, not display marker names.

By default the command clusters the channels whose names end in `-A` and aren't scatter (such as FSC-A, SSC-A or a Navios's FS INT). Files with fewer than two such channels, or with no FSC-A and SSC-A, are covered in [Files from other instruments](cli.md#files-from-other-instruments). It applies `arcsinh(x / c)`, with a cofactor `c` picked per channel from the cells being clustered. That's 150, or the spread of the channel's cells below 0 when that's wider and at least 1% of its cells are below 0. `--cofactor N` sets one for every channel ([Transform and Scale](cli.md#transform-and-scale)). Check both choices for your panel. The command doesn't compensate.

The command's default `--disc reference` and the array finder's default area rule differ, and they can change which events a population holds. Gates can overlap. Selecting several keeps their union, with each event counted once.

After inspecting each file's populations, a scripted run can use:

```sh
datanuggets-flow path/to/fcs_folder --pops "1,2" --no-show
```

This gets its own output folder too. `--pops "1,2"` applies those population numbers to every file, so check that they name equivalent populations.

## Gate once, choose later

To gate once and choose later, or choose more than once, run the two stages separately:

```sh
datanuggets-flow path/to/fcs_folder --gates-only --out outputs/gates-001
datanuggets-flow --from-gates outputs/gates-001
```

The first command gates the files, saves both gate figures and the gates in `outputs/gates-001`, and stops without asking. The second asks over those figures and clusters without gating again, in its own new output folder. Leave the FCS files where they are in between. The second stage refuses a file that moved or changed. [Staged runs](cli.md#staged-runs) describes the gate folder.

## Run it from Python

The same two stages run from Python. `gate_stage` gates the files and saves the gates in a folder. `cluster_stage` clusters the populations you choose from that folder.

```python
from pathlib import Path

from datanuggets_flow.pipeline import cluster_stage, gate_stage, parse_selection
from datanuggets_flow.settings import ClusterSettings, GateSettings
from datanuggets_flow.state import load_gates, write_run

gates, run = Path("outputs/gates-001"), Path("outputs/run-001")
gates.mkdir(parents=True)
gate_stage(sorted(Path("path/to/fcs_folder").glob("*.fcs")), gates, GateSettings())

# Open gates/local_maxima.png and decide which populations to keep.
folder = load_gates(gates)
chosen = parse_selection("1,2", [len(s["stats"]) for s in folder.samples])

run.mkdir()
settings = ClusterSettings(k=12)
result = cluster_stage(folder.samples, chosen, run, settings)
write_run(run, gates, settings, chosen, result.channels, result.labels,
          scaling=result.pool.scaling, cofactor=result.cofactor, pool=result.pool)
print(result.tables.summary)
```

`write_run` saves `run.json` in the run folder. The terminal command and the app write that file for you. The stage functions never print or prompt. Progress comes back through an `on_event` callback, and a bad setting raises `FlowError` before any file is read. [api.md](api.md#the-flow-pipeline-library) documents each function.

## Next steps

The [CLI reference](cli.md) lists flags, outputs and errors. The [methodology](methodology.md) explains the pipeline, and [reproducibility](reproducibility.md) records the public dataset used for validation. To run the app instead, see [Running the app locally](app/running-locally.md).
