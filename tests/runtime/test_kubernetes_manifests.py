from __future__ import annotations

from pathlib import Path

import yaml


def _docs() -> list[dict]:
    path = Path("deploy/kubernetes/deeptutor-backend.yaml")
    return [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]


def test_backend_kubernetes_manifest_externalizes_state_and_secrets() -> None:
    """若 K8s 示例把 data PVC 当权威或把 DSN/Secret 放进前端/明文 env，本测试应失败。"""

    deployment = next(doc for doc in _docs() if doc["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    pod = deployment["spec"]["template"]["spec"]
    backend = next(container for container in pod["containers"] if container["name"] == "backend")

    env = {item["name"]: item for item in backend["env"]}
    assert env["DEEPTUTOR_RUNTIME_MODE"]["value"] == "kubernetes"
    assert env["DEEPTUTOR_EXECUTION_MODE"]["value"] == "single"
    for secret_name in [
        "DEEPTUTOR_DATABASE_URL",
        "DEEPTUTOR_POSTGRES_MIGRATION_DATABASE_URL",
        "DEEPTUTOR_OBJECTSTORE_ACCESS_KEY",
        "DEEPTUTOR_OBJECTSTORE_SECRET_KEY",
    ]:
        assert "valueFrom" in env[secret_name]
        assert "value" not in env[secret_name]
    assert env["DEEPTUTOR_OBJECTSTORE_ACCESS_KEY_REF"]["value"].startswith("env:")
    assert env["DEEPTUTOR_OBJECTSTORE_SECRET_KEY_REF"]["value"].startswith("env:")

    volumes = {volume["name"]: volume for volume in pod.get("volumes", [])}
    assert set(volumes) >= {"scratch", "config-projection"}
    assert all("persistentVolumeClaim" not in volume for volume in volumes.values())
    mounts = {mount["name"]: mount for mount in backend.get("volumeMounts", [])}
    assert mounts["scratch"]["mountPath"] == "/tmp/deeptutor"
    assert mounts["config-projection"]["readOnly"] is True
