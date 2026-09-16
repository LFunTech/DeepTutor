"""兼容旧企业导入路径；PG 身份实现由 core 唯一持有。"""

from deeptutor.persistence.postgres.identity.service import (
    Identity as Identity,
)
from deeptutor.persistence.postgres.identity.service import (
    IdentityService as IdentityService,
)
from deeptutor.persistence.postgres.identity.service import (
    LoginRateLimited as LoginRateLimited,
)

__all__ = ["Identity", "IdentityService", "LoginRateLimited"]
