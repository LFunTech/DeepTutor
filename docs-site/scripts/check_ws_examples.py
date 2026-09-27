"""校验文档中标记的 WebSocket 命令与当前 wire model 一致。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

from pydantic import TypeAdapter, ValidationError

from deeptutor.api.contracts.turn_protocol import ClientCommand


ROOT = Path(__file__).resolve().parents[1] / "docs" / "agent-developer"
PATTERN = re.compile(r"<!-- ws-command -->\s*```json\s*(.*?)\s*```", re.DOTALL)
ADAPTER = TypeAdapter(ClientCommand)


def main() -> int:
    count = 0
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*.mdx")):
        content = path.read_text(encoding="utf-8")
        for index, match in enumerate(PATTERN.finditer(content), start=1):
            count += 1
            try:
                ADAPTER.validate_python(json.loads(match.group(1)))
            except (json.JSONDecodeError, ValidationError) as exc:
                failures.append(f"{path.name} 命令 #{index}: {exc}")
    if count < 12:
        failures.append("WebSocket 独立页面的命令示例不完整")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"已校验 {count} 个 WebSocket 命令示例")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
