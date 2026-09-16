"""Task 1.2：领域契约清单本身必须可机读、完整且指向真实基线节点。"""

from __future__ import annotations

import json
from pathlib import Path

CONTRACT = Path(__file__).with_name("business-domains-v1.json")
REQUIRED_DIMENSIONS = {
    "dto",
    "ids",
    "ordering",
    "pagination",
    "conflicts",
    "cas",
    "deletion",
    "recovery",
    "owner_constraints",
}


def test_contract_v1_has_all_domains_dimensions_and_75_existing_nodes() -> None:
    document = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert document["version"] == 1
    assert document["database_acceptance"] == "real-postgresql-only"
    assert document["matrix"]["hard_prerequisite_task"] == "1.23"
    assert document["matrix"]["schema_frozen"] is False

    domains = document["domains"]
    assert set(domains) == {
        "question_notebook",
        "learning_mastery",
        "reading_catalog",
        "cron",
        "partners_runtime_status",
        "marginnote4",
        "memory_snapshot",
    }
    assert all(set(domain["contract"]) == REQUIRED_DIMENSIONS for domain in domains.values())

    nodeids = [node for domain in domains.values() for node in domain["legacy_test_nodes"]]
    assert len(nodeids) == len(set(nodeids)) == 75
    root = Path(__file__).parents[3]
    assert all((root / nodeid.split("::", 1)[0]).is_file() for nodeid in nodeids)
    assert all(domain["postgres_acceptance"] for domain in domains.values())


def test_legacy_representatives_are_explicitly_isolated_from_pg_acceptance() -> None:
    document = json.loads(CONTRACT.read_text(encoding="utf-8"))
    representatives = document["legacy_representative_nodes"]

    assert set(representatives) == set(document["domains"])
    assert all(
        node in document["domains"][domain]["legacy_test_nodes"]
        for domain, node in representatives.items()
    )
    assert document["legacy_fixture_policy"] == {
        "purpose": "offline-import-and-behavior-baseline-only",
        "runtime_provider_allowed": False,
        "postgres_substitute_allowed": False,
        "requires_temporary_runtime_home": True,
    }


def test_postgres_business_fixture_has_no_legacy_store_fallback() -> None:
    business_root = Path(__file__).parents[1] / "postgres" / "business"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in business_root.rglob("*.py")
        if path.name != "test_business_domain_contract.py"
    )
    assert "sqlite3" not in sources.lower()
    assert '"sqlite"' not in sources.lower()
    assert ":memory:" not in sources
    assert "legacy_baseline" not in sources
