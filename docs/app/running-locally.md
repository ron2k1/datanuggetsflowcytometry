# Running the datanuggets-flow app locally

The app is one Docker image: the web page, the API and the `datanuggets-flow` package. On your
own computer it runs in `local` mode. In that mode there is no login and nothing expires. Uploads, events and runs have no caps. A few bounds stay: at most 100 clusters,
and the cells a run samples for the plot stop at 5,000 per file and 200,000 in all. The live
cells view takes 8 to 512 bins and keeps 8 sets per gate, dropping the oldest finished one for a
new one. A workspace keeps at most 100 dataset names, each at most 60 characters (contract section
3.3). Every upload and run is a file in a Docker volume on your disk, and nothing is sent
anywhere.

## Run it

You need Docker (Docker Desktop on Windows and macOS). Each release is published as an image
for linux/amd64 and linux/arm64:

```sh
docker run --rm -p 127.0.0.1:8000:8000 -v datanuggets-data:/data ghcr.io/ron2k1/datanuggets-flow:<version>
```

`<version>` is one of the versions on the image's
[package page](https://github.com/ron2k1/datanuggetsflowcytometry/pkgs/container/datanuggets-flow).
It is the release's [tag](https://github.com/ron2k1/datanuggetsflowcytometry/tags) without its
leading `v` (tag `v0.2.0` is image `0.2.0`). The app's "Run it locally" entry shows this command
with its own version filled in. `:latest` names the newest final release once there is one. A
prerelease such as `0.1.0a3` never becomes `latest`, so during the alpha name the version. A version also
keeps you on the app you know.

Then open <http://127.0.0.1:8000>. `Ctrl+C` stops it, and the next `docker run` with the same
`-v datanuggets-data:/data` finds your uploads and runs where you left them. Every command on
this page publishes the port on 127.0.0.1, so other machines on your network cannot reach the
app. That matters because local mode has no login.

To update, run the same command with the new version. The image is replaced and the volume,
with your files in it, stays.

### Build it from the source

Docker can build any release straight from its tag on GitHub, with no clone:

```sh
docker build -t datanuggets-flow https://github.com/ron2k1/datanuggetsflowcytometry.git#v<version>
docker run --rm -p 127.0.0.1:8000:8000 -v datanuggets-data:/data datanuggets-flow
```

From a clone, `docker build -t datanuggets-flow .` builds the checkout you have.

The build downloads the PBMC demo files from Zenodo and checks each one's sha256, so the build
fails rather than ship a changed file. The build needs internet access for those files and for
the Python wheels. Running the app does not: the page and Plotly are served from the image, so
it works offline.

### With Docker Compose

`compose.yaml` at the repository root builds the checkout and runs it the same way, with the
port bound to 127.0.0.1:

```sh
docker compose up --build        # http://127.0.0.1:8000
docker compose down              # stop, and the volume and your files stay
docker compose down --volumes    # stop and delete every upload and run
```

Set `PORT=8080` to publish on another host port (`PORT=8080 docker compose up`).

## Where your data lives

The image keeps everything under `/data`, which is a volume:

| Path in the container | Holds |
|---|---|
| `/data/ws/local/uploads/` | the files you uploaded or loaded from a demo |
| `/data/ws/local/gates/` | flow gating results |
| `/data/ws/local/runs/` | each run's folder: the CSV tables, figures and `run.json` that the `datanuggets-flow` command writes |
| `/data/ws/local/jobs/` | one JSON record and log per job |

With a named volume (`-v datanuggets-data:/data`), Docker keeps the files in its own storage on
your disk. They survive container restarts and image rebuilds, and they are gone only when you
delete the volume (`docker volume rm datanuggets-data`). To copy a run out, use the download
buttons in the app, or:

```sh
docker run --rm -v datanuggets-data:/data -v "$PWD":/out busybox cp -r /data/ws/local/runs /out/
```

To keep the files in a folder you choose, bind-mount it. The container runs as user 10001, not
root, so that user must be able to write the folder. On Linux, either give the folder to that
user or run as yourself:

```sh
mkdir -p dn-data
docker run --rm -p 127.0.0.1:8000:8000 -v "$PWD/dn-data:/data" --user "$(id -u):$(id -g)" ghcr.io/ron2k1/datanuggets-flow:<version>
```

## Settings

All settings are environment variables (`-e NAME=value` on `docker run`, or `environment:` in
`compose.yaml`). The image sets the first group itself.

| Variable | Image default | Meaning |
|---|---|---|
| `DN_MODE` | `local` | `local` (your computer) or `trial` (the hosted trial, see below) |
| `HOST` | `0.0.0.0` | bind address inside the container |
| `PORT` | `8000` | port inside the container; publish it with `-p <host port>:8000` |
| `DN_DATA_DIR` | `/data` | workspaces and job files |
| `DN_WEB_DIR`, `DN_DEMO_DIR` | `/app/app/web`, `/app/app/demo` | the page and the demo files in the image |
| `DN_WORKERS` | local: min(2, CPUs); trial: 1 | jobs that run at the same time |
| `DN_JOBS` | local: -1 (all cores); trial: 1 | parallel jobs inside one analysis |
| `DN_COOKIE_SECURE` | `0` | `1` adds `Secure` to the trial cookie (set it behind HTTPS) |
| `DN_TRUST_PROXY` | `0` | `1` takes the client address from `X-Real-IP` (only behind a proxy you run) |
| `DN_DOCKER_COMMAND` | the image command above, at this version | the run command "Run it locally" shows |
| `DN_ALLOWED_HOSTS` | empty | more host names the app answers, comma-separated, or `*` for any |

`docs/app/contract.md` has the full list and every trial cap.

Local mode answers only requests addressed to `localhost`, `127.0.0.1` or `[::1]`. Any other
name in the request's `Host` header gets a 400 `invalid_host` error. That stops a page on
another site from pointing its own name at your computer and reaching the app, which has no
login. To open it from another machine on purpose, publish the port on that interface and list
the name or address you will type. For a computer at 192.168.1.20 on your network, run the
command in [Run it](#run-it) with `-p 192.168.1.20:8000:8000 -e DN_ALLOWED_HOSTS=192.168.1.20`
in place of `-p 127.0.0.1:8000:8000`, then open <http://192.168.1.20:8000> on the other
machine. Anyone who can reach that address can then use the app. `DN_ALLOWED_HOSTS` takes more
than one name, comma-separated, such as `192.168.1.20,dn.lan`, and a port in an entry is
ignored.

## Trial mode

`DN_MODE=trial` is the hosted trial. The same image runs it with different rules:

- No login. The first visit creates an anonymous workspace, tied to an `HttpOnly`,
  `SameSite=Strict` cookie.
- A workspace is deleted 6 hours after its last use, and 24 hours after it was created at the
  latest. The app says so: "Files stay in a temporary workspace and are deleted within 24 hours.
  Do not upload identifiable patient data."
- Caps on upload size, events, nuggets, clusters, runs per workspace, and jobs per IP
  address per hour, plus a 15-minute limit per job. `GET /api/v1/config` lists them.
- Trial workspaces live in `/data/trial`, and each trial start empties that folder. The expiry
  above runs only while the container runs. The command below has `--rm` and no `-v`, so Docker
  deletes the container's `/data` along with the container when it stops. On a named volume, as
  `DN_MODE=trial docker compose up` uses, a trial's files stay after the container stops, until
  the next trial start. Local mode's files in `/data/ws/local` are left alone, so a trial start
  on the same volume does not delete them.

To try trial mode on your own computer:

```sh
docker run --rm -p 127.0.0.1:8001:8000 -e DN_MODE=trial ghcr.io/ron2k1/datanuggets-flow:<version>
```

On a public host, put it behind an HTTPS reverse proxy and set `DN_COOKIE_SECURE=1`. Set
`DN_TRUST_PROXY=1` only when that proxy sets `X-Real-IP`; otherwise every visitor shares the
proxy's address and the per-IP limits. Trial mode answers any host name by default, since only
you know the proxy's. Set `DN_ALLOWED_HOSTS` to that name to refuse the others.

## Demo data

The demos list in the app comes from `app/demo/manifest.json`, and each demo's card shows its
license, source and attribution from there:

| Demo | Size | License and source |
|---|---|---|
| PBMC spectral flow | 4 FCS files (190, 193, 199, 223), 193,293 events | CC BY 4.0. Stefanie Kreutmair and Susanne Unger (2026), *Flow cytometry data of PBMC of critically ill, mechanically ventilated patients* (V1), Zenodo, [doi:10.5281/zenodo.22079206](https://doi.org/10.5281/zenodo.22079206). The files are unmodified, and their use does not imply endorsement. |

The FCS files are not in the repository. They are downloaded when the image is built, by
`app/scripts/fetch_demos.py`, which checks each file's size and sha256 against the manifest. To
get them for a run outside Docker:

```sh
python app/scripts/fetch_demos.py            # fetch what is missing, check everything
python app/scripts/fetch_demos.py --check    # check only
```

### Large set (over 1 million events), on demand

One larger public set is listed in `app/demo/large.json`. It is never part of the image or the
repository. Download it where you will analyse it, then upload the files in the app (local mode
has no size caps):

```sh
python app/scripts/fetch_demo_large.py --set nkg2a     # 9 FCS files, 1,364,975 events, 196.6 MB
```

Files land in `tmp/demo-large/<set>/` and each is checked against the size and sha256 recorded
there.

- `nkg2a`: CC BY 4.0. Wolfgang Merkt (2026), *Spectral Flow Cytometry Data of Targeting the NK
  cell checkpoint NKG2A promotes lung fibrosis resolution by enhancing immune clearance of
  senescent myofibroblasts*, Zenodo,
  [doi:10.5281/zenodo.18367404](https://doi.org/10.5281/zenodo.18367404). The 9 healthy-donor
  PBMC files, unmodified.

## Licenses in the image

The app's own code is GPL-2.0-only, the license kept in the image as `/app/LICENSE`, and
`/app/THIRD_PARTY.md` credits the upstream work it builds on. The image also bundles the Python
packages the app depends on, each under its own license. The build lists every one of them in
`/app/python-package-licenses.txt` with its version, the license it declares and the paths of
the license files it ships. To read the list:

```sh
docker run --rm ghcr.io/ron2k1/datanuggets-flow:<version> cat /app/python-package-licenses.txt
```

The build stops if a package declares no license and ships no license file, so the list covers
every package.

The base image is `python:3.12-slim`, pinned by digest in the `Dockerfile`, and its system
packages come from Debian. Each one's license is in `/usr/share/doc/<package>/copyright`. To get
the source of the exact versions in an image, list them:

```sh
docker run --rm ghcr.io/ron2k1/datanuggets-flow:<version> dpkg-query -W -f '${source:Package} ${source:Version}\n' | sort -u
```

[snapshot.debian.org](https://snapshot.debian.org/) keeps every version Debian has published, so
each one's source stays available at `https://snapshot.debian.org/package/<source>/<version>/`
after Debian moves on.

The image carries OCI labels with its version, the commit it was built from, the source
repository and `GPL-2.0-only`. `docker inspect` shows them.

## How the image is checked

`.github/workflows/app.yml` builds the image on every pull request and every push to `main` that
touches the app, the package or the Docker files. It builds natively on an amd64 runner and on an arm64 runner, and both jobs must pass. Each runs the
container in local mode and in trial mode, and `app/scripts/smoke.py` (standard library only)
checks each one. The checks cover health, config, the page's security headers, the trial cookie,
loading the PBMC demo, gating its files, a small flow run from that gate to completion, the run's
plot and cells payloads, its files list, one of its files and its zip. The workflow also checks
the image's settings and labels and the license list. It checks that the page's development
fixtures and tests are not in the image, and that the image built with no `.dockerignore`, as a
build from a git URL is, holds the same files. It checks that local mode answers 400 to a
foreign `Host` name. It restarts the local container on the same volume and checks that the
gate and the run are still there, then starts trial mode on that volume and checks that the
local runs survive. That workflow pushes nothing to a registry. The release workflow runs it
too, so no version reaches PyPI with an image that fails these checks.

Releases are published by `.github/workflows/image.yml`. Pushing a tag `v<version>` that matches
the version in `pyproject.toml`, on a commit that is already on `main`, starts the release
workflow, and once that version is on PyPI it runs `image.yml`. That builds the image for
linux/amd64 and linux/arm64, with provenance and an SBOM attached. It pushes the image to
`ghcr.io/ron2k1/datanuggets-flow` by digest, with no tag yet. The workflow pulls that digest back on
an amd64 runner and on an arm64 runner and runs the same smoke test against each. Only when both
pass does it tag the image `<version>` and `sha-<commit>`, so a version you pull has passed the
smoke test. `latest` moves to it as well when it is a final release above the version `latest`
names in the registry at that moment. A version the registry already has is never moved to
another image.

Shipping an update is a release like any other. Bump the version in `pyproject.toml`, refresh
`uv.lock`, `app/uv.lock` and the `/config` fixtures as
[Releasing](../releasing.md#test-a-release-candidate) lists, merge to `main` and push the tag.
People running the app get the update by running the command above with the new version, and
their volume keeps their files.

To run the same smoke test against any running copy:

```sh
python app/scripts/smoke.py --base-url http://127.0.0.1:8000 --mode local
```

It loads the PBMC demo, so a copy run from a checkout rather than the image needs the FCS files
from `app/scripts/fetch_demos.py` first (see [Demo data](#demo-data)).
