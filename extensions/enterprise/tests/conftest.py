"""企业回归与 core 共用隔离临时 PG，不接用户数据库。"""

from pathlib import Path
import sys

from tests.fixtures.postgres import pg_cluster, pg_dsn  # noqa: F401

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
