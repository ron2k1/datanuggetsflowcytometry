# Releasing

Merging a pull request publishes nothing. A release goes out only when a maintainer runs the release workflow with TestPyPI selected or pushes a `v*` tag. The tag publishes the package to PyPI as `datanuggets-flow` and the app's image to `ghcr.io/ron2k1/datanuggets-flow`.

## What the workflows do

`.github/workflows/release.yml` publishes the package. Its first job requires the commit to be on `main`, and a tag to match the version in `pyproject.toml`, for example `v0.1.0a3` for version `0.1.0a3`. It then runs `tests.yml`, `matrix.yml`, `package.yml` and `app.yml`, which [development.md](development.md#what-ci-runs) describes. Only when all four pass does it upload the files `package.yml` built and checked.

- A manual run defaults to `destination: check`, which builds and tests the candidate without uploading it.
- A manual run with `destination: testpypi` uploads it to TestPyPI through the `testpypi` environment.
- A pushed `v*` tag uploads it to PyPI through the `pypi` environment, after `check_dist.py --expect-version` confirms the files carry the tag's version.

Both indexes use [Trusted Publishing](https://docs.pypi.org/trusted-publishers/), so the repository stores no API token. The publishing action creates provenance attestations by default. They name the repository, workflow and commit publicly.

After the PyPI upload, `release.yml` runs `image.yml`. It builds the image for linux/amd64 and linux/arm64 and pushes it by digest alone. It smoke-tests that digest on both architectures, and only then tags it with the version and `sha-<commit>`. `latest` moves only to a final version above the one `latest` already names, so a pre-release such as `0.1.0a3` never becomes `latest`. It signs in with the workflow's own `GITHUB_TOKEN`. [Running the app locally](app/running-locally.md) describes the image.

## One-time setup

These live in the GitHub and index settings, not in the committed files.

1. **Rulesets.** Protect `main` with a branch ruleset that requires a pull request and the checks of `tests`, `matrix` and `package`. Leave `app` out, since it runs only on pull requests that touch the app, the package or the Docker files. Add a tag ruleset on `v*` that restricts creation, updates and deletion to repository admins.
2. **Environments.** In Settings > Environments, create `testpypi`, limited to the branch `main`, and `pypi`, limited to tags matching `v*`. Add yourself as a required reviewer in both.
3. **Trusted publishers.** On [TestPyPI](https://test.pypi.org/manage/account/publishing/) and on [PyPI](https://pypi.org/manage/account/publishing/), add a publisher with these values:

   | Field | TestPyPI | PyPI |
   | --- | --- | --- |
   | Project name | `datanuggets-flow` | `datanuggets-flow` |
   | Owner | `ron2k1` | `ron2k1` |
   | Repository | `datanuggetsflowcytometry` | `datanuggetsflowcytometry` |
   | Workflow | `release.yml` | `release.yml` |
   | Environment | `testpypi` | `pypi` |

4. **Container visibility.** The first tag run of `image.yml` creates the `datanuggets-flow` package under `ron2k1`, and GitHub makes it private. Make it public once, from the package's settings. Check there that it's connected to the `ron2k1/datanuggetsflowcytometry` repository.

Keep the upstream notices and the dataset attribution in both archives and in the image. [Third-party notices](../THIRD_PARTY.md) record the permissions.

## Test a release candidate

1. Update `project.version` in `pyproject.toml`. Then, from the repository root, refresh both lock files and the app fixtures that carry the version:

   ```sh
   uv lock
   uv lock --project app
   uv run --project app python app/web/tools/build_fixtures.py --config-only --out app/web/fixtures
   ```

   `uv.lock` and `app/uv.lock` each record the package's version. The image installs with `uv sync --locked`, so a stale `app/uv.lock` fails its build. The last command rewrites the `/config` fixtures, whose run commands name the version. In `CITATION.cff`, set `version` to the release version and `date-released` to the day the tag is pushed. `tests/scripts/test_citation.py` fails while `version` differs from `project.version` in `pyproject.toml`. Merge the version, both lock files, the fixtures, `CITATION.cff`, [releases.md](releases.md) and the README together to `main`. The README is embedded in the package metadata, so an edit after upload can't repair that release's PyPI page.
2. In GitHub Actions, select release > Run workflow > main > check. Review the checks. Then run it again with testpypi and approve the `testpypi` deployment. Record the full commit hash of that run.
3. In a fresh environment, download the exact wheel from TestPyPI without dependencies, then install it with its dependencies from PyPI:

   ```sh
   python -m pip download --index-url https://test.pypi.org/simple/ --no-deps --only-binary=:all: --dest tmp/testpypi "datanuggets-flow==0.1.0a3"
   python -m pip install --index-url https://pypi.org/simple/ tmp/testpypi/datanuggets_flow-0.1.0a3-py3-none-any.whl
   python -c "import datanuggets_flow; print(datanuggets_flow.__version__)"
   datanuggets-flow --help
   ```

   An `--extra-index-url` doesn't give TestPyPI priority over PyPI, so the two steps keep the candidate's source explicit.
4. Run the command on representative FCS files before you tag.

TestPyPI needs a new version for each new set of files. Bump the alpha suffix for another candidate. The image has no candidate registry. The check run builds and smoke-tests it through `app.yml`.

## Publish the tested commit

Tag the exact commit tested above and push the tag:

```sh
git switch main
git pull --ff-only origin main
git tag -a v0.1.0a3 TESTED_COMMIT_SHA -m "datanuggets-flow 0.1.0a3"
git push origin v0.1.0a3
```

The tag run rebuilds and checks its own files and waits for approval of the `pypi` deployment. It doesn't promote the TestPyPI files byte for byte. After the upload, the same run publishes the image.

Then check what went out:

1. Install the exact version in a fresh environment with `python -m pip install "datanuggets-flow==0.1.0a3"`, and check the [PyPI page](https://pypi.org/p/datanuggets-flow).
2. On the first release, make the container package public.
3. Run the published image and open <http://127.0.0.1:8000>:

   ```sh
   docker run --rm -p 127.0.0.1:8000:8000 -v datanuggets-data:/data ghcr.io/ron2k1/datanuggets-flow:0.1.0a3
   ```

Published package files can't be replaced, so fix a broken release with a new version. `image.yml` refuses to put a version the registry already has on another image. If the image jobs fail after the upload, use Re-run failed jobs on the release run. It reruns the failed jobs and the ones after them, not the upload. When the version has no image tag yet, you can also run `image.yml` on manual dispatch on the tag. It checks first that PyPI has that version.
