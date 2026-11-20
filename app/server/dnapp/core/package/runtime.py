"""The installed package's version, and the set-up every job worker runs before its first job."""

from __future__ import annotations

from importlib.metadata import version


def package_version() -> str:
    """The installed datanuggets-flow version. The image tag and the release tag in the "Run it
    locally" commands are versions of that package, not of the datanuggets library it uses."""
    return version("datanuggets-flow")


def prepare_worker() -> None:
    """Runs once in each worker process: the package's figures go to files, and labels are never
    read as math. Only workers call this; the FastAPI process never loads matplotlib."""
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["text.parse_math"] = False
