from deeptutor.services.session.scope import StoreScope


def test_tenant_namespace_does_not_collide_with_same_owner():
    try:
        a = StoreScope("postgres", "db", "same-user", tenant_id="a")
        b = StoreScope("postgres", "db", "same-user", tenant_id="b")
    except TypeError:
        assert False, "StoreScope 尚不支持 tenant"
    assert a.cache_key != b.cache_key
    assert a.cache_key != StoreScope("postgres", "db:a", "same-user").cache_key


def test_local_namespace_preserved():
    assert StoreScope("sqlite", "/tmp/db", "user").cache_key == "sqlite:/tmp/db:user"
