"""兼容旧企业导入路径；migration 实现与 SQL 资源仅存在于 core。"""

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

__all__ = ["MigrationRunner"]
