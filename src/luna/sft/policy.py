"""Frozen default policy for Luna Phase 19E controlled SFT."""

from __future__ import annotations

from luna.sft.models import SFTPolicy


def build_default_sft_policy() -> SFTPolicy:
    """Return the revision-locked first-SFT policy."""

    return SFTPolicy.freeze(revision="1.0.0")
