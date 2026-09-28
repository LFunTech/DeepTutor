"""学校/租户持久化业务状态的程序值域。"""

from collections.abc import Mapping
from typing import Any

TENANT_BUSINESS_VALUES = {
    "external_eligibility": frozenset({"not_required", "allowed", "denied"}),
    "provisioning_status": frozenset({"pending", "ready", "failed"}),
    "recovery_state": frozenset({"normal", "quarantined"}),
}


def validate_tenant_business_values(row: Mapping[str, Any]) -> None:
    """拒绝旧行的未知状态；调用方必须先锁住即将变更的租户行。"""

    for field, allowed in TENANT_BUSINESS_VALUES.items():
        if row[field] not in allowed:
            raise ValueError(f"tenant {field} has unknown persisted value")


def tenant_allows_authentication(row: Mapping[str, Any]) -> bool:
    """未知值与被隔离学校统一拒绝认证，不向调用者暴露状态细节。"""

    try:
        validate_tenant_business_values(row)
        return bool(
            row["local_enabled"]
            and row["external_eligibility"] in {"not_required", "allowed"}
            and row["provisioning_status"] == "ready"
            and row["recovery_state"] == "normal"
        )
    except (KeyError, ValueError):
        return False
