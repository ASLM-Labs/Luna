"""Standard-library-only structural verification for Luna Phase 0."""
from __future__ import annotations
import hashlib, json, sys, tomllib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    required = [
        ROOT / "pyproject.toml",
        ROOT / "README.md",
        ROOT / "src/luna/__init__.py",
        ROOT / "src/luna/cli.py",
        ROOT / "tests/test_cli.py",
        ROOT / "docs/governance/Luna_0.1_Teknik_Anayasa_v0.1.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    result = {
        "python": sys.version,
        "project_version": pyproject["project"]["version"],
        "missing_required_files": missing,
        "constitution_sha256": sha256(required[-1]) if required[-1].is_file() else None,
        "status": "PASS" if not missing else "BLOCKED",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
