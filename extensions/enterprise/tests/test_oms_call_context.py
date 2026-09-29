"""CallContext 只在企业扩展内转换为 OMS attempt，不让 core 依赖余额逻辑。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from deeptutor_enterprise.oms.attempts import AttemptRequest
from deeptutor_enterprise.oms.call_context import UsageCallContext, safe_request_hash
import pytest


def _context():
    return UsageCallContext(
        tenant_id=uuid.uuid4(),
        operation_id=uuid.uuid4(),
        service_id="llm",
        unit_code="token",
        provider_id="provider-a",
        provider_account_id="account-a",
        pool_id="pool-a",
        model_id="model-a",
        config_version=3,
        subject_kind="user",
        subject_id="learner-1",
        user_id="learner-1",
        app_id="agent-app-1",
        request_hash=safe_request_hash(
            {
                "route": "ws.turn",
                "model_id": "model-a",
                "issued_at": datetime(2026, 9, 28, tzinfo=timezone.utc).isoformat(),
                "deadline_at": (
                    datetime(2026, 9, 28, tzinfo=timezone.utc) + timedelta(seconds=30)
                ).isoformat(),
            }
        ),
    )


def test_usage_call_context_creates_distinct_billable_attempts_for_same_operation():
    context = _context()
    first = context.attempt(reserved_units=Decimal("10"))
    second = context.attempt(reserved_units=Decimal("10"))
    assert isinstance(first, AttemptRequest)
    assert first.operation_id == second.operation_id == context.operation_id
    assert first.attempt_id != second.attempt_id
    assert first.service_id == "llm"
    assert first.pool_id == "pool-a"
    assert first.subject_id == "learner-1"


def test_usage_request_hash_rejects_private_content_and_is_deterministic():
    assert safe_request_hash({"model": "a", "route": "http"}) == safe_request_hash(
        {"route": "http", "model": "a"}
    )
    with pytest.raises(ValueError, match="private request content"):
        safe_request_hash({"prompt": "do not persist"})
    with pytest.raises(ValueError, match="private request content"):
        safe_request_hash({"attachments": ["raw"]})
