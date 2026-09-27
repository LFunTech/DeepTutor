"""test-cn Webhook Secret 的受控发布路径（仅使用合成密钥）。"""

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SYNC = ROOT / "scripts/protected-k8s-release/sync-test-webhook-secret.py"


def _test_environment(
    tmp_path,
    *,
    target_env="test-cn",
    secret="synthetic-webhook-secret",
    digest_key="synthetic-independent-inbox-digest-key-0123456789",
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    fake_kubectl = fake_bin / "kubectl"
    fake_kubectl.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """import json, os, sys
from pathlib import Path
args = sys.argv[1:]
state = Path(os.environ["KUBECTL_STATE"])
log = Path(os.environ["KUBECTL_LOG"])
with log.open("a") as out:
    out.write(" ".join(args) + "\\n")
if "get" in args and "secret" in args:
    print(state.read_text())
elif "replace" in args and "-f" in args:
    state.write_text(json.dumps(json.load(sys.stdin)))
    print("secret/deeptutor-runtime-secrets replaced")
else:
    raise SystemExit(9)
""",
        encoding="utf8",
    )
    fake_kubectl.chmod(0o755)
    state = tmp_path / "secret.json"
    state.write_text(
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "deeptutor-runtime-secrets",
                    "namespace": "deeptutor-test-cn",
                    "resourceVersion": "123",
                },
                "type": "Opaque",
                "data": {
                    "DT_EDUPLUS2_WEBHOOK_SECRET": base64.b64encode(b"old-synthetic").decode(),
                    "OTHER_SECRET": base64.b64encode(b"preserve-synthetic").decode(),
                },
            }
        )
    )
    log = tmp_path / "kubectl.log"
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env["PATH"],
            "KUBECTL_STATE": str(state),
            "KUBECTL_LOG": str(log),
            "DEEPTUTOR_TARGET_ENV_ID": target_env,
            "DEEPTUTOR_K8S_NAMESPACE": "deeptutor-test-cn",
            "DT_TEST_CN_EDUPLUS2_WEBHOOK_SECRET": secret,
            "DT_TEST_CN_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY": digest_key,
            "KUBECONFIG_DATA": "apiVersion: v1\nclusters: []\ncontexts: []\n",
        }
    )
    return env, state, log


