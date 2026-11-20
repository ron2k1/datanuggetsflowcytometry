"""Cabrera's gate finder for the lymphocyte and macrophage populations on two channels (FSC-A
against SSC-A in his files, any two in yours), from Prof. Cabrera's Python port of the original R
code, checked piece by piece against it."""

from importlib.metadata import version as _version

from datanuggets_flow.gate import (
    FinderPeaks,
    finder_peaks,
    gate_peaks,
    hull_gate,
    lymphmacro_finder,
)
from datanuggets_flow.grid import DensityGrid, f_plot
from datanuggets_flow.peaks import find_area, local_maxima, mirrored_area, refine_peaks, search_ind

# pyproject.toml holds the version; this reads it back from the installed metadata
__version__ = _version("datanuggets-flow")

__all__ = [
    "DensityGrid",
    "FinderPeaks",
    "f_plot",
    "find_area",
    "finder_peaks",
    "gate_peaks",
    "hull_gate",
    "local_maxima",
    "lymphmacro_finder",
    "mirrored_area",
    "refine_peaks",
    "search_ind",
]
