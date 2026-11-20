"""Argument checks the flow shares with the library, copied from its private _validate word for
word: check_choice, as_real, as_count and check_n_jobs. tests/flow/test_flow_validate.py holds their
messages."""

from __future__ import annotations

import numbers


def check_choice(name: str, value, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(map(repr, choices))}, got {value!r}")
    return value


def as_real(name: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    return float(value)


def as_count(name: str, value) -> int:
    v = as_real(name, value)
    if not v.is_integer() or v < 1:
        raise ValueError(f"{name} must be a whole number >= 1, got {value!r}")
    return int(v)


def check_n_jobs(n_jobs) -> int:
    """joblib's n_jobs: a positive int, or -1 for every core."""
    if isinstance(n_jobs, bool) or not isinstance(n_jobs, int) or n_jobs == 0 or n_jobs < -1:
        raise ValueError(f"n_jobs must be a positive int or -1, got {n_jobs!r}")
    return n_jobs
