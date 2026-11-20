# Architecture

How the datanuggets-flow repository fits together: the layers it holds, which way they depend on each other, the tests that keep those lines, and where a new feature goes in each layer. This page is the map. Each layer's own page has the detail.

## The layers

| Layer | Where | What it is | Detail |
|---|---|---|---|
| Package | `src/datanuggets_flow/` | Prof. Cabrera's flow gate finder and the `datanuggets-flow` pipeline and command, built on the `datanuggets` library from PyPI. It is the only code in the wheel | [architecture/package.md](architecture/package.md) |
| Server | `app/server/dnapp/` | the FastAPI app behind the web workbench: the HTTP API under `/api/v1`, the job workers, and the app's only calls into the package | [architecture/server.md](architecture/server.md) |
| Web | `app/web/` | the browser workbench: static ES modules with no build step, Plotly vendored, and recorded API responses for `?fixtures=1` | [architecture/web.md](architecture/web.md) |
| Docker | `Dockerfile`, `compose.yaml`, `.dockerignore`, `app/demo/`, `app/scripts/`, `.github/workflows/app.yml` | one image holding the package, the server and the page. The demo data comes with a sha256 manifest, and CI builds the image and smoke-tests it with `app/scripts/smoke.py` | [app/running-locally.md](app/running-locally.md), and the comments at the top of each file |
| Docs | `docs/` | user guides at the top level, the app's API contract and how to run it in `docs/app/`, and each layer's layout in `docs/architecture/` | [README.md](README.md) |

The rest of the repository serves the package:

| Folder | Holds |
|---|---|
| `tests/` | the package's pytest suite, its recorded fixtures, and the package's two boundary tests |
| `scripts/` | `check_dist.py`, the check of a built sdist and wheel |
| `benchmarks/flow/` | the reference code the flow port is held to, and the comparisons and timings run against it |
| `.github/workflows/` | `tests.yml`, `matrix.yml`, `package.yml` and `release.yml` for the package, and `app.yml` and `image.yml` for the app and its image. [development.md](development.md#what-ci-runs) describes them |

The wheel holds the package alone. The sdist adds the package's tests and the user guides that `pyproject.toml` lists. The Docker image holds the installed package, `app/server/` without its tests, the page in `app/web/` without its fixtures and tools, and the demo data. The `Dockerfile` picks those files itself, since a build from a git URL gets no `.dockerignore`. `.dockerignore` keeps the rest, such as the tests, the benchmarks and the docs, out of a local build's context.

## Which way the dependencies run

Each arrow points from the code that imports or calls to the code it reaches. Nothing points back.

- **Web to server, over HTTP only.** The page reaches the server through the API client in `app/web/shared/api/`. No web module imports server code. The server serves `app/web/` as static files. The API is pinned in [app/contract.md](app/contract.md) and [app/contract-livecells.md](app/contract-livecells.md).
- **Inside the web, features to shared.** A module in `features/<name>/` imports only its own folder and `shared/`, and `shared/` imports only itself. `main.js` is the composition root that imports every feature. Features reach each other through the store, the events declared in `shared/events.js`, and the view and slot registry.
- **Inside the server, features to core.** A module in `features/<name>/` imports only `dnapp.core` and its own folder. `core` imports no feature, and `main.py` wires them together. Features reach each other's services through the interfaces in `core/protocols.py`.
- **Server core to the package.** The running server imports `datanuggets` and `datanuggets_flow` only in `core/package/`, inside each function, so the FastAPI process loads only what it calls. The app's tests and the fixture builder in `app/web/tools/` import the package directly, to check the app against it and to record fixtures from real runs.
- **The package to nothing outside it.** `src/datanuggets_flow` imports nothing from the app, `tests/`, `scripts/` or `benchmarks/`. Inside it, imports run from the command down to the `datanuggets` library, and only the modules that draw reach matplotlib. [package.md](architecture/package.md) gives the facades.

## The boundary tests

Each rule above has a test that reads the sources, so nothing is imported to check them. Every test runs with its layer's suite, and each can also be run alone from the repository root.

| Test | Fails when | Run it alone |
|---|---|---|
| `tests/test_import_graph.py` | the package has an import cycle, or a module outside `DRAWS` reaches matplotlib, `datanuggets_flow.plot` or `datanuggets.plot` | `uv run pytest tests/test_import_graph.py` |
| `tests/test_public_paths.py` | a name `docs/api.md` documents, a name in an `__all__`, or a name a facade ever defined stops importing from its path | `uv run pytest tests/test_public_paths.py` |
| `app/tests/architecture/test_server_boundaries.py` | a server feature imports another feature or `main.py`, `core` imports a feature, or a module outside `core/package/` imports `datanuggets` or `datanuggets_flow` | `uv run --project app pytest app/tests/architecture` |
| `app/tests/architecture/test_web_boundaries.py` | a web feature imports another feature, `shared/` imports a feature, an event is not declared or has no sender or listener, or a stylesheet is linked out of order | the same command |

The full suites are `uv run pytest -n 2` for the package and `uv run --project app pytest -n 2 app/tests` for the app. [development.md](development.md) covers the package's setup and lint. The app is linted on its own config by running `ruff check .` inside `app/`.

## Adding a feature

A feature that spans layers is built from the bottom up. The package gets the computation and its tests first. Then the server gets a `core/package/` call and a feature with its route, written into the contract. Last comes the web feature, with its client method and fixtures recorded from a real run on public data. Each layer's own steps:

- **Package.** A function, a setting of `datanuggets-flow` or a pipeline stage: [package.md](architecture/package.md), and for a stage, [Adding a flow stage](architecture/package.md#adding-a-flow-stage).
- **Server.** A folder in `features/`, wired in `main.py`: [server.md](architecture/server.md#adding-a-feature). A new endpoint is added to [app/contract.md](app/contract.md) in the same change.
- **Web.** A folder in `features/`, listed in `main.js`: [web.md](architecture/web.md#adding-a-feature). A new endpoint gets a method in `shared/api/client.js` and its fixtures from `tools/fixturegen/`.
- **Docker.** A file the running app reads has to be copied by the `Dockerfile` and not excluded by `.dockerignore`. A setting read from the environment goes in the server's `core/config.py`, and in `compose.yaml` when users should be able to override it. A demo dataset goes in `app/demo/manifest.json` with its size and sha256, which `app/scripts/fetch_demos.py` checks.
- **Docs.** A user guide goes in `docs/`. When it should ship in the sdist, it is also added to the sdist list in `pyproject.toml` and to `scripts/check_dist.py`. A change to a layer's layout updates that layer's page. This page changes only when a layer or a boundary does.
