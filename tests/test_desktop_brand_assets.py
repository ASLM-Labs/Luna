from __future__ import annotations

from pathlib import Path
from struct import unpack

import pytest

from luna.desktop import (
    BRAND_ASSET_DIR,
    LUNA_BRAND_BLUE,
    LUNA_BRAND_DARK_PANEL,
    LUNA_BRAND_NEAR_BLACK,
    LUNA_BRAND_SOFT_WHITE,
    LUNA_ICON_SIZES,
    luna_brand_assets,
    luna_empty_state_brand_asset,
    luna_sidebar_brand_asset,
)


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return unpack(">II", data[16:24])


def test_canonical_luna_brand_palette_is_locked() -> None:
    assert LUNA_BRAND_NEAR_BLACK == "#171717"
    assert LUNA_BRAND_SOFT_WHITE == "#F1F1EE"
    assert LUNA_BRAND_BLUE == "#1783FF"
    assert LUNA_BRAND_DARK_PANEL == "#181817"


def test_light_and_dark_asset_families_use_official_geometry_and_colors() -> None:
    light = luna_brand_assets("light")
    dark = luna_brand_assets("dark")

    assert light.foreground == LUNA_BRAND_NEAR_BLACK
    assert dark.foreground == LUNA_BRAND_SOFT_WHITE
    assert light.blue == dark.blue == LUNA_BRAND_BLUE
    assert light.icon_svg.name == "luna-icon-light.svg"
    assert dark.icon_svg.name == "luna-icon-dark.svg"
    assert light.wordmark_svg.name == "luna-wordmark-light.svg"
    assert dark.wordmark_svg.name == "luna-wordmark-dark.svg"

    light_icon = light.icon_svg.read_text(encoding="utf-8")
    dark_icon = dark.icon_svg.read_text(encoding="utf-8")
    light_wordmark = light.wordmark_svg.read_text(encoding="utf-8")
    dark_wordmark = dark.wordmark_svg.read_text(encoding="utf-8")
    assert LUNA_BRAND_NEAR_BLACK in light_icon
    assert LUNA_BRAND_NEAR_BLACK in light_wordmark
    assert LUNA_BRAND_SOFT_WHITE in dark_icon
    assert LUNA_BRAND_SOFT_WHITE in dark_wordmark
    for source in (light_icon, dark_icon, light_wordmark, dark_wordmark):
        assert LUNA_BRAND_BLUE in source
        assert "#2563EB" not in source
        assert "gradient" not in source.lower()
        assert "filter" not in source.lower()


def test_exact_icon_sizes_are_shipped_without_runtime_resize() -> None:
    for theme in ("light", "dark"):
        assets = luna_brand_assets(theme)
        for size in LUNA_ICON_SIZES:
            path = assets.icon_png(size)
            assert path.is_file()
            assert _png_size(path) == (size, size)
        with pytest.raises(ValueError, match="unsupported official Luna icon size"):
            assets.icon_png(96)


def test_regular_compact_and_empty_state_brand_surfaces_remain_separate() -> None:
    regular = luna_sidebar_brand_asset("light", compact=False)
    compact = luna_sidebar_brand_asset("light", compact=True)
    empty = luna_empty_state_brand_asset("dark")

    assert regular.kind == "wordmark"
    assert regular.pixel_size == (120, 54)
    assert _png_size(regular.path) == regular.pixel_size
    assert compact.kind == "icon"
    assert compact.pixel_size == (32, 32)
    assert _png_size(compact.path) == compact.pixel_size
    assert empty.kind == "wordmark"
    assert empty.pixel_size == (160, 72)
    assert _png_size(empty.path) == empty.pixel_size


def test_combined_lockup_is_not_shipped_to_the_desktop_package() -> None:
    shipped = tuple(path.name for path in BRAND_ASSET_DIR.iterdir() if path.is_file())
    assert shipped
    assert all("lockup" not in name.lower() for name in shipped)
