# Third-party notices

The package is licensed under GPL-2.0-only. The full text is in `LICENSE`.
The data described below keep their own licenses.

The datanuggets library, which this package depends on, keeps its own notices in its [THIRD_PARTY.md](https://github.com/ron2k1/datanuggets/blob/main/THIRD_PARTY.md).

## Supplied flow-analysis code

The flow-analysis implementation and its reference benchmarks adapt Python code supplied
by Prof. Javier Cabrera on 2026-10-12. The adaptations add package interfaces, validation,
CLI input/output handling and the documented gate correction.

On 2026-10-21, maintainer Ronil Basu confirmed that Prof. Cabrera's permission covers
redistribution of the supplied code and these adaptations under GPL-2.0-only.

## Release approval

On 2026-11-01, Prof. Javier Cabrera approved releasing the port publicly under
GPL-2.0-only, as the `datanuggets` package on PyPI and as a Docker image of the app.

## Flow-cytometry test data

The flow fixtures derive from:

Stefanie Kreutmair and Susanne Unger (2026). *Flow cytometry data of PBMC of critically
ill, mechanically ventilated patients* (V1). Zenodo.
[doi:10.5281/zenodo.22079206](https://doi.org/10.5281/zenodo.22079206).

The original data are licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
The derived data retain that license. Use of the data does not imply endorsement.

`tests/fixtures/flow/154.npz`, `202.npz` and `223.npz` select channels from three FCS
files, retain every sixth, fifth and first event respectively, cap each selection at
50,000 events, and convert it to NPZ. They also contain computed reference results.
`202_fluor.npz` contains three fluorescence channels for the same selected events as
`202.npz`. These fixtures are included in the source distribution, not the wheel.

## The app

The files under `app/` make up the web app and its Docker image. They are not part of either
Python archive.

### plotly.js

`app/web/vendor/plotly-3.0.1-strict.min.js` is
[plotly.js](https://github.com/plotly/plotly.js) 3.0.1, the strict bundle, vendored
unmodified. It is licensed under the MIT License, and its copyright notice and license text are
in `app/web/vendor/LICENSE-plotly.txt`, which the image also carries.

### Demo data

The image carries one demo, listed in `app/demo/manifest.json`: four FCS files, `190.fcs`,
`193.fcs`, `199.fcs` and `223.fcs`, from the Zenodo record cited under
[Flow-cytometry test data](#flow-cytometry-test-data), under the same CC BY 4.0 license. They
are downloaded unmodified while the image is built, checked against the sha256 in the manifest,
and are not in the repository.

### Derived app fixtures

`app/web/fixtures/` holds the outputs of datanuggets-flow runs on that demo, which the page serves in
place of a live server when it is opened with `?fixtures=1`: tables, samples of events, run
records and figures.
`app/web/tools/build_fixtures.py` generated them. They are adaptations of the four CC BY 4.0
FCS files and keep that license, with the attribution above. They were changed from the
originals: the events were selected, transformed and scaled, reduced to data nuggets and
clustered, and the files record those results.

### Docker image contents

The image `ghcr.io/ron2k1/datanuggets-flow` contains the plotly.js bundle and the demo above.
It leaves out the derived app fixtures, which only the page's development mode serves. It also
contains:

- The Debian-based `python:3.12-slim` image, pinned in the `Dockerfile` by its digest
  `sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f`. Each Debian
  package's license is in `/usr/share/doc/<package>/copyright` inside the image, and the source
  of every Debian package version is kept at [snapshot.debian.org](https://snapshot.debian.org/).
- The Python packages that `app/uv.lock` pins for running the app, installed in `/opt/venv`,
  datanuggets-flow and datanuggets among them. The lock's development tools, such as pytest, are
  not installed.
  Each package's license files are in its `.dist-info` folder there. The image also carries a
  generated list of those packages with their versions and licenses, which
  [Running the app locally](https://github.com/ron2k1/datanuggetsflowcytometry/blob/main/docs/app/running-locally.md#licenses-in-the-image)
  describes.
- `LICENSE` and this file, in `/app`.

The image collects these separately licensed packages, and each keeps its own license. The
GPL-2.0-only license of datanuggets-flow, datanuggets and the app covers their own code and does
not relicense any other package in the image.

Two of those packages are licensed under Apache-2.0 alone, and the app's server process loads
them: python-multipart, which parses uploads, and opentelemetry-api, which FastAPI requires. A
third, tzdata, comes in with pandas and python-dateutil and is never imported. The Free Software
Foundation considers Apache-2.0 incompatible with GPL-2.0-only code combined into one program.
On 2026-11-02 the maintainer decided to distribute the image with these packages unchanged. The
datanuggets-flow wheel and source distribution contain none of the three and do not depend on
python-multipart or opentelemetry-api. Installing datanuggets-flow can also install tzdata,
because pandas requires it on Windows and python-dateutil 3 requires it everywhere. llvmlite,
which numba loads, carries LLVM under Apache-2.0 with the LLVM exception, and that exception
allows combining it with GPL-2.0 code.

uv is used only while the image is built and is not in the final image.
