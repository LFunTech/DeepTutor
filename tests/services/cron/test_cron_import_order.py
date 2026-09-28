"""PG cron 仓储不依赖服务包导入顺序。"""

from __future__ import annotations

import subprocess
import sys


def test_pg_cron_repository_imports_in_clean_interpreter() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from deeptutor.persistence.postgres.cron import AsyncPostgresCronRepository; "
            "from deeptutor.services.cron import PostgresCronService; "
            "assert AsyncPostgresCronRepository and PostgresCronService",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
