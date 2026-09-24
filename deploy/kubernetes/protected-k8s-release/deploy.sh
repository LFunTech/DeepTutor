#!/usr/bin/env bash
set -euo pipefail

if [ "${DEEPTUTOR_DEPLOY_APPROVED:-}" != "yes" ]; then
  echo "DEEPTUTOR_DEPLOY_APPROVED=yes is required" >&2
  exit 1
fi

: "${DEEPTUTOR_TARGET_ENV_ID:?must be set}"
: "${DEEPTUTOR_RELEASE_ID:?must be set}"
: "${DEEPTUTOR_RUNTIME_IMAGE_DIGEST:?must be set}"
: "${DEEPTUTOR_K8S_NAMESPACE:?must be set}"
: "${DEEPTUTOR_INGRESS_HOST:?must be set}"
: "${DEEPTUTOR_TLS_SECRET_NAME:?must be set}"
: "${DEEPTUTOR_RELEASE_LOCK_REF:?must be set}"
: "${DEEPTUTOR_MIGRATION_LOCK_REF:?must be set}"
: "${KUBECONFIG_DATA:?must be set}"

namespace="${DEEPTUTOR_K8S_NAMESPACE}"
manifest_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
migration_job_name="dt-migrate-${DEEPTUTOR_RELEASE_ID}"
backend_executor_replicas="${DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS:-1}"
execution_mode="${DEEPTUTOR_EXECUTION_MODE:-single}"
turn_coordination_backend="${DEEPTUTOR_TURN_COORDINATION_BACKEND:-memory}"
hpa_enabled="${DEEPTUTOR_HPA_ENABLED:-false}"
redis_key_prefix="${DEEPTUTOR_REDIS_KEY_PREFIX:-deeptutor-${DEEPTUTOR_TARGET_ENV_ID}}"

case "${backend_executor_replicas}" in
  ''|*[!0-9]*)
    echo "DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS must be a positive integer" >&2
    exit 1
    ;;
esac
if [ "${backend_executor_replicas}" -lt 1 ]; then
  echo "DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS must be >= 1" >&2
  exit 1
fi
case "${execution_mode}" in
  single|replicated)
    ;;
  *)
    echo "DEEPTUTOR_EXECUTION_MODE must be single or replicated" >&2
    exit 1
    ;;
esac
expected_execution_mode="single"
if [ "${backend_executor_replicas}" -gt 1 ] || [ "${hpa_enabled}" = "true" ]; then
  expected_execution_mode="replicated"
fi
if [ "${execution_mode}" != "${expected_execution_mode}" ]; then
  echo "DEEPTUTOR_EXECUTION_MODE must be ${expected_execution_mode} for the requested backend topology" >&2
  exit 1
fi
if [ "${backend_executor_replicas}" -gt 1 ] && [ "${turn_coordination_backend}" != "redis" ]; then
  echo "backend replicas > 1 requires DEEPTUTOR_TURN_COORDINATION_BACKEND=redis" >&2
  exit 1
fi
if [ "${hpa_enabled}" = "true" ]; then
  : "${DEEPTUTOR_HPA_MIN_REPLICAS:?must be set when HPA is enabled}"
  : "${DEEPTUTOR_HPA_MAX_REPLICAS:?must be set when HPA is enabled}"
  : "${DEEPTUTOR_HPA_TARGET_CPU_UTILIZATION_PERCENTAGE:?must be set when HPA is enabled}"
  if [ "${turn_coordination_backend}" != "redis" ]; then
    echo "HPA requires DEEPTUTOR_TURN_COORDINATION_BACKEND=redis" >&2
    exit 1
  fi
elif [ "${hpa_enabled}" != "false" ]; then
  echo "DEEPTUTOR_HPA_ENABLED must be true or false" >&2
  exit 1
fi
export DEEPTUTOR_BACKEND_EXECUTOR_REPLICAS="${backend_executor_replicas}"
export DEEPTUTOR_EXECUTION_MODE="${execution_mode}"
export DEEPTUTOR_TURN_COORDINATION_BACKEND="${turn_coordination_backend}"
export DEEPTUTOR_REDIS_KEY_PREFIX="${redis_key_prefix}"
export DEEPTUTOR_HPA_ENABLED="${hpa_enabled}"

kube_dir="${HOME:-/tmp}/.kube"
kubeconfig_path="${kube_dir}/deeptutor-protected-k8s-release-${DEEPTUTOR_TARGET_ENV_ID}.yaml"
mkdir -p "${kube_dir}"
if printf '%s' "${KUBECONFIG_DATA}" | grep -q '^apiVersion:'; then
  printf '%s\n' "${KUBECONFIG_DATA}" > "${kubeconfig_path}"
else
  printf '%s' "${KUBECONFIG_DATA}" | base64 -d > "${kubeconfig_path}"
fi
chmod 600 "${kubeconfig_path}"
export KUBECONFIG="${kubeconfig_path}"
cleanup() {
  rm -f "${kubeconfig_path}"
}
trap cleanup EXIT

render_manifest() {
  local source_path="$1"
  python - "$source_path" <<'PY'
from __future__ import annotations

import os
import string
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf8")
print(string.Template(source).safe_substitute(os.environ))
PY
}

kubectl cluster-info >/dev/null
kubectl -n "${namespace}" get namespace "${namespace}" >/dev/null

render_manifest "${manifest_dir}/networkpolicy.yaml" | kubectl -n "${namespace}" apply -f -
render_manifest "${manifest_dir}/migration-job.yaml" | kubectl -n "${namespace}" apply -f -
if ! kubectl -n "${namespace}" wait --for=condition=complete --timeout="${DEEPTUTOR_MIGRATION_TIMEOUT:-900s}" "job/${migration_job_name}"; then
  kubectl -n "${namespace}" get pods -l job-name="${migration_job_name}" -o wide >&2 || true
  kubectl -n "${namespace}" logs "job/${migration_job_name}" --all-containers=true >&2 || true
  kubectl -n "${namespace}" describe job "${migration_job_name}" >&2 || true
  exit 1
fi
kubectl -n "${namespace}" logs "job/${migration_job_name}" --all-containers=true || true

render_manifest "${manifest_dir}/backend.yaml" | kubectl -n "${namespace}" apply -f -
if [ "${hpa_enabled}" = "true" ]; then
  render_manifest "${manifest_dir}/patches/autoscaling/hpa.yaml" | kubectl -n "${namespace}" apply -f -
fi
kubectl -n "${namespace}" rollout status deployment/deeptutor-backend --timeout="${DEEPTUTOR_ROLLOUT_TIMEOUT:-600s}"
