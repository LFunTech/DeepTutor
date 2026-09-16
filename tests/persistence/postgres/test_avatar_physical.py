"""1.7 Minor 闭环：在修改引用前保存真实路径，随后直接检查物理对象。"""

import pytest

from tests.fixtures.default_pg_auth import pg_auth_client

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64


@pytest.mark.parametrize("operation", ["delete", "icon", "replace", "account"])
def test_avatar_old_physical_object_is_removed(pg_dsn, tmp_path, operation):
    with pg_auth_client(pg_dsn, tmp_path / "resources") as client:
        user = client.users()["bob"]
        headers = {"Authorization": "Bearer user-token"}
        response = client.put(
            "/api/auth/profile/avatar", files={"file": ("a.png", PNG, "image/png")}, headers=headers
        )
        assert response.status_code == 200
        old = client.avatar_file(user["id"])
        assert old is not None and old.read_bytes() == PNG
        if operation == "delete":
            response = client.delete("/api/auth/profile/avatar", headers=headers)
        elif operation == "icon":
            response = client.put(
                "/api/auth/profile", json={"avatar": "icon:leaf:teal"}, headers=headers
            )
        elif operation == "replace":
            response = client.put(
                "/api/auth/profile/avatar",
                files={"file": ("b.webp", WEBP, "image/webp")},
                headers=headers,
            )
        else:
            response = client.delete(
                "/api/auth/users/bob", headers={"Authorization": "Bearer admin-token"}
            )
        assert response.status_code == 200
        # 不再次问 PG helper；持有删除前路径直接证明旧物理文件消失。
        assert not old.exists()
        if operation == "replace":
            new = client.avatar_file(user["id"])
            assert new != old and new.read_bytes() == WEBP
