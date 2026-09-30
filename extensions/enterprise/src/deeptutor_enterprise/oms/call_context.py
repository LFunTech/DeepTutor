"""可信 provider 调用上下文到 OMS attempt 的企业扩展适配层。

该模块位于 enterprise 扩展内，避免 core 运行时依赖额度/余额逻辑。core 若未来
需要 hook，只需传入不含正文的服务/主体/配置元数据和 caller-owned operation id。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID, uuid4

from .attempts import AttemptRequest

SubjectKind = Literal["user", "delegated_user", "app", "service"]


@dataclass(frozen=True, slots=True)
class UsageCallContext:
    tenant_id: UUID
    operation_id: UUID
    service_id: str
    unit_code: str
    provider_id: str
    provider_account_id: str
    pool_id: str
    model_id: str
    config_version: int
    subject_kind: SubjectKind
    subject_id: str
    user_id: str = ""
    app_id: str = ""
    request_hash: str = ""

    def attempt(self, *, reserved_units: Decimal, attempt_id: UUID | None = None) -> AttemptRequest:
        if self.request_hash and len(self.request_hash) != 64:
            raise ValueError("usage call context request hash must be sha256 hex")
        if self.subject_kind == "user" and (
            self.user_id != self.subject_id or bool(self.app_id)
        ):
            raise ValueError("usage call context subject attribution is invalid")
        if self.subject_kind == "delegated_user" and (
            self.user_id != self.subject_id or not self.app_id
        ):
            raise ValueError("usage call context subject attribution is invalid")
        if self.subject_kind == "app" and (
            self.app_id != self.subject_id or bool(self.user_id)
        ):
            raise ValueError("usage call context subject attribution is invalid")
        if self.subject_kind == "service" and (self.user_id or self.app_id):
            raise ValueError("usage call context subject attribution is invalid")
        return AttemptRequest(
            operation_id=self.operation_id,
            attempt_id=attempt_id or uuid4(),
            service_id=self.service_id,
            unit_code=self.unit_code,
            provider_id=self.provider_id,
            provider_account_id=self.provider_account_id,
            pool_id=self.pool_id,
            model_id=self.model_id,
            config_version=self.config_version,
            subject_kind=self.subject_kind,
            subject_id=self.subject_id,
            user_id=self.user_id,
            app_id=self.app_id,
            reserved_units=reserved_units,
        )


@dataclass(frozen=True, slots=True)
class ProviderAttemptReceipt:
    """不含 prompt/回答正文的可信 provider 调用结果与 usage 证据。"""

    result: Any
    units: Decimal | None
    evidence_ref: str
    provider_request_id: str = ""
    source: Literal["provider_usage", "verified_reconciliation"] = "provider_usage"


async def run_metered_provider_attempt(
    ledger: Any,
    scope: Any,
    context: UsageCallContext,
    *,
    reserved_units: Decimal,
    dispatch_evidence_ref: str,
    unknown_evidence_ref: str,
    call: Callable[[UUID], Awaitable[ProviderAttemptReceipt]],
) -> Any:
    """预留、记录发出、执行 provider 调用并按可信 usage 结算。

    `call` 只接收 attempt ID；调用方不得把 prompt、回答或附件正文交给本层。
    发生异常时保留预留并标记 remote_unknown，等待后续 provider receipt 对账。
    """

    request = context.attempt(reserved_units=reserved_units)
    await ledger.reserve(scope, request)
    await ledger.mark_dispatched(
        scope,
        request.attempt_id,
        evidence_ref=dispatch_evidence_ref,
    )
    try:
        receipt = await call(request.attempt_id)
    except BaseException:
        await ledger.mark_remote_unknown(
            scope,
            request.attempt_id,
            evidence_ref=unknown_evidence_ref,
        )
        raise
    if not isinstance(receipt, ProviderAttemptReceipt):
        await ledger.mark_remote_unknown(
            scope,
            request.attempt_id,
            evidence_ref=unknown_evidence_ref,
        )
        raise ValueError("trusted provider receipt is required")
    if receipt.provider_request_id:
        await ledger.mark_dispatched(
            scope,
            request.attempt_id,
            evidence_ref=dispatch_evidence_ref,
            provider_request_id=receipt.provider_request_id,
        )
    if receipt.units is None:
        await ledger.mark_remote_unknown(
            scope,
            request.attempt_id,
            evidence_ref=receipt.evidence_ref or unknown_evidence_ref,
        )
        return receipt.result
    await ledger.settle(
        scope,
        request.attempt_id,
        units=receipt.units,
        source=receipt.source,
        evidence_ref=receipt.evidence_ref,
        provider_request_id=receipt.provider_request_id,
    )
    return receipt.result


def safe_request_hash(metadata: dict[str, Any]) -> str:
    """仅对安全元数据取 hash；调用方不得传 prompt/回答/附件正文。"""

    if not isinstance(metadata, dict):
        raise ValueError("usage request metadata must be an object")
    forbidden = {"prompt", "messages", "answer", "content", "attachment", "attachments"}

    def reject_private_keys(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in forbidden:
                    raise ValueError("usage request hash must not include private request content")
                reject_private_keys(child)
        elif isinstance(value, list | tuple):
            for child in value:
                reject_private_keys(child)

    reject_private_keys(metadata)
    payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
