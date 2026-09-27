"""test-cn 第三方文档站的发布拓扑与对外访问门禁。"""

from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import yaml

ROOT = Path(__file__).resolve().parents[3]
K8S = ROOT / "deploy/kubernetes/protected-k8s-release"
REPO = "docker-hub.f123.pub/lfun/deeptutor/test-cn"


def test_docs_build_is_parallel_to_frontend_and_test_cn_only():
    pipeline = yaml.safe_load((ROOT / ".woodpecker/protected-k8s-release.yml").read_text())
    steps = {step["name"]: step for step in pipeline["steps"]}
    docs = steps["compile-docs-test-cn"]
    assert (
        docs["depends_on"]
        == steps["compile-frontend-test-cn"]["depends_on"]
        == ["prepare-release-metadata"]
    )
    assert docs["when"][0]["ref"] == "refs/tags/deploy/test-cn/**"
    commands = "\n".join(docs["commands"])
    assert "--context=dir:///woodpecker/src/docs-site" in commands
    assert "--dockerfile=/woodpecker/src/docs-site/Dockerfile" in commands
    assert "/docs:$${DEEPTUTOR_IMAGE_TAG}" in commands
    assert 'DOCS_SITE_URL="https://$${DEEPTUTOR_INGRESS_HOST}"' in commands
    assert "DOCS_BASE_URL=/docs/" in commands
    assert "compile-docs-test-cn" in steps["pre-deploy-check-test-cn"]["depends_on"]
    for env_id in ("pre-cn", "prod-cn-east", "prod-overseas-a"):
        assert f"compile-docs-{env_id}" not in steps
        assert "compile-docs-test-cn" not in steps[f"pre-deploy-check-{env_id}"]["depends_on"]


def test_docs_digest_is_locked_and_smoke_runs_after_deployment():
    pipeline = yaml.safe_load((ROOT / ".woodpecker/protected-k8s-release.yml").read_text())
    steps = {step["name"]: step for step in pipeline["steps"]}
    precheck = "\n".join(steps["pre-deploy-check-test-cn"]["commands"])
    deploy = "\n".join(steps["deploy-test-cn"]["commands"])
    assert "/docs/manifests/$${DEEPTUTOR_IMAGE_TAG}" in precheck
    assert "DEEPTUTOR_DOCS_IMAGE_DIGEST" in precheck
    assert "docs@" in precheck
    assert "docs-image-digest.json" in precheck
    assert "check-docs-site.py" in deploy
    assert '"https://$${DEEPTUTOR_INGRESS_HOST}"' in deploy
    assert "scan-evidence" in deploy


def test_ingress_routes_docs_only_in_test_cn_and_docs_pod_is_isolated():
    base_ingress = yaml.safe_load((K8S / "ingress.yaml").read_text())
    test_ingress = yaml.safe_load((K8S / "ingress-test-cn.yaml").read_text())
    docs_resources = [
        doc for doc in yaml.safe_load_all((K8S / "docs-test-cn.yaml").read_text()) if doc
    ]
    assert [doc["kind"] for doc in docs_resources] == ["Deployment", "Service", "NetworkPolicy"]
    assert (
        base_ingress["metadata"]["name"] == test_ingress["metadata"]["name"] == "deeptutor-backend"
    )
    base_paths = base_ingress["spec"]["rules"][0]["http"]["paths"]
    test_paths = test_ingress["spec"]["rules"][0]["http"]["paths"]
    assert [(path["path"], path["backend"]["service"]["name"]) for path in base_paths] == [
        ("/", "deeptutor-backend")
    ]
    assert [(path["path"], path["backend"]["service"]["name"]) for path in test_paths] == [
        ("/docs", "deeptutor-docs"),
        ("/", "deeptutor-backend"),
    ]
    deployment, service, policy = docs_resources
    assert deployment["spec"]["template"]["spec"]["serviceAccountName"] == "deeptutor-runtime"
    assert deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    assert (
        deployment["spec"]["template"]["spec"]["containers"][0]["image"]
        == "${DEEPTUTOR_DOCS_IMAGE_DIGEST}"
    )
    assert service["spec"]["ports"][0]["targetPort"] == "docs-http"
    assert policy["spec"]["policyTypes"] == ["Ingress", "Egress"]
    assert policy["spec"]["ingress"][0]["ports"][0]["port"] == 8080
    assert policy["spec"]["egress"] == []


