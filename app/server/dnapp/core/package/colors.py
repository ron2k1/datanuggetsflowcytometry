"""datanuggets.colors, for the colours a run's own files do not carry."""

from __future__ import annotations

from collections.abc import Sequence


def population_colors(events: Sequence[int]) -> list[str | None]:
    from datanuggets_flow.colors import population_colors as colors

    return list(colors(list(events)))
