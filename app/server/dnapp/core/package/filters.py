"""datanuggets.filters: a row filter's JSON read the way the package reads it."""

from __future__ import annotations

from collections.abc import Mapping


def row_filter(f: Mapping):
    """A RowFilter for a filter's JSON, its spec parsed back as the package reads it, so a bad
    one raises the package's ValueError here."""
    from datanuggets.filters import RowFilter, format_filter, parse_filter

    value = f["value"]
    if isinstance(value, list):
        value = tuple(value)
    return parse_filter(format_filter(RowFilter(column=f["column"], op=f["op"], value=value)))


def filter_spec(f: Mapping) -> str:
    """The canonical spec string the flow CLI and ClusterSettings take."""
    from datanuggets.filters import format_filter

    return format_filter(row_filter(f))