def test_test_cn_rejects_missing_or_foreign_docs_digest_before_kubectl():
    script = K8S / "deploy.sh"
    env = os.environ.copy()
    env.update(
        {
            "DEEPTUTOR_DEPLOY_APPROVED": "yes",
            "DEEPTUTOR_TARGET_ENV_ID": "test-cn",
            "DEEPTUTOR_RELEASE_ID": "test-cn-v1-4-0",
            "DEEPTUTOR_RUNTIME_IMAGE_DIGEST": f"{REPO}/runtime@sha256:{'1' * 64}",
            "DEEPTUTOR_REGISTRY_REPOSITORY": REPO,
            "DEEPTUTOR_K8S_NAMESPACE": "deeptutor-test-cn",
            "DEEPTUTOR_INGRESS_HOST": "llm-agent-test.f123.pub",
            "DEEPTUTOR_TLS_SECRET_NAME": "deeptutor-test-cn-tls",
            "DEEPTUTOR_RELEASE_LOCK_REF": "postgres:test-cn/release_locks",
            "DEEPTUTOR_MIGRATION_LOCK_REF": "postgres:test-cn/migration_locks",
            "KUBECONFIG_DATA": "apiVersion: v1\nclusters: []\ncontexts: []\n",
        }
    )
    for bad_digest in (
        None,
        f"{REPO}/runtime@sha256:{'2' * 64}",
        f"docker-hub.f123.pub/lfun/deeptutor/pre-cn/docs@sha256:{'2' * 64}",
    ):
        if bad_digest is None:
            env.pop("DEEPTUTOR_DOCS_IMAGE_DIGEST", None)
        else:
            env["DEEPTUTOR_DOCS_IMAGE_DIGEST"] = bad_digest
        result = subprocess.run(
            ["bash", str(script)], cwd=ROOT, env=env, text=True, capture_output=True, check=False
        )
        assert result.returncode != 0
        assert "docs image digest" in result.stderr.lower()
        assert "kubectl" not in result.stderr.lower()


