"""pytest's root for the app's tests, which live in two places: app/tests (the cross-feature and
end-to-end tests, and tests/testkit.py, the shared kit) and each feature's own tests/ folder
beside its code under server/dnapp/features. This file gives both the kit's fixtures, and makes a
run of the tests folder alone (CI's `pytest app/tests`) collect the features' tests too, so one
command runs everything. The wheel and the Docker image leave every tests/ folder out."""

from __future__ import annotations

from pathlib import Path

pytest_plugins = ["testkit"]  # importable through pythonpath = ["tests"] in pyproject.toml

HERE = Path(__file__).resolve().parent


def pytest_configure(config):
    tests, server = HERE / "tests", HERE / "server"
    given = {Path(a).resolve() for a in config.args}
    if tests in given and server not in given:
        config.args.append(str(server))
