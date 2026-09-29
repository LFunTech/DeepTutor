import pytest

from tests.fixtures import postgres


def test_external_pg_dsn_accepts_explicit_localhost_admin_database():
    assert (
        postgres._validated_external_admin_dsn(  # noqa: SLF001 - fixture helper contract
            "host=localhost port=5432 user=postgres dbname=postgres"
        )
        == "host=localhost port=5432 user=postgres dbname=postgres"
    )


@pytest.mark.parametrize(
    "dsn",
    [
        "host=db.example.com user=postgres dbname=postgres",
        "host=127.0.0.1 user=postgres dbname=deeptutor",
    ],
)
def test_external_pg_dsn_rejects_non_local_or_non_admin_database(dsn):
    with pytest.raises(ValueError):
        postgres._validated_external_admin_dsn(dsn)  # noqa: SLF001 - fixture helper contract
