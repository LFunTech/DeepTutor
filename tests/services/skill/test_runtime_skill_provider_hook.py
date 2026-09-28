"""通用 Skill service 注入 seam，供产品扩展装配而不改核心解析器。"""

import pytest

from deeptutor.core.providers import ApplicationProviders, provider_context
from deeptutor.services.skill.runtime import get_runtime_skill_service


def test_explicit_skill_service_factory_is_scoped_to_provider_context():
    first = object()
    second = object()
    calls = []

    def factory():
        calls.append("resolved")
        return first if len(calls) == 1 else second

    with provider_context(ApplicationProviders(skill_service_factory=factory)):
        assert get_runtime_skill_service() is first
        assert get_runtime_skill_service() is second
    assert calls == ["resolved", "resolved"]


def test_configured_skill_service_unavailable_does_not_fall_back_to_builtin():
    with provider_context(ApplicationProviders(skill_service_factory=lambda: None)):
        with pytest.raises(RuntimeError, match="configured skill service unavailable"):
            get_runtime_skill_service()
