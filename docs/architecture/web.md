# The web workbench: architecture

`app/web` is the browser half of the datanuggets app: static ES modules with no build step, served
as files under a Content-Security-Policy of `script-src 'self'` (no inline script, no `eval`).
Plotly 3.0.1 strict is vendored and loaded as a classic script, so modules reach it as
`window.Plotly`. The HTTP API it calls is pinned in [docs/app/contract.md](../app/contract.md)
section 3 and [contract-livecells.md](../app/contract-livecells.md); the behaviour it must keep is in
sections 6 to 8 there.

The code is split by feature. Each screen or panel lives in one folder with its own stylesheet,
and features never import each other: they share state through the store, announce changes as
events declared in one file, and plug into each other's screens through a view registry and named
slots. A test reads the sources and fails when a module crosses those lines.
[ARCHITECTURE.md](../ARCHITECTURE.md) places the web app among the repository's layers.

## Layout

```
app/web/
  index.html           the page: stylesheets in cascade order, theme-boot.js, Plotly, main.js
  main.js              the composition root: mounts every feature, loads /config and /workspace
  shared/              what features have in common; imports nothing outside shared/
    api/               the API client (client.js) and its two transports (live.js, fixtures.js)
    store.js           app state S, the event bus (emit/subscribe), payload caches
    events.js          every event name and its payload
    views.js           the tab-view registry and named slots
    theme.js           the light/dark switch; theme-boot.js applies a stored choice before paint
    config.js          UI constants (caps and analysis defaults come from GET /config instead)
    plot-base.js       Plotly chrome that follows the theme: plotTheme(), baseLayout(), file colours
    cofactor.js        the Transform stage's cofactor in words: a run's transform read as the
                       package reads it, and readers that take one cofactor or one per channel
                       (cofactorFor, cofactorTag, transformText, cofactorWhy, cofactorRows),
                       auto's cofactors and SDs as whole numbers, as the server's text prints them
                       (fmtCofactor)
    datasets.js        the FCS uploads grouped by their set of colour channels (groupDatasets,
                       datasetKey), and the words for what one lacks or adds against another and
                       for stains that differ (diffText, stainText, newDatasetNotes)
    dom.js, format.js, forms.js, icons.js, menu.js
    styles/            tokens.css, base.css, components.css, forms.css
  features/<name>/     index.js (exports mount), its other parts, <name>.css
  vendor/              Plotly, unchanged
  fixtures/            recorded API responses for ?fixtures=1, generated, never edited directly
  tools/               build_fixtures.py and its parts in fixturegen/
```

## Feature map

| Feature | Owns |
|---|---|
| `shell` | the frame: titlebar menus, crumbs, the editor that draws the active tab's view, status bar, narrow-screen drawer, keyboard |
| `theme` | the titlebar theme button |
| `explorer` | the side tree: Start, the FCS uploads by dataset (a mark on one whose stains differ, and a name typed in place), gates, flow runs and live jobs; a delete button on each file and gate ([deleting.md](../app/deleting.md)) |
| `tabs` | the tab strip and its "+" menu |
| `terminal` | the bottom panel: the open tab's Output and the session's Activity log |
| `start` | the Start tab: steps (Live cells is named only while a part is in slot `gate.livecells`, as the picker does), drop zone, demo data |
| `run-locally` | the "Run it locally" tab |
| `upload` | the uploader (chooser, drops, progress; FCS files only, known by their header whatever their name, which it reads before sending a file; a toast for each dataset a batch makes while another is there) and the upload tab with its dataset and channels; owns slot `upload.fcs` |
| `gate` | the "Find populations" form in slot `upload.fcs`, which offers only the opened file's dataset, and the gate's full figure tab |
| `population-picker` | a finished gate's steps: populations and groups, then whatever part is in slot `gate.livecells`, then the Transform and Scale stages (the cofactor on Auto by default, which picks one per channel from the run's cells when it starts, so the form shows the rule rather than a number; a typed number applies to every channel, and "Use auto" goes back), the cluster settings and Cluster; owns slot `gate.livecells` |
| `live-cells` | the Live cells step, as the part in slot `gate.livecells`: a marker-channel dropdown per row (viability dye, CD45, and any added with "Add a channel"), a histogram per row with a line to click, drag or type, the counts that pass, and the row filters it hands the cluster settings. Without it the picker goes from populations straight to Cluster |
| `jobs` | polling every queued or running job, and the job tab |
| `plot` | one run's nuggets or cells in 2D, 3D, pairs or parallel coordinates, with toolbar and inspector, the point card (a clicked point's values as plotted and in the file's units), and the bar under the canvas that opens a cluster's box plots (`EV.boxPlots`); owns slot `plot.legend` |
| `legend` | the cluster legend, as the part in slot `plot.legend` |
| `cluster-panel` | the box plots tab, `cluster:<run>` ([cluster-panel.md](../app/cluster-panel.md)), opened by `EV.boxPlots` or the + menu: one cluster's cells per group or file, each marker's box against the rest of the run's, and one marker's box per group |
| `compare` | Compare samples for flow runs; the group summary and marker differences are labelled descriptive (no significance test) |
| `files` | a run's download links and zip |
| `record` | a run's settings and run.json as JSON trees, with a flow run's Transform and Scale stages in words above them |

