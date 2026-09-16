"""兼容旧企业导入路径；PG 会话实现由 core 唯一持有。"""

from deeptutor.persistence.postgres.session import PostgresSessionStore as PostgresSessionStore

__all__ = ["PostgresSessionStore"]
