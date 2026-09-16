"""A1 externalized data/runtime provider schema contract."""


def test_externalized_runtime_catalog_declares_metadata_settings_policy_and_secret_refs():
    """若 migration 没有登记外置资源/配置/Secret schema，本测试应失败。"""

    from deeptutor.persistence.postgres.migrations.runner import _CATALOGS, _OWNER_TABLES

    columns, constraints = _CATALOGS["0014_externalized_runtime"]

    required = {
        "resource_objects",
        "resource_cleanup_jobs",
        "runtime_settings",
        "runtime_policies",
        "secret_references",
        "runtime_audit_events",
    }
    assert required <= set(columns)
    assert {"resource_objects", "resource_cleanup_jobs"} <= set(_OWNER_TABLES)
    assert "secret_references" not in _OWNER_TABLES
    assert "secret_value" not in columns["secret_references"]
    assert "plaintext" not in columns["secret_references"]
    assert "summary" in columns["runtime_audit_events"]
    assert any("bucket, object_key" in item for item in constraints["resource_objects"])
    assert any("status" in item and "draft" in item for item in constraints["runtime_settings"])
    assert any("event_kind" in item for item in constraints["runtime_audit_events"])
