"""Shared console rendering and exit-code policy."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def write_json(
    payload: Mapping[str, Any] | list[Any],
    *,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
    indent: int | None = 2,
) -> None:
    """Render a legacy-compatible indented JSON payload."""

    print(
        json.dumps(
            payload,
            ensure_ascii=ensure_ascii,
            indent=indent,
            sort_keys=sort_keys,
        )
    )


def diagnostic_exit_code(passed: bool) -> int:
    """Map diagnostic truth to Luna's established process contract."""

    return 0 if passed else 2
