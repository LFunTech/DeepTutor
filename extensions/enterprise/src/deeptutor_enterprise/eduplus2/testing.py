"""EduPlus2 测试替身；只用于本地契约测试，不代表生产降级路径。"""

from __future__ import annotations

import copy

from .client import normalize_permission_response, normalize_profile_response


class StaticEduPlus2Resolver:
    """以 client_id 返回预置 resolve 结果的确定性 resolver。"""

    def __init__(self, clients: dict[str, dict]):
        self._clients = copy.deepcopy(clients)

    async def resolve_client(self, client_id: str) -> dict:
        if client_id not in self._clients:
            raise LookupError("client is not resolvable")
        return copy.deepcopy(self._clients[client_id])


class StaticEduPlus2ProfileClient:
    """以 (tenant,user) 返回 profile 的确定性测试替身。"""

    def __init__(self, profiles: dict[tuple[str, str], dict]):
        self._profiles = copy.deepcopy(profiles)

    async def fetch_profile(
        self,
        *,
        external_tenant_id: str,
        external_user_id: str,
        external_subject: str,
        client_id: str,
        external_app_id: str,
    ) -> dict:
        key = (external_tenant_id, external_user_id)
        if key not in self._profiles:
            raise LookupError("profile is unavailable")
        profile = copy.deepcopy(self._profiles[key])
        return normalize_profile_response(
            external_tenant_id=external_tenant_id,
            external_user_id=external_user_id,
            external_subject=external_subject,
            payload={"data": {"verified": True, "profile": profile}},
        )


class StaticEduPlus2PermissionClient:
    """以 (tenant,user,client,app) 返回 permission 的确定性测试替身。"""

    def __init__(self, permissions: dict[tuple[str, str, str, str], dict]):
        self._permissions = copy.deepcopy(permissions)

    async def check_permission(
        self,
        *,
        external_tenant_id: str,
        external_user_id: str,
        external_subject: str,
        client_id: str,
        external_app_id: str,
        requested_usages: tuple[str, ...] = ("deeptutor.chat",),
    ) -> dict:
        key = (external_tenant_id, external_user_id, client_id, external_app_id)
        if key not in self._permissions:
            raise LookupError("permission is unavailable")
        permission = copy.deepcopy(self._permissions[key])
        return normalize_permission_response(
            external_tenant_id=external_tenant_id,
            external_user_id=external_user_id,
            external_subject=external_subject,
            client_id=client_id,
            external_app_id=external_app_id,
            payload={
                "data": {
                    "allowed": permission.get("allowed", False),
                    "reason": permission.get("reason", ""),
                    "tenant": {"id": external_tenant_id},
                    "user": {"id": external_user_id, "subject": external_subject},
                    "client": {"client_id": client_id},
                    "app": {"id": external_app_id},
                    "permission": permission,
                    "requested_usages": list(requested_usages),
                }
            },
        )
