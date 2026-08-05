"""Strict validation for the Phase 4 tool argument schema."""

from __future__ import annotations

from luna.tools.models import ToolArgumentRule, ToolArgumentType, ToolArgumentValue, ToolSpec


class ToolArgumentError(ValueError):
    """Raised when a tool request does not match its registered schema."""


def _is_integer(value: ToolArgumentValue) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: ToolArgumentValue) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)


def _validate_one(name: str, value: ToolArgumentValue, rule: ToolArgumentRule) -> None:
    argument_type = rule.argument_type
    if argument_type is ToolArgumentType.STRING:
        if not isinstance(value, str):
            raise ToolArgumentError(f"argument '{name}' must be a string")
        if rule.min_length is not None and len(value) < rule.min_length:
            raise ToolArgumentError(f"argument '{name}' is shorter than min_length")
        if rule.max_length is not None and len(value) > rule.max_length:
            raise ToolArgumentError(f"argument '{name}' exceeds max_length")
        if rule.choices and value not in rule.choices:
            raise ToolArgumentError(f"argument '{name}' is not an allowed choice")
    elif argument_type is ToolArgumentType.INTEGER:
        if not _is_integer(value):
            raise ToolArgumentError(f"argument '{name}' must be an integer")
    elif argument_type is ToolArgumentType.NUMBER:
        if not _is_number(value):
            raise ToolArgumentError(f"argument '{name}' must be a number")
    elif argument_type is ToolArgumentType.BOOLEAN:
        if not isinstance(value, bool):
            raise ToolArgumentError(f"argument '{name}' must be a boolean")
    else:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ToolArgumentError(f"argument '{name}' must be a string list")
        if rule.min_length is not None and len(value) < rule.min_length:
            raise ToolArgumentError(f"argument '{name}' has too few items")
        if rule.max_length is not None and len(value) > rule.max_length:
            raise ToolArgumentError(f"argument '{name}' has too many items")

    if _is_number(value):
        numeric = float(value)
        if rule.minimum is not None and numeric < rule.minimum:
            raise ToolArgumentError(f"argument '{name}' is below minimum")
        if rule.maximum is not None and numeric > rule.maximum:
            raise ToolArgumentError(f"argument '{name}' exceeds maximum")


def validate_tool_arguments(
    spec: ToolSpec,
    arguments: dict[str, ToolArgumentValue],
) -> None:
    """Reject missing, unknown, or wrongly typed arguments."""
    unknown = sorted(set(arguments) - set(spec.argument_schema))
    if unknown:
        raise ToolArgumentError("unknown arguments: " + ", ".join(unknown))

    missing = sorted(
        name
        for name, rule in spec.argument_schema.items()
        if rule.required and name not in arguments
    )
    if missing:
        raise ToolArgumentError("missing required arguments: " + ", ".join(missing))

    for name, value in arguments.items():
        _validate_one(name, value, spec.argument_schema[name])
