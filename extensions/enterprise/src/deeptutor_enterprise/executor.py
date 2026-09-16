"""兼容旧企业导入路径；PG 执行租约实现由 core 唯一持有。"""

from deeptutor.persistence.postgres.executor import ExecutorLease as ExecutorLease
from deeptutor.persistence.postgres.executor import lock_key as lock_key

__all__ = ["ExecutorLease", "lock_key"]
