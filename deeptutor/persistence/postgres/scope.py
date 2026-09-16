"""经过认证或受控维护入口建立的不可变资源范围。"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantScope:
    tenant_id: str
    user_id: str

    def __post_init__(self):
        object.__setattr__(self, "tenant_id", str(UUID(self.tenant_id)))
        if not self.user_id or len(self.user_id) > 255 or "\x00" in self.user_id:
            raise ValueError("invalid user scope")
