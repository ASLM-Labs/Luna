"""Parse project Python sources without creating bytecode cache files."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "src", ROOT / "tests", ROOT / "scripts")


def main() -> int:
    files = sorted(
        path
        for source_root in SOURCE_ROOTS
        for path in source_root.rglob("*.py")
        if path.name != Path(__file__).name or path.resolve() == Path(__file__).resolve()
    )
    for path in files:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
    print(f"{len(files)} Python files parsed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
