"""OMS 持久化业务值域的程序校验。"""

from __future__ import annotations

from typing import Any, Iterable

SERVICE_RESOURCE_CATEGORIES = frozenset(
    {"model_external", "agent_capability", "tool_integration", "knowledge_content", "runtime"}
)
SUPPLY_LOT_STATUSES = frozenset({"active", "revoked"})
SUPPLY_BASES = frozenset({"legacy_unverified", "native_units", "money", "credits", "paygo"})
ENTITLEMENT_STATUSES = frozenset({"active", "revoked"})
QUOTA_ACQUISITION_METHODS = frozenset({"gift", "recharge"})
QUOTA_GRANT_STATUSES = frozenset({"active", "revoked", "expired"})
GRANT_COMMAND_RESULTS = frozenset({"pending", "success", "denied"})
USAGE_ATTEMPT_STATUSES = frozenset(
    {"reserved", "dispatched", "remote_unknown", "reconcile_required", "settled", "released"}
)
USAGE_SUBJECT_KINDS = frozenset({"user", "delegated_user", "app", "service"})
ATTEMPT_EVIDENCE_EVENT_KINDS = frozenset(
    {
        "dispatch_intent",
        "remote_unknown",
        "provider_usage",
        "verified_reconciliation",
        "confirmed_not_sent",
        "overage",
    }
)
OMS_AUDIT_RESULTS = frozenset({"success", "denied", "conflict", "failed"})
SCHOOL_BINDING_STATUSES = frozenset({"pending", "verified", "revoked"})


class OmsValueError(ValueError):
    """已持久化 OMS 业务值不满足程序权威契约。"""


def _get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_allowed(value: Any, allowed: Iterable[str], message: str) -> str:
    if value not in allowed:
        raise OmsValueError(message)
    return str(value)


def validate_service_definition_row(row: Any) -> None:
    _require_allowed(
        _get(row, "resource_category"),
        SERVICE_RESOURCE_CATEGORIES,
        "service resource category is invalid",
    )


def validate_supply_lot_row(row: Any) -> None:
    _require_allowed(_get(row, "status"), SUPPLY_LOT_STATUSES, "supply lot status is invalid")
    basis = _require_allowed(
        _get(row, "supply_basis"), SUPPLY_BASES, "supply lot basis is invalid"
    )
    hard_ceiling = _get(row, "hard_ceiling")
    verified_at = _get(row, "verified_at")
    created_by = _get(row, "created_by")
    version = _get(row, "version")
    if basis not in {"legacy_unverified", "native_units"} and hard_ceiling is not None:
        raise OmsValueError("supply lot native proof is invalid")
    if verified_at is not None and (basis != "native_units" or hard_ceiling is None):
        raise OmsValueError("supply lot native proof is invalid")
    if created_by is not None and not _nonempty(created_by):
        raise OmsValueError("supply lot creator is invalid")
    if version is not None and (not isinstance(version, int) or version < 1):
        raise OmsValueError("supply lot version is invalid")


def validate_entitlement_row(row: Any) -> None:
    _require_allowed(
        _get(row, "status"), ENTITLEMENT_STATUSES, "entitlement status is invalid"
    )
    version = _get(row, "version")
    if version is not None and (not isinstance(version, int) or version < 1):
        raise OmsValueError("entitlement version is invalid")


def validate_quota_grant_row(row: Any) -> None:
    _require_allowed(
        _get(row, "acquisition_method"),
        QUOTA_ACQUISITION_METHODS,
        "quota grant acquisition method is invalid",
    )
    _require_allowed(_get(row, "status"), QUOTA_GRANT_STATUSES, "quota grant status is invalid")
    version = _get(row, "version")
    if version is not None and (not isinstance(version, int) or version < 1):
        raise OmsValueError("quota grant version is invalid")


def validate_grant_command_row(row: Any) -> None:
    _require_allowed(
        _get(row, "result"), GRANT_COMMAND_RESULTS, "grant command result is invalid"
    )


def validate_usage_attempt_row(row: Any) -> None:
    _require_allowed(
        _get(row, "status"), USAGE_ATTEMPT_STATUSES, "usage attempt status is invalid"
    )
    subject_kind = _require_allowed(
        _get(row, "subject_kind"), USAGE_SUBJECT_KINDS, "usage attempt subject kind is invalid"
    )
    subject_id = _get(row, "subject_id")
    user_id = _get(row, "user_id") or ""
    app_id = _get(row, "app_id") or ""
    if not _nonempty(subject_id):
        raise OmsValueError("usage attempt subject is invalid")
    if subject_kind == "user" and (user_id != subject_id or app_id):
        raise OmsValueError("usage attempt subject kind is invalid")
    if subject_kind == "delegated_user" and (user_id != subject_id or not app_id):
        raise OmsValueError("usage attempt subject kind is invalid")
    if subject_kind == "app" and (app_id != subject_id or user_id):
        raise OmsValueError("usage attempt subject kind is invalid")
    if subject_kind == "service" and (user_id or app_id):
        raise OmsValueError("usage attempt subject kind is invalid")


def validate_attempt_evidence_row(row: Any) -> None:
    _require_allowed(
        _get(row, "event_kind"),
        ATTEMPT_EVIDENCE_EVENT_KINDS,
        "attempt evidence event kind is invalid",
    )


def validate_oms_audit_result(result: Any) -> None:
    _require_allowed(result, OMS_AUDIT_RESULTS, "OMS audit result is invalid")


def validate_school_binding_row(row: Any) -> None:
    status = _require_allowed(
        _get(row, "status"), SCHOOL_BINDING_STATUSES, "school binding status is invalid"
    )
    version = _get(row, "version")
    if not isinstance(version, int) or version < 1:
        raise OmsValueError("school binding version is invalid")
    source_ref = _get(row, "source_ref")
    if source_ref is not None and not _nonempty(source_ref):
        raise OmsValueError("school binding source reference is invalid")
    verified = _get(row, "verified_at") is not None and _nonempty(_get(row, "verified_by"))
    if (status == "verified") != verified:
        raise OmsValueError("school binding verification proof is invalid")
