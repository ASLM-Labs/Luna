from __future__ import annotations
import tomllib
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]

def test_pyproject_declares_expected_python_and_version() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == "0.1.0"
    assert data["project"]["requires-python"] == ">=3.12,<3.14"

def test_governance_constitution_is_present() -> None:
    constitution = PROJECT_ROOT / "docs/governance/Luna_0.1_Teknik_Anayasa_v0.1.md"
    assert constitution.is_file()
    assert "ONAYLANDI" in constitution.read_text(encoding="utf-8")

def test_no_runtime_capability_modules_exist_in_phase_zero() -> None:
    package_root = PROJECT_ROOT / "src/luna"
    forbidden = {"tools", "memory", "workspace", "checkpoint", "verification"}
    present = {path.name for path in package_root.iterdir() if path.is_dir()}
    assert forbidden.isdisjoint(present)
