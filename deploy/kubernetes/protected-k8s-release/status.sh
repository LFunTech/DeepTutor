#!/usr/bin/env bash
set -euo pipefail

namespace="${1:-${DEEPTUTOR_K8S_NAMESPACE:-}}"
if [ -z "${namespace}" ]; then
  echo "namespace argument or DEEPTUTOR_K8S_NAMESPACE is required" >&2
  exit 2
fi
app_name="${DEEPTUTOR_APP_NAME:-deeptutor-backend}"

cleanup_kubeconfig() {
  if [ -n "${generated_kubeconfig_path:-}" ]; then
    rm -f "${generated_kubeconfig_path}"
  fi
}

if [ -n "${KUBECONFIG_DATA:-}" ]; then
  kube_dir="${HOME:-/tmp}/.kube"
  target_env_id="${DEEPTUTOR_TARGET_ENV_ID:-status}"
  generated_kubeconfig_path="${kube_dir}/deeptutor-protected-k8s-release-${target_env_id}-status.yaml"
  mkdir -p "${kube_dir}"
  if printf '%s' "${KUBECONFIG_DATA}" | grep -q '^apiVersion:'; then
    printf '%s\n' "${KUBECONFIG_DATA}" > "${generated_kubeconfig_path}"
  else
    printf '%s' "${KUBECONFIG_DATA}" | base64 -d > "${generated_kubeconfig_path}"
  fi
  chmod 600 "${generated_kubeconfig_path}"
  export KUBECONFIG="${generated_kubeconfig_path}"
  trap cleanup_kubeconfig EXIT
fi

kubectl -n "${namespace}" get deployment "${app_name}" -o wide
kubectl -n "${namespace}" get pods -l app.kubernetes.io/name="${app_name}" -o wide
kubectl -n "${namespace}" get service "${app_name}" -o wide
kubectl -n "${namespace}" get ingress "${app_name}" -o wide || true
kubectl -n "${namespace}" get jobs -l app.kubernetes.io/part-of=deeptutor-protected-k8s-release -o wide || true
