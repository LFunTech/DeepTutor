"""从 DeepTutor 当前设置 descriptor 生成 OMS 原型的离线候选快照。"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from deeptutor.api.routers.settings import _connection_targets, _provider_choices  # noqa: E402


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "apps/oms/src/provider-descriptors.generated.json"
    data = {
        "source": "deeptutor.api.routers.settings._provider_choices/_connection_targets",
        "source_revision": hashlib.sha256((ROOT / "deeptutor/api/routers/settings.py").read_bytes()).hexdigest()[:12],
        "reasoning_source": "web/lib/reasoning-effort.ts",
        "reasoning_source_revision": hashlib.sha256((ROOT / "web/lib/reasoning-effort.ts").read_bytes()).hexdigest()[:12],
        "providers": _provider_choices(),
        "connection_targets": _connection_targets(),
    }
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if "--check" in sys.argv:
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            raise SystemExit("OMS provider descriptor 快照已过期，请重新生成并审阅差异。")
        print("OMS provider descriptor 快照与 DeepTutor 当前源码一致。")
    else:
        output.write_text(content, encoding="utf-8")
        print(output)


if __name__ == "__main__":
    main()
