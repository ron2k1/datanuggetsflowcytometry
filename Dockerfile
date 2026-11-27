# The datanuggets-flow app: the FastAPI backend, the static page and the datanuggets-flow package,
# in one image. DN_MODE=local (the default) keeps every file in the /data volume with no caps on
# uploads or runs, and DN_MODE=trial is the hosted trial (anonymous workspaces, caps, expiry).
#
#   docker build -t datanuggets-flow .
#   docker run --rm -p 127.0.0.1:8000:8000 -v datanuggets-data:/data datanuggets-flow
#
# Releases are built for linux/amd64 and linux/arm64 and pushed to ghcr.io/ron2k1/datanuggets-flow
# by .github/workflows/image.yml. The build context is the repo root. .dockerignore lets in only
# what is copied below, but a build from a git URL (docs/app/running-locally.md) gets the whole
# tree with no .dockerignore, so the runtime stage names what it takes and leaves the page's
# fixtures and tools and the server's tests behind on its own. No secrets are read at build or
# run time.
#
# Both base images are pinned by multi-arch index digest, written out in the FROM lines so that
# Dependabot (.github/dependabot.yml) can propose new digests. Bump them on purpose.

FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv

# python:3.12-slim is Debian based. docs/app/running-locally.md says where the source of its
# Debian packages is.
FROM python:3.12-slim@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f AS base

FROM base AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app

# 1. Third-party dependencies from app/uv.lock only: this layer is rebuilt when a manifest or
#    the lock changes, not on every source edit. numba, llvmlite and scipy install as wheels, so
#    no compiler is needed.
COPY pyproject.toml README.md LICENSE THIRD_PARTY.md ./
COPY app/pyproject.toml app/uv.lock app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project app --locked --no-dev --no-install-project --no-install-local

# 2. Demo data: the PBMC FCS files are downloaded from Zenodo and sha256-checked (a mismatch
#    fails the build). The 1M+ sets are never fetched here.
COPY app/demo/ app/demo/
COPY app/scripts/fetch_demos.py app/scripts/
RUN python -I app/scripts/fetch_demos.py --demo-dir /app/app/demo

# 3. The package and the app, installed into the venv (not editable, so the runtime stage needs
#    neither src/ nor the build tools).
COPY src/ src/
COPY app/server/ app/server/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project app --locked --no-dev --no-editable

# 4. The license of every Python package in the venv, kept in the image as
#    /app/python-package-licenses.txt. --strict fails the build for a package that declares no
#    license and ships no license file.
COPY app/scripts/list_licenses.py app/scripts/
RUN /opt/venv/bin/python -I app/scripts/list_licenses.py --strict --out /app/python-package-licenses.txt

# 5. The server code the runtime stage copies, without each feature's tests.
RUN find app/server -type d -name tests -prune -exec rm -rf {} +

FROM base AS runtime
# NUMBA_CACHE_DIR and MPLCONFIGDIR: writable caches for the non-root user (site-packages is
# read-only to it). PYTHONPATH keeps `python -m dnapp` working whether or not the app project
# installs dnapp as a package.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/app/server \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    NUMBA_CACHE_DIR=/tmp/numba \
    HOST=0.0.0.0 \
    PORT=8000 \
    DN_MODE=local \
    DN_DATA_DIR=/data \
    DN_WEB_DIR=/app/app/web \
    DN_DEMO_DIR=/app/app/demo

RUN groupadd --gid 10001 dn \
 && useradd --uid 10001 --gid dn --no-log-init --create-home --home-dir /home/dn --shell /usr/sbin/nologin dn \
 && mkdir -p /data \
 && chown dn:dn /data

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app/app/demo /app/app/demo
COPY --from=build /app/python-package-licenses.txt /app/
COPY --from=build /app/app/server /app/app/server
# the page: only what the app serves, not app/web/fixtures or app/web/tools
COPY app/web/index.html app/web/main.js /app/app/web/
COPY app/web/features/ /app/app/web/features/
COPY app/web/shared/ /app/app/web/shared/
COPY app/web/vendor/ /app/app/web/vendor/
COPY LICENSE THIRD_PARTY.md /app/

WORKDIR /app
USER dn:dn
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import os, sys, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('PORT', '8000'), timeout=4); sys.exit(0 if r.status == 200 else 1)"]

CMD ["python", "-m", "dnapp"]

# OCI labels, last so that a new revision changes no layer. image.yml passes the version (from
# pyproject.toml) and the commit, and a plain local build leaves both empty. licenses names the
# app's own license, and /app/python-package-licenses.txt lists every bundled package's.
ARG DN_VERSION=""
ARG DN_REVISION=""
LABEL org.opencontainers.image.title="datanuggets-flow" \
      org.opencontainers.image.description="The datanuggets-flow web app: gate flow cytometry (FCS) files and cluster the populations you pick." \
      org.opencontainers.image.source="https://github.com/ron2k1/datanuggetsflowcytometry" \
      org.opencontainers.image.url="https://github.com/ron2k1/datanuggetsflowcytometry" \
      org.opencontainers.image.documentation="https://github.com/ron2k1/datanuggetsflowcytometry/blob/main/docs/app/running-locally.md" \
      org.opencontainers.image.licenses="GPL-2.0-only" \
      org.opencontainers.image.version="${DN_VERSION}" \
      org.opencontainers.image.revision="${DN_REVISION}"
