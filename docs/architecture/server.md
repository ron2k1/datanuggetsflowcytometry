# The app server's layout

How `app/server/dnapp`, the FastAPI server behind the datanuggets web app, is organized: by
feature, with the code, the tests and the worker of each feature in one folder, and the features
joined through interfaces in `core` instead of through each other. The HTTP API itself is pinned
in [docs/app/contract.md](../app/contract.md); this page is about where its code lives.

For the package's own layout (`src/datanuggets_flow`), see [package.md](package.md). For where the
server sits among the repository's layers, and the tests that keep their boundaries, see
[ARCHITECTURE.md](../ARCHITECTURE.md).

## The tree

```
app/
  conftest.py          pytest's root: the shared kit, and one command for every test
  tests/               cross-feature and end-to-end tests, testkit.py, architecture/
  server/dnapp/
    __main__.py        python -m dnapp and the datanuggets-app script
    main.py            create_app: the one module that wires the features together
    core/              what every feature may import; it imports no feature
      package/         the only code that imports datanuggets
    features/<name>/   one folder per feature: router, service, schemas, worker, tests/
```

A feature folder holds only the files it needs. `router.py` holds its routes; `service.py` the
records and logic behind them, and the class another feature reaches it through, when one does;
`schemas.py` its request bodies; `worker.py` the work its jobs run in a worker process; `tests/`
its own tests. Larger features split further by step (uploads has `receive.py` and
`describe.py`, plot has `cells.py`).

## The features

Every route is under `/api/v1`. "Implements" names the `core/protocols.py` interface the feature
provides; "uses" names the services it reads from the shared state.

| Feature | Routes | Implements | Uses |
|---|---|---|---|
| `meta` | `GET /health`, `GET /config` | | jobs |
| `workspaces` | `GET /workspace`, `DELETE /workspace` | | each `WorkspaceSection`, jobs |
| `uploads` | `POST /uploads`, `GET /uploads`, `GET /uploads/{uid}`, `DELETE /uploads/{uid}` | `UploadStore`, `WorkspaceSection` | each `UploadUser` |
| `datasets` | `POST /datasets` | `WorkspaceSection` | uploads |
| `demos` | `GET /demos`, `POST /demos/{demo_id}/load` | | uploads |
| `jobs` | `GET /jobs`, `GET /jobs/{jid}`, `POST /jobs/{jid}/cancel` | `JobRunner`, `WorkspaceSection` | |
| `gates` | `POST /flow/gates`, `GET /flow/gates/{gid}`, `GET /flow/gates/{gid}/figures/{name}`, `DELETE /flow/gates/{gid}` | `GateStore`, `UploadUser`, `WorkspaceSection` | uploads, jobs, each `GateUser` |
| `flow` | `POST /flow/runs` | | uploads, gates, jobs, runs |
| `livecells` | `GET /flow/gates/{gid}/livecells`, `POST /flow/gates/{gid}/livecells`, `GET /flow/gates/{gid}/livecells/{lid}`, `POST /flow/gates/{gid}/livecells/{lid}/counts` | `GateUser` | gates, jobs, its own `LiveCells` in `features` |
| `runs` | `GET /runs`, `GET /runs/{rid}`, `DELETE /runs/{rid}` | `RunStore`, `GateUser`, `WorkspaceSection` | jobs |
| `plot` | `GET /runs/{rid}/plot`, `GET /runs/{rid}/cells` | | runs |
| `compare` | `GET /runs/{rid}/compare` | | runs |
| `downloads` | `GET /runs/{rid}/files/{name}`, `GET /runs/{rid}/download.zip` | | runs |

Three features run jobs: `gates`, `flow` and `livecells`. Each has a `worker.py` whose work
function main.py registers under the job kind in `JOB_KINDS`; the `jobs` feature runs whatever
that table names and knows no kind itself. `runs` holds the records that `flow` creates, and
`plot`, `compare` and `downloads` serve a done run's files. `livecells` keeps
its sets inside their gate's folder (see
[docs/app/contract-livecells.md](../app/contract-livecells.md)): a job reads the kept cells
once into `values.npz`, and each counts request then reads that file, through a small
in-memory cache, in FastAPI's threadpool and never in the job pool. The cache also bounds the
loads (one per set at a time, and no more sets loading at once than it keeps), since a load
reads a whole set into memory. At boot, after the jobs are loaded, main.py has `livecells`
remove the set folders that are not a done set's, which a crash or kill can leave half written.

`datasets` keeps only the names given to channel sets, as records in `meta.json`; the page
groups uploads into datasets itself. At the cap on names it reads the uploads, to remove the
names of the sets none of them has. The rule that a gate takes files of one dataset is
`core/datasets.py`'s, which reads each upload's colour channels with `core/package/flow.py`'s
`colour_channels`: `POST /flow/gates` refuses a mix with it before it queues a job, and
`POST /flow/runs` refuses a gate whose uploads mix datasets, as one made before that check can
(see [docs/app/contract.md](../app/contract.md), sections 3.3 and 3.4).

## core

`core` is what the features share and nothing feature-specific:

- `config.py`: every cap, default, path and environment name. `Settings.from_env()` is the only
  reader of `os.environ`.
- `errors.py` and `http.py`: the pinned error shape and its handlers, path scrubbing, the
  security headers, the trial cookie and download headers.
- `limits.py`: the trial's per-IP, per-hour and per-day limits, the per-minute window the
  live-cells counts take, and the disk floor.
