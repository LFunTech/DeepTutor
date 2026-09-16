"""企业旧路径仅兼容转发 core PG 唯一实现。"""


def test_identity_session_and_executor_are_exact_core_symbols():
    from deeptutor_enterprise.executor import ExecutorLease, lock_key
    from deeptutor_enterprise.identity.service import (
        Identity,
        IdentityService,
        LoginRateLimited,
    )
    from deeptutor_enterprise.stores.postgres.session import PostgresSessionStore

    from deeptutor.persistence.postgres.executor import (
        ExecutorLease as CoreExecutorLease,
    )
    from deeptutor.persistence.postgres.executor import (
        lock_key as core_lock_key,
    )
    from deeptutor.persistence.postgres.identity.service import (
        Identity as CoreIdentity,
    )
    from deeptutor.persistence.postgres.identity.service import (
        IdentityService as CoreIdentityService,
    )
    from deeptutor.persistence.postgres.identity.service import (
        LoginRateLimited as CoreLoginRateLimited,
    )
    from deeptutor.persistence.postgres.session import (
        PostgresSessionStore as CorePostgresSessionStore,
    )

    assert Identity is CoreIdentity
    assert IdentityService is CoreIdentityService
    assert LoginRateLimited is CoreLoginRateLimited
    assert PostgresSessionStore is CorePostgresSessionStore
    assert ExecutorLease is CoreExecutorLease
    assert lock_key is core_lock_key