def test_deploy_selects_test_cn_docs_ingress_without_affecting_pre_cn(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python").symlink_to(sys.executable)
    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$KUBECTL_LOG"
if [[ "$*" == *"get configmap deeptutor-deployment-config"* ]]; then
  printf '%s\\n' '{"data":{"deployment.json":"{\\"origins\\":[\\"https://old.example\\"]}"}}'
  exit 0
fi
if [[ "$*" == *"get job/"* && "$*" == *"Complete"* ]]; then
  printf 'True'
  exit 0
fi
if [[ "$*" == *"apply -f -"* ]]; then
  cat >> "$APPLIED_MANIFESTS"
  printf '\\n---\\n' >> "$APPLIED_MANIFESTS"
fi
exit 0
""",
        encoding="utf8",
    )
    fake_kubectl.chmod(0o755)
    for env_id in ("test-cn", "pre-cn"):
        applied = tmp_path / f"{env_id}-manifests.yaml"
        log = tmp_path / f"{env_id}-kubectl.log"
        home = tmp_path / f"{env_id}-home"
        home.mkdir()
        repo = f"registry.example/deeptutor/{env_id}"
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                "HOME": str(home),
                "APPLIED_MANIFESTS": str(applied),
                "KUBECTL_LOG": str(log),
                "DEEPTUTOR_DEPLOY_APPROVED": "yes",
                "DEEPTUTOR_TARGET_ENV_ID": env_id,
                "DEEPTUTOR_RELEASE_ID": f"{env_id}-v1-4-0",
                "DEEPTUTOR_RUNTIME_IMAGE_DIGEST": f"{repo}/runtime@sha256:{'1' * 64}",
                "DEEPTUTOR_REGISTRY_REPOSITORY": repo,
                "DEEPTUTOR_K8S_NAMESPACE": f"deeptutor-{env_id}",
                "DEEPTUTOR_INGRESS_HOST": f"{env_id}.example.com",
                "DEEPTUTOR_TLS_SECRET_NAME": f"deeptutor-{env_id}-tls",
                "DEEPTUTOR_RELEASE_LOCK_REF": f"postgres:{env_id}/release_locks",
                "DEEPTUTOR_MIGRATION_LOCK_REF": f"postgres:{env_id}/migration_locks",
                "DEEPTUTOR_MIGRATION_POLL_INTERVAL_SECONDS": "0",
                "KUBECONFIG_DATA": "apiVersion: v1\nclusters: []\ncontexts: []\n",
            }
        )
        if env_id == "test-cn":
            env["DEEPTUTOR_DOCS_IMAGE_DIGEST"] = f"{repo}/docs@sha256:{'2' * 64}"
        else:
            env.pop("DEEPTUTOR_DOCS_IMAGE_DIGEST", None)
        result = subprocess.run(
            ["bash", str(K8S / "deploy.sh")],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        resources = [doc for doc in yaml.safe_load_all(applied.read_text()) if doc]
        docs_deployments = [
            doc
            for doc in resources
            if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "deeptutor-docs"
        ]
        ingress = next(doc for doc in resources if doc["kind"] == "Ingress")
        paths = ingress["spec"]["rules"][0]["http"]["paths"]
        if env_id == "test-cn":
            assert len(docs_deployments) == 1
            assert docs_deployments[0]["spec"]["template"]["spec"]["containers"][0]["image"] == (
                f"{repo}/docs@sha256:{'2' * 64}"
            )
            assert [path["path"] for path in paths] == ["/docs", "/"]
            assert "rollout status deployment/deeptutor-docs" in log.read_text()
        else:
            assert docs_deployments == []
            assert [path["path"] for path in paths] == ["/"]
            assert "rollout status deployment/deeptutor-docs" not in log.read_text()


def test_docs_static_image_serves_only_docs_prefix_without_privileged_port():
    dockerfile = (ROOT / "docs-site/Dockerfile").read_text()
    nginx = (ROOT / "docs-site/nginx.conf").read_text()
    assert "npm ci" in dockerfile
    assert "npm run typecheck" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=builder /app/build/ /usr/share/nginx/html/docs/" in dockerfile
    assert "USER 101:101" in dockerfile
    assert "listen 8080" in nginx
    assert "location = /docs" in nginx
    assert "location ^~ /docs/" in nginx
    assert "location / {" in nginx
    assert "return 404" in nginx


def test_docs_https_check_verifies_home_and_referenced_asset(tmp_path):
    site = tmp_path / "site"
    (site / "docs/assets/css").mkdir(parents=True)
    (site / "docs/index.html").write_text(
        "<!doctype html><html><head><title>智能体基座 Agent 开发者文档</title>"
        '<link rel="stylesheet" href="/docs/assets/css/styles.css"></head><body>ok</body></html>',
        encoding="utf8",
    )
    (site / "docs/assets/css/styles.css").write_text("body{color:black}", encoding="utf8")

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(site)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        output = tmp_path / "docs-smoke.json"
        command = [
            sys.executable,
            str(ROOT / "scripts/protected-k8s-release/check-docs-site.py"),
            "--origin",
            f"http://127.0.0.1:{server.server_port}",
            "--output",
            str(output),
            "--allow-http-for-test",
        ]
        rejected = subprocess.run(command[:-1], cwd=ROOT, text=True, capture_output=True, check=False)
        assert rejected.returncode != 0
        assert json.loads(output.read_text())["error_code"] == "invalid_origin"
        ok = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert ok.returncode == 0, ok.stderr
        evidence = json.loads(output.read_text())
        assert evidence["ready"] is True
        assert evidence["homepage_path"] == "/docs/"
        assert evidence["asset_path"] == "/docs/assets/css/styles.css"
        (site / "docs/assets/css/styles.css").unlink()
        bad = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert bad.returncode != 0
        assert json.loads(output.read_text())["ready"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
