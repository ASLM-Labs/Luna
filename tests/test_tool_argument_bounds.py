from __future__ import annotations

from uuid import uuid4

import pytest

from luna.tools.arguments import (
    ToolArgumentError,
    validate_tool_arguments,
)
from luna.tools.models import (
    ToolArgumentRule,
    ToolArgumentType,
    ToolRequest,
    ToolSpec,
)


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


def test_tool_request_preserves_exact_argument_string_whitespace() -> None:
    content = "  first line\nsecond line  \n"

    argv = [
        "  first",
        "second  ",
        "third\n",
    ]

    request = ToolRequest(
        task_id=uuid4(),
        trace_id=uuid4(),
        tool_name="test.arguments",
        arguments={
            "content": content,
            "argv": argv,
        },
    )

    assert (
        request.arguments["content"]
        == content
    )

    assert (
        request.arguments["argv"]
        == argv
    )



def test_exact_call_fingerprint_distinguishes_argument_whitespace() -> None:
    task_id = uuid4()

    plain = ToolRequest(
        task_id=task_id,
        trace_id=uuid4(),
        tool_name="test.arguments",
        arguments={
            "content": "after",
        },
    )

    newline = ToolRequest(
        task_id=task_id,
        trace_id=uuid4(),
        tool_name="test.arguments",
        arguments={
            "content": "after\n",
        },
    )

    assert (
        plain.arguments["content"]
        == "after"
    )

    assert (
        newline.arguments["content"]
        == "after\n"
    )

    assert (
        plain.exact_call_fingerprint()
        != newline.exact_call_fingerprint()
    )
