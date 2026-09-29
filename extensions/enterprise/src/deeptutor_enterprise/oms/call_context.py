"""可信 provider 调用上下文到 OMS attempt 的企业扩展适配层。

该模块位于 enterprise 扩展内，避免 core 运行时依赖额度/余额逻辑。core 若未来
需要 hook，只需传入不含正文的服务/主体/配置元数据和 caller-owned operation id。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Any, Literal
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


def safe_request_hash(metadata: dict[str, Any]) -> str:
    """仅对安全元数据取 hash；调用方不得传 prompt/回答/附件正文。"""

    if not isinstance(metadata, dict):
        raise ValueError("usage request metadata must be an object")
    forbidden = {"prompt", "messages", "answer", "content", "attachment", "attachments"}
    if any(str(key) in forbidden for key in metadata):
        raise ValueError("usage request hash must not include private request content")
    payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
