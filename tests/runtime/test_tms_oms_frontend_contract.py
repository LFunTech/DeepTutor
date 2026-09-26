from __future__ import annotations

from pathlib import Path


ROOT = Path("extensions/enterprise/frontends")


def test_cloud_admin_frontends_are_independent_and_share_components() -> None:
    oms = (ROOT / "apps/oms/src/OmsPrototype.tsx").read_text(encoding="utf-8")
    tms = (ROOT / "apps/tms/src/TmsPrototype.tsx").read_text(encoding="utf-8")
    shared = (ROOT / "packages/service-components/src/index.tsx").read_text(encoding="utf-8")
    for source in (oms, tms):
        assert 'from "@deeptutor/service-components"' in source
        assert "<OcrServiceList" in source
        assert "<ServiceList" in source
    assert "isOms" not in shared and "isTms" not in shared
    assert (ROOT / "apps/oms/next.config.mjs").exists()
    assert (ROOT / "apps/tms/next.config.mjs").exists()


def test_tms_quota_is_read_only_and_fixture_does_not_contain_platform_fields() -> None:
    tms = (ROOT / "apps/tms/src/TmsPrototype.tsx").read_text(encoding="utf-8")
    fixture = (ROOT / "apps/tms/src/fixtures.ts").read_text(encoding="utf-8")
    assert "配额清单" in tms
    assert "仅可查看" in tms
    assert "onClick={() => setFormOpen" not in tms.split('root === "quotas"')[1].split('root === "knowledge"')[0]
    for forbidden in ("secretRef", "supplierCost", "api_key", "tenantId: \"harbor\""):
        assert forbidden not in fixture


def test_local_web_retires_old_admin_entries_and_prototype_redirects_are_dev_only() -> None:
    for app in ("oms", "tms"):
        page = Path(f"web/app/{app}/page.tsx").read_text(encoding="utf-8")
        route = Path(f"web/app/{app}/prototype/page.tsx").read_text(encoding="utf-8")
        proxy = (ROOT / f"apps/{app}/proxy.ts").read_text(encoding="utf-8")
        assert "notFound()" in page
        assert 'process.env.NODE_ENV !== "development"' in route
        assert "notFound()" in route
        assert "redirect(" in route
        assert "status: 404" in proxy
