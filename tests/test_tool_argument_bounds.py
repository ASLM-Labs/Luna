from __future__ import annotations

import pytest

from luna.tools.arguments import ToolArgumentError, validate_tool_arguments
from luna.tools.models import ToolArgumentRule, ToolArgumentType, ToolSpec


def _number_spec() -> ToolSpec:
    return ToolSpec(
        name="test.number",
        description="Bounded numeric argument",
        argument_schema={
            "value": ToolArgumentRule(
                argument_type=ToolArgumentType.NUMBER,
                required=True,
                minimum=0.0,
                maximum=1.0,
            )
        },
    )


def test_number_bounds_accept_int_and_float() -> None:
    spec = _number_spec()
    validate_tool_arguments(spec, {"value": 0})
    validate_tool_arguments(spec, {"value": 0.5})
    validate_tool_arguments(spec, {"value": 1.0})


@pytest.mark.parametrize("value", (True, False, -0.1, 1.1, None, ["0.5"]))
def test_number_bounds_reject_invalid_values(value: object) -> None:
    spec = _number_spec()
    with pytest.raises(ToolArgumentError):
        validate_tool_arguments(spec, {"value": value})  # type: ignore[dict-item]
