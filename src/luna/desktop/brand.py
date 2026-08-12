"""Official Luna brand assets for the desktop presentation layer.

This module selects immutable, repository-owned files only.  It never draws or
recomposes Luna geometry at runtime and carries no controller/runtime authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from .theme import (
    LUNA_BRAND_BLUE,
    LUNA_BRAND_DARK_PANEL,
    LUNA_BRAND_NEAR_BLACK,
    LUNA_BRAND_SOFT_WHITE,
)

type LunaBrandTheme = Literal["light", "dark"]
type LunaBrandAssetKind = Literal["icon", "wordmark"]

BRAND_ASSET_DIR: Final = Path(__file__).with_name("assets") / "brand"
LUNA_ICON_SIZES: Final = (16, 24, 32, 48, 64)
LUNA_SIDEBAR_ICON_SIZE: Final = 32


@dataclass(frozen=True, slots=True)
class LunaBrandAssets:
    """One theme-specific set of official standalone brand assets."""

    theme: LunaBrandTheme
    foreground: str
    blue: str
    icon_svg: Path
    icon_ico: Path
    wordmark_svg: Path
    sidebar_wordmark_png: Path
    welcome_wordmark_png: Path
    icon_pngs: tuple[tuple[int, Path], ...]

    def icon_png(self, size: int) -> Path:
        """Return an exact-size icon; runtime resizing is intentionally rejected."""
        for candidate_size, path in self.icon_pngs:
            if candidate_size == size:
                return path
        raise ValueError(f"unsupported official Luna icon size: {size}")


@dataclass(frozen=True, slots=True)
class LunaBrandPlacement:
    """A presentation-only asset choice for one semantic UI surface."""

    kind: LunaBrandAssetKind
    path: Path
    pixel_size: tuple[int, int]


def _asset_set(theme: LunaBrandTheme) -> LunaBrandAssets:
    foreground = LUNA_BRAND_NEAR_BLACK if theme == "light" else LUNA_BRAND_SOFT_WHITE
    return LunaBrandAssets(
        theme=theme,
        foreground=foreground,
        blue=LUNA_BRAND_BLUE,
        icon_svg=BRAND_ASSET_DIR / f"luna-icon-{theme}.svg",
        icon_ico=BRAND_ASSET_DIR / f"luna-icon-{theme}.ico",
        wordmark_svg=BRAND_ASSET_DIR / f"luna-wordmark-{theme}.svg",
        sidebar_wordmark_png=BRAND_ASSET_DIR / f"luna-wordmark-{theme}-120.png",
        welcome_wordmark_png=BRAND_ASSET_DIR / f"luna-wordmark-{theme}-160.png",
        icon_pngs=tuple(
            (size, BRAND_ASSET_DIR / f"luna-icon-{theme}-{size}.png")
            for size in LUNA_ICON_SIZES
        ),
    )


LUNA_LIGHT_BRAND_ASSETS: Final = _asset_set("light")
LUNA_DARK_BRAND_ASSETS: Final = _asset_set("dark")


def luna_brand_assets(theme: LunaBrandTheme) -> LunaBrandAssets:
    """Select the official asset family for a light or dark surface."""
    return LUNA_DARK_BRAND_ASSETS if theme == "dark" else LUNA_LIGHT_BRAND_ASSETS


def luna_sidebar_brand_asset(
    theme: LunaBrandTheme,
    *,
    compact: bool,
) -> LunaBrandPlacement:
    """Use icon-only compact navigation and wordmark-only regular navigation."""
    assets = luna_brand_assets(theme)
    if compact:
        return LunaBrandPlacement(
            kind="icon",
            path=assets.icon_png(LUNA_SIDEBAR_ICON_SIZE),
            pixel_size=(LUNA_SIDEBAR_ICON_SIZE, LUNA_SIDEBAR_ICON_SIZE),
        )
    return LunaBrandPlacement(
        kind="wordmark",
        path=assets.sidebar_wordmark_png,
        pixel_size=(120, 54),
    )


def luna_empty_state_brand_asset(theme: LunaBrandTheme) -> LunaBrandPlacement:
    """Return the official wordmark for the empty-state identity surface."""
    assets = luna_brand_assets(theme)
    return LunaBrandPlacement(
        kind="wordmark",
        path=assets.welcome_wordmark_png,
        pixel_size=(160, 72),
    )


__all__ = [
    "BRAND_ASSET_DIR",
    "LUNA_BRAND_BLUE",
    "LUNA_BRAND_DARK_PANEL",
    "LUNA_BRAND_NEAR_BLACK",
    "LUNA_BRAND_SOFT_WHITE",
    "LUNA_DARK_BRAND_ASSETS",
    "LUNA_ICON_SIZES",
    "LUNA_LIGHT_BRAND_ASSETS",
    "LUNA_SIDEBAR_ICON_SIZE",
    "LunaBrandAssetKind",
    "LunaBrandAssets",
    "LunaBrandPlacement",
    "LunaBrandTheme",
    "luna_brand_assets",
    "luna_empty_state_brand_asset",
    "luna_sidebar_brand_asset",
]
