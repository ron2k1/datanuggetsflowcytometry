# Development

Setting up, running the tests and the lint, and checking a build. [ARCHITECTURE.md](ARCHITECTURE.md) maps the repository's layers and the tests that keep their boundaries. [architecture/package.md](architecture/package.md) shows where each part of the package, its tests and its fixtures live.

## Setup

```sh
git clone --branch main https://github.com/ron2k1/datanuggetsflowcytometry.git
cd datanuggetsflowcytometry
uv sync --locked --python 3.14
```

This creates `.venv` with an editable install of `datanuggets-flow`, `datanuggets` from PyPI and the development group: pytest, pytest-xdist, ruff and openpyxl. Every command below runs from the repository root. The app has its own project in `app/`, with its own `app/uv.lock`.

## Tests

```sh
uv run pytest -q -p no:cacheprovider -n 2
uv run --directory app --locked pytest -q -p no:cacheprovider -n 2
```

The first runs the package's tests and the second the app's. Neither needs R. The flow tests read the recorded events in `tests/fixtures/flow/`, which come from the public Zenodo record that [reproducibility.md](reproducibility.md) describes. `-n 2` runs two pytest-xdist workers, as CI does.

### What CI runs

| Workflow | When | What it runs |
| --- | --- | --- |
| `tests.yml` | every pull request, every push to `main`, on manual dispatch, and inside a release | `uv sync --locked`, then the tests on Linux for Python 3.12 to 3.15 |
| `matrix.yml` | every pull request to `main`, on manual dispatch, and inside a release | the tests on Windows and macOS for Python 3.12 to 3.15 |
| `package.yml` | every pull request, every push to `main`, on manual dispatch, and inside a release | the build check below, then the sdist's tests against the installed wheel |
| `app.yml` | a pull request or a push to `main` that changes the app, the package or the Docker files, on manual dispatch, and inside a release | the app's tests, then its Docker image built natively on amd64 and arm64 and smoke-tested. Nothing is pushed |
| `release.yml` | on manual dispatch for a check or TestPyPI, a pushed `v*` tag for PyPI | the four above, then the upload and, for a tag, `image.yml`, as [releasing.md](releasing.md) describes |
| `image.yml` | inside a tag's release after the PyPI upload, or on manual dispatch on a tag already on PyPI | the app's image, pushed to `ghcr.io/ron2k1/datanuggets-flow` by digest, smoke-tested on amd64 and arm64, then tagged with the package version |

## Lint

```sh
uv run ruff check
uv run ruff format --check
```

No workflow runs ruff, so run both before pushing. `uv run ruff format` rewrites the files the check flags. The settings in `pyproject.toml` set the line length to 100. They leave out `app/`, `docs/`, the README files, `benchmarks/flow/cabrera_reference.py` and `benchmarks/flow/run_cabrera.py`. The last two keep Prof. Cabrera's code as written.

## Check a build

Build into an empty folder and run the checks `package.yml` runs:

```sh
uv build --out-dir tmp/dist
uv run --no-project python scripts/check_dist.py tmp/dist
uvx --from twine==7.0.0 twine check --strict tmp/dist/*
```

`check_dist.py` opens the sdist and the wheel. It fails on a file outside the allowlist in `pyproject.toml`, a cache file, a home-folder path, a denied word or versions that disagree. Leftovers from an earlier build in the same folder can fail it. `--expect-version` makes it fail unless the build has that version, which the release uses on a tag. `package.yml` then installs the wheel alone in a new environment, runs `uv pip check` and `datanuggets-flow --help`, deletes `src/` from the unpacked sdist and runs the sdist's own tests against the installed wheel. [releasing.md](releasing.md) covers publishing.

## Repository contents

Keep the Python source, the tests, the recorded fixtures and the public documentation tracked. The library's R comparisons live in the `datanuggets` repository, and its [development guide](https://github.com/ron2k1/datanuggets/blob/main/docs/development.md) covers them. [limitations.md](limitations.md) describes the current behavior and open problems.
