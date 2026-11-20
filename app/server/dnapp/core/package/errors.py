"""The package's refusals as the API sends them. A FlowError names its setting by the CLI flag;
the API names it by its JSON field instead, so the message and param match the request body."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from dnapp.core.errors import ApiError


def refusal(e: BaseException) -> ApiError | None:
    """e as invalid_setting when it is the package refusing a setting; None otherwise."""
    from datanuggets_flow.exceptions import FlowError

    if isinstance(e, FlowError):
        return ApiError("invalid_setting", e.cli(lambda name: name), e.param)
    return None


@contextlib.contextmanager
def refusals() -> Iterator[None]:
    """Turns the package refusing a settings dict into invalid_setting: its FlowError, or the
    TypeError a dataclass raises for a field it does not have."""
    try:
        yield
    except TypeError as e:
        raise ApiError("invalid_setting", str(e)) from None
    except Exception as e:
        err = refusal(e)
        if err is None:
            raise
        raise err from None