`main.js` lists the features in draw order: `EV.render` reaches its subscribers in the order they
mounted, so the shell's editor draws after the tree and the tabs.

## Shared interfaces

**API client.** [`shared/api/client.js`](../../app/web/shared/api/client.js) has one method per
endpoint the web calls, with JSDoc typedefs for the fields it reads. `shared/api/index.js` picks
the transport once: `live.js` (the server under `/api/v1`) or, with `?fixtures=1` or
`localStorage["dn-fixtures"] = "1"`, `fixtures.js`, which reads `fixtures/<METHOD>__<path>.json`.
Features import `api` and never build a URL or choose a transport.

**Store.** [`shared/store.js`](../../app/web/shared/store.js) holds `S`: what the server said
(config, workspace), which tabs are open, and per-tab view state. Features read and write it
directly. Payloads (plot, cells, compare, manifest, gate) are fetched through its cached getters, so
two tabs of one run share one download. A workspace made before the app was flow only can still
hold CSV uploads and general runs and jobs, which the server still lists (contract section 3.4);
features list and count only what `fcsUploads()`, `flowRuns()` and `flowJobs()` return. Every tab
opens through `EV.openTab`, where the tabs feature refuses a key for an item the workspace holds
but those leave out, with a toast and a line in the Activity log. The upload tab refuses a CSV
upload it fetches in the same words. The store's `deleteUpload(uid)` and `deleteGate(gid)` send
the DELETE, drop the item from the workspace (and a gate from the gate cache) and close its tabs,
and a reload the delete overtook leaves the item out, as one a dataset name overtook keeps the
name. The explorer asks first with `confirmDanger` in `shared/dom.js`, a dialog with the focus on
Cancel that lets no key through to the page; its optional `back()` gives the element to focus when
the one that opened it has left the page.

