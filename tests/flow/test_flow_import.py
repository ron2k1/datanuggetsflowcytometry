"""The gate finder runs with matplotlib blocked, and the flow library's modules import without
matplotlib, pandas, scikit-learn or flowio, which load only where a file is read or drawn."""

import subprocess
import sys

CODE = """
import sys
sys.modules["matplotlib"] = None
import numpy as np
from datanuggets_flow import lymphmacro_finder
rng = np.random.default_rng(0)
fsc = np.concatenate([rng.normal(4e5, 3e4, 4000), rng.normal(7e5, 5e4, 2000)])
ssc = np.concatenate([rng.normal(2e5, 2e4, 4000), rng.normal(5e5, 6e4, 2000)])
print(lymphmacro_finder(fsc, ssc).shape)
"""
# the flow library's modules, which a backend imports without the CLI
LIBRARY = ("datanuggets_flow.settings", "datanuggets_flow.pipeline", "datanuggets_flow.state")
# the packages that load only where a file is read, tabulated or drawn
LAZY = ("matplotlib", "pandas", "sklearn", "flowio")


def test_the_gate_finder_runs_without_matplotlib():
    out = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True, check=True)
    assert out.stdout.strip().startswith("(6000, ")


def test_flow_library_modules_import_without_the_lazily_loaded_packages():
    code = (
        "import importlib, sys\n"
        f"sys.modules.update(dict.fromkeys({LAZY!r}))\n"
        f"for name in {LIBRARY!r}:\n"
        "    importlib.import_module(name)\n"
        "assert 'datanuggets_flow.pick' not in sys.modules\n"
    )
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr[-2000:]


def test_the_run_viewer_table_modules_import_without_matplotlib_or_pandas():
    code = (
        "import sys\n"
        "sys.modules.update(dict.fromkeys(('matplotlib', 'pandas', 'sklearn')))\n"
        "import datanuggets_flow.compare, datanuggets_flow.outputs\n"
    )
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr[-2000:]
