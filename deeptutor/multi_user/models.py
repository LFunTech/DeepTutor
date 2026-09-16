"""Small data models for DeepTutor's optional multi-user layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Role = Literal["admin", "user", "tenant_admin"]
AccountPreset = Literal["standard", "learner", "custom"]
ScopeKind = Literal["admin", "user", "tenant"]


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    username: str
    role: Role = "user"
    created_at: str = ""
    disabled: bool = False
    # Avatar marker: "" (deterministic fallback), "icon:<name>:<color>" for a
    # picked icon, or "img:<version>" when the user uploaded an image (the
    # version is bumped on every upload so clients can cache-bust).
    avatar: str = ""

    # Account presets describe how a normal ``user`` is configured. They are
    # deliberately not a third identity role: admins remain admins and every
    # preset remains an ordinary account.
    preset: AccountPreset = "standard"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at,
            "disabled": self.disabled,
            "avatar": self.avatar,
            "preset": self.preset,
        }


@dataclass(frozen=True, slots=True)
class UserScope:
    kind: ScopeKind
    user_id: str
    root: Path | None
    tenant_id: str = ""

    @property
    def cache_key(self) -> str:
        if self.tenant_id:
            import json

            return json.dumps([self.kind, self.tenant_id, self.user_id], separators=(",", ":"))
        if self.root is None:
            raise ValueError("local scope requires a filesystem root")
        return f"{self.kind}:{self.user_id}:{self.root.resolve()}"


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    username: str
    role: Role
    scope: UserScope
    learning_policy: dict[str, Any] | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_manage_accounts(self) -> bool:
        return self.role == "tenant_admin" and self.scope.kind == "tenant"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "is_admin": self.can_manage_accounts,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeResource:
    id: str
    name: str
    base_dir: Path
    source: Literal["admin", "user"]
    assigned: bool = False
    read_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def physical_name(self) -> str:
        return self.name


LOCAL_ADMIN_ID = "local-admin"
LOCAL_ADMIN_USERNAME = "local"
