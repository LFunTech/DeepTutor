"""PG-only 残余 SQLite 引用分类门禁。"""

from __future__ import annotations

from pathlib import Path
import re

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CLASSIFICATION = (
    REPOSITORY_ROOT
    / "openspec"
    / "changes"
    / "migrate-all-sqlite-state-to-postgresql"
    / "sqlite-reference-classification.md"
)


def _production_sqlite_imports() -> list[str]:
    pattern = re.compile(r"^(?:import sqlite3|from sqlite3 import )", re.MULTILINE)
    results: list[str] = []
    for path in sorted((REPOSITORY_ROOT / "deeptutor").rglob("*.py")):
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if "/tests/" in f"/{relative}/":
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            results.append(relative)
    return results


def test_all_remaining_sqlite_imports_are_classified() -> None:
    text = CLASSIFICATION.read_text(encoding="utf-8")

    missing = [relative for relative in _production_sqlite_imports() if relative not in text]

    assert missing == []
    assert "aiosqlite direct runtime dependencies: none" in text
    assert "业务默认运行图：禁止" in text
