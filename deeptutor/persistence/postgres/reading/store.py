"""阅读目录聚合；不加载 SQLite、不创建目录、不运行构造 DDL。"""

from .base import StoreBase
from .materials import Materials
from .pages import Pages
from .queries import Queries
from .sessions import Sessions
from .workspaces import Workspaces


class PostgresReadingCatalogStore(Materials, Workspaces, Sessions, Queries, Pages, StoreBase):
    pass