- `workspace.py`: the workspace folders, `meta.json`, the record lists and id counters.
- `payload.py`, `run_outputs.py`, `filters.py`, `pops.py`: reading what the package writes, and
  the row filter and the per-file population choice that several features take. Each is here
  because more than one feature uses it.
- `datasets.py`: an upload's colour channel set, and the check that a request's uploads are of
  one dataset, with the words that say how two differ.
- `protocols.py`, `state.py`, `deps.py`: the interfaces, the shared state that carries their
  implementations, and the FastAPI dependencies that read it (below).
- `package/`: every call into datanuggets, one module per area (runtime, errors, filters,
  colors, flow, livecells). It imports the package inside each function, so the server starts
  without loading what only a worker needs, and nothing the FastAPI process calls there imports
  `datanuggets.plot` or matplotlib. Figures are drawn in the job workers.

## The interfaces

A feature that needs another feature's service names the interface in `core/protocols.py` and
reads the implementation from the shared state. It never imports the other feature.

| Interface | Implemented by | Used by |
|---|---|---|
| `JobRunner` (with `Job`, `Work`, `Reporter`) | `jobs.service.JobManager` | gates, flow, livecells, runs, workspaces, meta; each worker's work function gets a `Reporter` |
| `UploadStore` | `uploads.service.Uploads` | demos, gates, flow, datasets |
| `UploadUser` | gates | uploads, before it deletes an upload |
| `GateStore` | `gates.service.Gates` | flow, livecells |
| `GateUser` | runs, livecells | gates, which asks each user before deleting a gate and tells each one as it does |
| `RunStore` | `runs.service.Runs` | flow, plot, compare, downloads |
| `WorkspaceSection` | uploads, gates, runs, jobs, datasets | workspaces, for the `GET /workspace` body |

`ACTIVE` and `FINAL`, the job statuses, sit beside them.

### How main.py wires them

`main.build_state` constructs each feature's service, then the `State` dataclass
(`core/state.py`) that holds them, typed by interface, plus three tables:

- `sections`: the record kinds `GET /workspace` lists, by key, in the body's order;
- `upload_users` and `gate_users`: who is asked, in order, before an upload or a gate is deleted.
  The first one that gives a reason refuses the delete with a 409. A gate's users are then told
  it is going, so each drops what it keeps for the gate.
- `features`: a feature's own service that keeps state between requests and that no other
  feature reads, by the feature's name. The feature reads it with `core.deps.own`, which checks
  its type, so `State` names no feature class.

`create_app` puts the state on `app.state.dn`, includes every feature's router under
`/api/v1`, then the API's 404 fallback, the page and the security headers. A route reads the
state with `core.deps.st(request)` and its workspace through the `WS` dependency; a route that
starts a job calls `check_job_room` first.

`JOB_KINDS` maps each job kind to its work function, and `JobManager` gets the table when it is
built. A work function must be module-level, since the spawned worker pool sends it by name.

## Adding a feature

1. Make `features/<name>/` with an `__init__.py` whose docstring says what the feature is, and a
   `router.py` with `router = APIRouter()` and its routes. Import only `dnapp.core` and your
   own folder.
2. Put the logic in `service.py` and request bodies in `schemas.py`. Read shared services with
   `st(request).<service>` and type them by their interface.
3. When another feature has to reach yours, add a Protocol to `core/protocols.py`, a field to
   `State`, and the construction to `main.build_state`. When yours has to refuse another's
   delete, implement `UploadUser` or `GateUser` and add it to that list in `build_state`. When
   it keeps a record kind, implement `WorkspaceSection` and add it to `sections`. When only your
   feature reads its service but the service keeps state between requests (a cache, say),
   construct it in `build_state`, put it in `features` under your feature's name, and read it
   with `own(request, "<name>", YourService)`.
4. For a job, write the work function in `worker.py`, register it in `JOB_KINDS`, and submit
   through `st(request).jobs`.
5. For a call into datanuggets, add or extend a module in `core/package/`.
6. Include the router in `create_app`'s list.
7. Put the tests in `features/<name>/tests/` with an empty `__init__.py`. Build clients with the
   kit (the `make_client` fixture, or `testkit.new_client` for a restart) and use its real-data
   fixtures and helpers; never import `dnapp.main`.

Caps and defaults go in `core/config.py`, and API errors through `core.errors.ApiError`.

## The boundary rules and their test

`app/tests/architecture/test_server_boundaries.py` reads every module's source with `ast`, so
nothing is imported to check it, and fails when:

1. a module under `features/<a>`, its tests included, imports from `dnapp` anything but
   `dnapp.core` and `dnapp.features.<a>`: no other feature, and not `main.py`;
2. a module outside `core/package` imports `datanuggets`;
3. a module in `core` imports a feature or `main.py`.

It also checks that `main.py` imports every feature folder. Relative imports are resolved, and
`importlib.import_module("...")` or `__import__("...")` with a literal name count as imports.
Each rule asserts that it saw imports to judge, so a scan that found no files fails too. Its
commit records a planted violation of each rule being caught.

## Tests and packaging

One command collects every test, from `app/tests` and from each feature's `tests/`:

```
uv run --project app pytest -n 2 app/tests
```

Run from `app/`, plain `pytest` does the same. `app/conftest.py` loads `tests/testkit.py` as a
plugin, which gives every test the same fixtures, and adds `server/` when only the tests folder is
named. The wheel (`[tool.hatch.build.targets.wheel] exclude`) and the Docker image (the
`Dockerfile`, and `.dockerignore` for a local build) leave out every `tests/` folder and
`app/conftest.py`.
