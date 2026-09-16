from __future__ import annotations

from pathlib import Path


def test_tms_oms_pages_surface_externalized_provider_governance() -> None:
    """若 TMS/OMS 入口未展示外置配置/Secret/用量治理状态，本测试应失败。"""

    tms = Path("web/app/tms/page.tsx")
    oms = Path("web/app/oms/page.tsx")

    assert tms.exists()
    assert oms.exists()
    tms_source = tms.read_text(encoding="utf-8")
    oms_source = oms.read_text(encoding="utf-8")

    for status in ("managed", "locked", "draft", "active", "failed"):
        assert status in tms_source
    assert "/api/v1/tms/settings" in tms_source
    assert "Secret reference" in tms_source
    assert "Secret value" not in tms_source

    assert "/api/v1/oms/usage" in oms_source
    assert "/api/v1/oms/audit" in oms_source
    assert "/api/v1/oms/secrets" in oms_source
    assert "private file body" in oms_source
    assert "long-lived download URL" in oms_source
