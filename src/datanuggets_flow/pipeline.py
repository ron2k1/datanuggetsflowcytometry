"""The datanuggets-flow run as library steps, which a backend calls without the CLI: nothing here
reads the terminal or prints to it. A step reports what the CLI prints as a StageEvent, whose
message the CLI prints and whose data a backend reads. read_fcs reads a file with flowio, which
loads only when a file is read, and read_ranges its header alone, for a backend that shows the
channels' ranges; pandas loads in the steps that make tables, scikit-learn only for the t-SNE, and
matplotlib only for the figures.

The steps live in datanuggets_flow._pipeline, a module per job: fcs reads a file, records holds
what the steps pass along, cofactor picks the Transform stage's cofactors from a NegativeTally of
the cells the run clusters, selection reads --pops and --groups, gating gates, clustering scales
the channels, tallies the cells below 0 (negative_tally) and makes and clusters the nuggets,
tables makes the tables, and stages runs each stage. This module is their public path: every
name it has always had is imported from here, and a stand-in for a step set on this module is the
one the CLI calls."""

# ruff: noqa: F401

from datanuggets_flow._pipeline.clustering import (
    MIN_KEPT_EVENTS,
    MIN_OCCUPIED_NUGGETS,
    _kept_cells,
    cluster_nuggets,
    make_nuggets,
    negative_tally,
    pooled_scaling,
    resolve_channels,
    tsne_embedding,
)
from datanuggets_flow._pipeline.cofactor import NegativeTally, auto_cofactor, resolve_cofactor
from datanuggets_flow._pipeline.fcs import decode_ranges, read_fcs, read_ranges
from datanuggets_flow._pipeline.gating import gate_files, population_stats, population_table
from datanuggets_flow._pipeline.records import (
    Cofactor,
    Kept,
    OnEvent,
    Pool,
    PopStats,
    RangesReader,
    Reader,
    RunResult,
    Sample,
    Scaling,
    StageEvent,
    Tables,
)
from datanuggets_flow._pipeline.selection import (
    parse_groups,
    parse_pops,
    parse_selection,
    pick_events,
    pops_spec,
    selection_choices,
)
from datanuggets_flow._pipeline.stages import cluster_stage, gate_stage
from datanuggets_flow._pipeline.tables import result_tables, selection_table, write_tables
