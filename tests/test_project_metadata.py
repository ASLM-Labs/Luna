from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_expected_python_version_and_developer() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]

    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.12,<3.14"
    assert project["authors"] == [{"name": "Novopic Intelligence"}]


def test_governance_constitution_is_present() -> None:
    constitution = PROJECT_ROOT / "docs" / "governance" / "Luna_0.1_Teknik_Anayasa_v0.1.md"
    assert constitution.is_file()
    assert "ONAYLANDI" in constitution.read_text(encoding="utf-8")


def test_phase_eight_opens_continuity_without_future_runtime_packages() -> None:
    package_root = PROJECT_ROOT / "src" / "luna"
    present = {path.name for path in package_root.iterdir() if path.is_dir()}

    assert {"workspace", "shell", "audit", "verification", "continuity"}.issubset(present)
    assert {"memory", "network"}.isdisjoint(present)


def test_license_contains_full_apache_terms() -> None:
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
