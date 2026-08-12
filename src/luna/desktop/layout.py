"""Deterministic responsive layout policy for the Tk desktop renderer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .theme import INSPECTOR_WIDTH, SIDEBAR_COMPACT_WIDTH, SIDEBAR_WIDTH


class DesktopLayoutMode(StrEnum):
    """Width-driven shell arrangements."""

    WIDE = "WIDE"
    MEDIUM = "MEDIUM"
    NARROW = "NARROW"


@dataclass(frozen=True, slots=True)
class DesktopLayout:
    """Presentation-only geometry; it carries no runtime authority."""

    mode: DesktopLayoutMode
    sidebar_width: int
    inspector_width: int
    inspector_default_visible: bool
    compact_navigation: bool


def desktop_layout_for_width(width: int) -> DesktopLayout:
    """Choose a usable shell geometry for the current window width."""
    if width >= 1240:
        return DesktopLayout(
            mode=DesktopLayoutMode.WIDE,
            sidebar_width=SIDEBAR_WIDTH,
            inspector_width=INSPECTOR_WIDTH,
            inspector_default_visible=True,
            compact_navigation=False,
        )
    if width >= 880:
        return DesktopLayout(
            mode=DesktopLayoutMode.MEDIUM,
            sidebar_width=232,
            inspector_width=304,
            inspector_default_visible=False,
            compact_navigation=False,
        )
    return DesktopLayout(
        mode=DesktopLayoutMode.NARROW,
        sidebar_width=SIDEBAR_COMPACT_WIDTH,
        inspector_width=288,
        inspector_default_visible=False,
        compact_navigation=True,
    )
