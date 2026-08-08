"""Light-first Phase 16 desktop theme tokens."""

from __future__ import annotations

from typing import Final

LUNA_CANVAS: Final = "#FFFFFF"
LUNA_TEXT: Final = "#171717"
LUNA_SECONDARY: Final = "#666B73"
LUNA_BORDER: Final = "#E7E9ED"
LUNA_SURFACE: Final = "#F5F6F8"
LUNA_SIDEBAR: Final = "#F1F5F9"
LUNA_BLUE: Final = "#2563EB"
LUNA_BLUE_SOFT: Final = "#EAF1FF"
LUNA_SUCCESS: Final = "#15803D"
LUNA_WARNING: Final = "#B45309"
LUNA_DANGER: Final = "#B91C1C"

BASE_FONT_FAMILY: Final = "Segoe UI"
BASE_FONT_SIZE: Final = 11
TITLE_FONT_SIZE: Final = 24

SIDEBAR_WIDTH: Final = 248
CONTENT_MAX_WIDTH: Final = 920
CORNER_RADIUS_HINT: Final = 14

THEME_TOKENS: Final[dict[str, str | int]] = {
    "canvas": LUNA_CANVAS,
    "text": LUNA_TEXT,
    "secondary": LUNA_SECONDARY,
    "border": LUNA_BORDER,
    "surface": LUNA_SURFACE,
    "sidebar": LUNA_SIDEBAR,
    "blue": LUNA_BLUE,
    "blue_soft": LUNA_BLUE_SOFT,
    "success": LUNA_SUCCESS,
    "warning": LUNA_WARNING,
    "danger": LUNA_DANGER,
    "font_family": BASE_FONT_FAMILY,
    "font_size": BASE_FONT_SIZE,
    "title_font_size": TITLE_FONT_SIZE,
    "sidebar_width": SIDEBAR_WIDTH,
    "content_max_width": CONTENT_MAX_WIDTH,
    "corner_radius_hint": CORNER_RADIUS_HINT,
}
