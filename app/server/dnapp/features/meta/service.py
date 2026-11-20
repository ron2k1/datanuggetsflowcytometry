"""The app's own version, as installed, and the "Run it locally" commands for a package version."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from dnapp.core.config import BUILD_COMMAND, IMAGE, RUN_COMMAND, SOURCE_IMAGE, SOURCE_REPO


def app_version() -> str:
    try:
        return version("datanuggets-app")
    except PackageNotFoundError:
        return "0.0.0"


def docker_commands(package_version: str, run: str | None = None) -> dict[str, str]:
    """The commands /config sends: run the published image of this version, or build the same
    version from its release tag and run that. run, from DN_DOCKER_COMMAND, replaces the first."""
    return {
        "docker_command": run or RUN_COMMAND.format(image=f"{IMAGE}:{package_version}"),
        "build_command": BUILD_COMMAND.format(
            image=SOURCE_IMAGE, repo=SOURCE_REPO, version=package_version
        ),
        "build_run_command": RUN_COMMAND.format(image=SOURCE_IMAGE),
    }
