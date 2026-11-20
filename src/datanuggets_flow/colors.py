"""The colours plot.gates draws the gate finder's populations in. Cluster colours come from the
library's datanuggets.colors."""

from __future__ import annotations

from collections.abc import Sequence

from datanuggets.colors import TAB10


def population_colors(events: Sequence[int]) -> list[str | None]:
    """The colour plot.gates draws each population in (numbered from 0), given each one's
    events, under matplotlib's default colours: the next tab10 colour for each population that has
    an event, and None for an empty one, which it doesn't draw."""
    colors, drawn = [], 0
    for n in events:
        if n > 0:
            colors.append(TAB10[drawn % len(TAB10)])
            drawn += 1
        else:
            colors.append(None)
    return colors
