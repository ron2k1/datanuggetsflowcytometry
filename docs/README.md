# datanuggets-flow documentation

| Guide | What you will find |
| --- | --- |
| [Getting started](quickstart.md) | Installing the package, a first `datanuggets-flow` run, staged runs and the same two stages from Python |
| [Function reference](api.md) | The finder functions `datanuggets_flow` exports and the flow pipeline library: settings, stages, run records and figures |
| [Flow CLI](cli.md#fcs-pipeline) | `datanuggets-flow`: gating FCS files, choosing populations, channels, filters and groups, the Transform and Scale stages, staged runs, every flag, the output files and every failure message |
| [Limitations](limitations.md) | Memory with the tree, weighted k-means starts, what the tests cover, flow caveats and open problems |
| [Methodology](methodology.md) | The gate finder and where it departs from Cabrera's code, the pipeline's design choices, how it relates to the papers and what is tested |
| [Reproducibility](reproducibility.md) | The public dataset, the comparisons with Cabrera's script and the flow run records |
| [Running the app locally](app/running-locally.md) | Running the app's Docker image, building it from source, its modes and where your files live |
| [Development](https://github.com/ron2k1/datanuggetsflowcytometry/blob/main/docs/development.md) | Setup, tests, lint and build checks |
| [Architecture](https://github.com/ron2k1/datanuggetsflowcytometry/blob/main/docs/ARCHITECTURE.md) | The repository's layers, which way they depend on each other, the tests that hold the boundaries, and where new code goes |
| [Release notes](releases.md) | What `0.1.0a3`, the first alpha, contains |
| [Releasing](https://github.com/ron2k1/datanuggetsflowcytometry/blob/main/docs/releasing.md) | The release workflows, one-time setup, testing a release candidate and publishing the tested commit |

The data nuggets method and the weighted clustering come from the `datanuggets` library. Its [documentation](https://github.com/ron2k1/datanuggets/blob/main/docs/README.md) covers them.
