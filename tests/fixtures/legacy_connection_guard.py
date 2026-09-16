"""PG 行为测试的旧连接硬门禁；绝不创建旧库。"""

import sqlite3


def forbid_legacy_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Legacy database runtime access")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
