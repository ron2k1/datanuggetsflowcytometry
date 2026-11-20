"""The four argument checks the flow copies from the library's private _validate: check_choice,
as_real, as_count and check_n_jobs. Their messages are asserted word for word here, because the
copies get no pin against the library, whose _validate module the flow may not import."""

import numpy as np
import pytest

from datanuggets_flow._validate import as_count, as_real, check_choice, check_n_jobs


def _message(error, fn, *args) -> str:
    with pytest.raises(error) as e:
        fn(*args)
    return str(e.value)


def test_check_choice_returns_the_value_or_names_every_choice():
    assert check_choice("disc", "fixed", ("reference", "fixed")) == "fixed"
    got = _message(ValueError, check_choice, "disc", "mirror", ("reference", "fixed"))
    assert got == "disc must be one of 'reference', 'fixed', got 'mirror'"


def test_as_real_takes_real_numbers_and_refuses_bools_and_text():
    assert as_real("t", 3) == 3.0 and isinstance(as_real("t", 3), float)
    assert as_real("t", np.float32(0.5)) == 0.5
    assert _message(TypeError, as_real, "t", True) == "t must be a number, got bool"
    assert _message(TypeError, as_real, "t", "3") == "t must be a number, got str"
    assert _message(TypeError, as_real, "t", None) == "t must be a number, got NoneType"


def test_as_count_takes_whole_numbers_from_one():
    assert as_count("n_row", 11) == 11
    assert as_count("n_row", 11.0) == 11 and isinstance(as_count("n_row", 11.0), int)
    assert _message(ValueError, as_count, "n_row", 2.5) == (
        "n_row must be a whole number >= 1, got 2.5"
    )
    assert _message(ValueError, as_count, "n_row", 0) == "n_row must be a whole number >= 1, got 0"
    assert _message(TypeError, as_count, "n_row", False) == "n_row must be a number, got bool"


@pytest.mark.parametrize("n_jobs", [1, 4, -1])
def test_check_n_jobs_takes_a_positive_int_or_minus_one(n_jobs):
    assert check_n_jobs(n_jobs) == n_jobs


@pytest.mark.parametrize(
    ("n_jobs", "shown"), [(0, "0"), (-2, "-2"), (True, "True"), (2.0, "2.0"), ("4", "'4'")]
)
def test_check_n_jobs_refuses_anything_else(n_jobs, shown):
    got = _message(ValueError, check_n_jobs, n_jobs)
    assert got == f"n_jobs must be a positive int or -1, got {shown}"
