#!/usr/bin/env bash
set -euo pipefail

namespace="${1:-${DEEPTUTOR_K8S_NAMESPACE:-}}"
if [ -z "${namespace}" ]; then
  echo "namespace argument or DEEPTUTOR_K8S_NAMESPACE is required" >&2
  exit 2
fi
app_name="${DEEPTUTOR_APP_NAME:-deeptutor-backend}"

kubectl -n "${namespace}" get deployment "${app_name}" -o wide
kubectl -n "${namespace}" get pods -l app.kubernetes.io/name="${app_name}" -o wide
kubectl -n "${namespace}" get service "${app_name}" -o wide
kubectl -n "${namespace}" get ingress "${app_name}" -o wide || true
kubectl -n "${namespace}" get jobs -l app.kubernetes.io/part-of=deeptutor-protected-k8s-release -o wide || true