**Datasets.** A gate takes files from one dataset: the FCS uploads whose colour channels are one
set ([docs/app/contract.md](../app/contract.md#33-uploads) section 3.3). The store's
`datasets()` groups `fcsUploads()` with [`shared/datasets.js`](../../app/web/shared/datasets.js)
and `datasetOf(uid)` finds an upload's. A dataset's name is the one `S.ws.datasets` gives its
channel set, else "Dataset N" by first upload; a rename goes through the store's `nameDataset`,
which sends POST /datasets and keeps the names the server answers with, never the typed text, even
when a workspace reload is on its way at the same time. In fixture mode `fixtures.js` answers
POST /datasets itself, with the server's checks and words, and keeps the names until the page
reloads. At the cap on names it removes those of the sets that neither the recorded workspace's
uploads nor the files read in the tab have, as the server does with its uploads.

**Events.** Features tell each other about changes only with `emit(EV.<name>, payload)` and
`subscribe(EV.<name>, f)`. Every name and its payload typedef is declared in
[`shared/events.js`](../../app/web/shared/events.js); read the list there.

**Views and slots.** [`shared/views.js`](../../app/web/shared/views.js) lets a feature put UI on
another feature's screen without importing it. `registerView(kind, view)` claims a tab kind (tab
keys look like `kind:id`); the shell draws whichever view the active tab names. `registerSlot(name,
part)` adds a part to a named slot; the feature that owns the slot draws every part registered for
it and documents what a part must provide.

**Styles.** `shared/styles/tokens.css` defines the colour, type and spacing tokens: the light paper
theme on `:root` and the dark theme under `[data-theme="dark"]`. Feature stylesheets build on the
tokens. The order of the `<link>` tags in `index.html` is the cascade order: shared styles first,
then each feature's.

**Plots.** Plotly takes colours as values, not CSS, so the chrome of every figure (fonts, axis and
grid lines, hover labels, 3D panes, the sequential and diverging scales) comes from the `--plot-*`
tokens through [`shared/plot-base.js`](../../app/web/shared/plot-base.js): `plotTheme()` reads them
for the current theme and `baseLayout(T)` gives a layout with transparent backgrounds over the
container's `--plot-bg`. Data colours stay the payload's; a mark the user places (the Live cells
line) takes `--accent`. A feature that draws Plotly builds its layout from `plotTheme()` and
redraws on `EV.themeChange`.

**Steps.** A screen that walks through steps ends with the shared `.step-bar` from
`components.css`: what the user has chosen so far, why the next step is held, and the Back, Skip
and Continue buttons.

**Theme.** The first load is light whatever the OS prefers. The toggle switches to dark and back
and stores the choice in `localStorage["dn-theme"]`; `shared/theme-boot.js`, a classic script in
`<head>`, applies a stored dark choice before the first paint. A switch emits `EV.themeChange`.

## Adding a feature

1. Make `features/<name>/` with an `index.js` that exports `mount()`. `mount()` registers the
   feature's views or slot parts, subscribes to the events it needs and wires its fixed controls
   in `index.html`; the first full draw comes from `EV.render` once the workspace has loaded.
2. Put the feature's other parts beside `index.js`, and its stylesheet in `<name>.css`, written
   against the tokens. Link the stylesheet in `index.html` after the shared styles.
3. Import the feature in `main.js` as `import * as <name> from './features/<name>/index.js'` and
   add it to `FEATURES` where it should draw.
4. Talk to other features only through the store, the events and the view registry. A new event
   gets its name and payload typedef in `shared/events.js`; it needs a sender and a listener.
5. Call the server only through `api`. A new endpoint gets a method and typedef in
   `shared/api/client.js`, and fixtures written by a part in `tools/fixturegen/` from a real run
   on public data, listed in `fixtures/index.json` by `tools/build_fixtures.py`.
6. Run the boundary test, then load the page at `?fixtures=1` at 1440 and 390 px in both themes
   with zero console errors.

## Boundary rules and their test

`app/tests/architecture/test_web_boundaries.py` reads every module outside `vendor/`, `fixtures/`
and `tools/` and fails when:

- a module in `features/<a>/` imports anything outside `features/<a>/` and `shared/`;
- a module in `shared/` imports anything outside `shared/`;
- a module other than `main.js` imports a feature, `main.js` imports a feature's inner module
  instead of its `index.js`, or a feature is not imported and listed in `FEATURES`;
- a feature has no `index.js` exporting `mount()`, or `index.html` loads a module other than
  `main.js`;
- an import specifier is not relative or does not name a file in `app/web` with its exact case;
- an `emit()` or `subscribe()` names anything but an `EV.<name>` declared in `shared/events.js`, or
  a declared event has no sender or no listener;
- a stylesheet is not linked exactly once, or a shared stylesheet is linked after a feature's.

It uses only the standard library and fails closed: a line starting with `import` that it cannot
parse, or an `import()` of a computed specifier, is a failure, not a pass. Run it with the app's
other tests:

```
uv run --project app pytest app/tests/architecture -q
```
