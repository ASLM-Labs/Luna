"""Remove generated repository artifacts while preserving .git and .venv."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv"}
DIRECTORY_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp",
    ".mypy_cache",
    ".ruff_cache",
}


def main() -> int:
    removed: list[str] = []
    paths = sorted(ROOT.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in paths:
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if path.is_dir() and (path.name in DIRECTORY_NAMES or path.name.endswith(".egg-info")):
            shutil.rmtree(path, ignore_errors=True)
            removed.append(relative.as_posix())
        elif path.is_file() and path.suffix in {".pyc", ".pyo"}:
            path.unlink(missing_ok=True)
            removed.append(relative.as_posix())
    print(f"removed_artifacts: {len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