def test_test_cn_sync_updates_only_webhook_secret_without_leaking(tmp_path):
    env, state, log = _test_environment(tmp_path)
    first = subprocess.run([sys.executable, str(SYNC)], env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    data = json.loads(state.read_text())["data"]
    assert base64.b64decode(data["DT_EDUPLUS2_WEBHOOK_SECRET"]) == b"synthetic-webhook-secret"
    assert base64.b64decode(data["DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY"]) == (
        b"synthetic-independent-inbox-digest-key-0123456789"
    )
    assert base64.b64decode(data["OTHER_SECRET"]) == b"preserve-synthetic"
    second = subprocess.run([sys.executable, str(SYNC)], env=env, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert log.read_text().count("replace") == 1
    assert "synthetic-webhook-secret" not in first.stdout + first.stderr + log.read_text()


def test_test_cn_sync_rejects_other_environment_and_missing_secret_before_kubectl(tmp_path):
    env, _, log = _test_environment(tmp_path, target_env="prod-cn-east")
    denied = subprocess.run([sys.executable, str(SYNC)], env=env, capture_output=True, text=True)
    assert denied.returncode != 0
    assert not log.exists()
    env["DEEPTUTOR_TARGET_ENV_ID"] = "test-cn"
    env.pop("DT_TEST_CN_EDUPLUS2_WEBHOOK_SECRET")
    missing = subprocess.run([sys.executable, str(SYNC)], env=env, capture_output=True, text=True)
    assert missing.returncode != 0
    assert not log.exists()
    env, _, log = _test_environment(tmp_path / "missing-digest")
    env.pop("DT_TEST_CN_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY")
    missing_digest = subprocess.run(
        [sys.executable, str(SYNC)], env=env, capture_output=True, text=True
    )
    assert missing_digest.returncode != 0
    assert not log.exists()


def test_test_cn_sync_rejects_digest_rotation_and_key_reuse(tmp_path):
    env, state, log = _test_environment(tmp_path)
    data = json.loads(state.read_text())
    data["data"]["DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY"] = base64.b64encode(
        b"another-stable-digest-key-0123456789"
    ).decode()
    state.write_text(json.dumps(data))
    mismatch = subprocess.run([sys.executable, str(SYNC)], env=env, capture_output=True, text=True)
    assert mismatch.returncode != 0
    assert "replace" not in log.read_text()
    assert "synthetic-independent-inbox-digest-key-0123456789" not in (
        mismatch.stdout + mismatch.stderr
    )

    env, _, log = _test_environment(tmp_path / "reused-digest")
    env["DT_TEST_CN_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY"] = env[
        "DT_TEST_CN_EDUPLUS2_WEBHOOK_SECRET"
    ]
    reused = subprocess.run([sys.executable, str(SYNC)], env=env, capture_output=True, text=True)
    assert reused.returncode != 0
    assert not log.exists()


def test_test_cn_sync_accepts_wrapped_base64_kubeconfig(tmp_path):
    env, state, _ = _test_environment(tmp_path)
    encoded = base64.b64encode(env["KUBECONFIG_DATA"].encode()).decode()
    env["KUBECONFIG_DATA"] = "\n".join(encoded[i : i + 20] for i in range(0, len(encoded), 20))
    result = subprocess.run([sys.executable, str(SYNC)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert base64.b64decode(json.loads(state.read_text())["data"]["DT_EDUPLUS2_WEBHOOK_SECRET"]) == (
        b"synthetic-webhook-secret"
    )


def test_test_cn_release_retires_static_app_id_only_after_rollout(tmp_path):
    env, state, _ = _test_environment(tmp_path)
    current = json.loads(state.read_text())
    current["data"]["DT_EDUPLUS2_WEBHOOK_APP_ID"] = base64.b64encode(b"51").decode()
    state.write_text(json.dumps(current))
    before = subprocess.run([sys.executable, str(SYNC)], env=env, capture_output=True, text=True)
    assert before.returncode == 0, before.stderr
    assert "DT_EDUPLUS2_WEBHOOK_APP_ID" in json.loads(state.read_text())["data"]
    premature = subprocess.run(
        [sys.executable, str(SYNC), "--retire-legacy-app-id"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert premature.returncode != 0
    assert "DT_EDUPLUS2_WEBHOOK_APP_ID" in json.loads(state.read_text())["data"]
    env["DEEPTUTOR_WEBHOOK_ROLLOUT_COMPLETE"] = "yes"
    retired = subprocess.run(
        [sys.executable, str(SYNC), "--retire-legacy-app-id"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert retired.returncode == 0, retired.stderr
    updated = json.loads(state.read_text())["data"]
    assert "DT_EDUPLUS2_WEBHOOK_APP_ID" not in updated
    assert updated["OTHER_SECRET"] == current["data"]["OTHER_SECRET"]
    pipeline = (ROOT / ".woodpecker/protected-k8s-release.yml").read_text()
    deploy = re.search(r"\n  - name: deploy-test-cn\n(.*?)(?=\n  - name:|\Z)", pipeline, re.S)
    assert deploy is not None
    assert deploy.group(1).index("deploy/kubernetes/protected-k8s-release/deploy.sh") < deploy.group(
        1
    ).index("sync-test-webhook-secret.py --retire-legacy-app-id")


def test_test_cn_pipeline_limits_webhook_secret_to_preflight_and_deploy_steps():
    pipeline = (ROOT / ".woodpecker/protected-k8s-release.yml").read_text()
    deploy = re.search(r"\n  - name: deploy-test-cn\n(.*?)(?=\n  - name:|\Z)", pipeline, re.S)
    preflight = re.search(r"\n  - name: secret-preflight-test-cn\n(.*?)(?=\n  - name:|\Z)", pipeline, re.S)
    assert deploy is not None
    assert preflight is not None
    assert "from_secret: dt_test_cn_eduplus2_webhook_secret" in deploy.group(1)
    assert "from_secret: dt_test_cn_eduplus2_webhook_secret" in preflight.group(1)
    assert "from_secret: dt_test_cn_eduplus2_webhook_inbox_digest_key" in deploy.group(1)
    assert "from_secret: dt_test_cn_eduplus2_webhook_inbox_digest_key" in preflight.group(1)
    assert "sync-test-webhook-secret.py" in deploy.group(1)
    assert pipeline.count("from_secret: dt_test_cn_eduplus2_webhook_secret") == 2
    assert pipeline.count("from_secret: dt_test_cn_eduplus2_webhook_inbox_digest_key") == 2


def test_test_cn_release_contract_declares_webhook_secret_preflight():
    registry = json.loads(
        (ROOT / "extensions/enterprise/protected-k8s-release-environments.example.json").read_text()
    )
    test_env = next(item for item in registry["environments"] if item["env_id"] == "test-cn")
    webhook = next(
        item
        for item in test_env["woodpecker"]["secrets"]
        if item["logical_name"] == "EDUPLUS2_WEBHOOK_SECRET"
    )
    assert webhook["required"] is True
    assert webhook["scope_env_id"] == "test-cn"
    assert webhook["purpose"] == "runtime_secret_sync"
    digest = next(
        item
        for item in test_env["woodpecker"]["secrets"]
        if item["logical_name"] == "EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY"
    )
    assert digest["required"] is True
    assert digest["scope_env_id"] == "test-cn"
    assert digest["purpose"] == "runtime_secret_sync"
    collector = (ROOT / "scripts/protected-k8s-release/collect-secret-preflight-status.sh").read_text()
    assert '"EDUPLUS2_WEBHOOK_SECRET": "runtime_secret_sync"' in collector
    assert '"EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY": "runtime_secret_sync"' in collector
