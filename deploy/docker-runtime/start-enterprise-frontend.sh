#!/bin/bash
set -euo pipefail

ENTERPRISE_FRONTEND_APP=${ENTERPRISE_FRONTEND_APP:?missing enterprise frontend app name}
ENTERPRISE_FRONTEND_PORT=${ENTERPRISE_FRONTEND_PORT:?missing enterprise frontend port}
FRONTEND_HOST=${FRONTEND_HOST:-0.0.0.0}
server="/app/enterprise-frontends/${ENTERPRISE_FRONTEND_APP}/apps/${ENTERPRISE_FRONTEND_APP}/server.js"

if [ ! -r "${server}" ]; then
    echo "[Frontend:${ENTERPRISE_FRONTEND_APP}] missing standalone server: ${server}" >&2
    exit 1
fi

echo "[Frontend:${ENTERPRISE_FRONTEND_APP}] 🚀 Starting ${ENTERPRISE_FRONTEND_APP} Next.js frontend on ${FRONTEND_HOST}:${ENTERPRISE_FRONTEND_PORT}..."

export PORT=${ENTERPRISE_FRONTEND_PORT}
export HOSTNAME=${FRONTEND_HOST}
export DEEPTUTOR_ENTERPRISE_API_ORIGIN=${DEEPTUTOR_ENTERPRISE_API_ORIGIN:-http://127.0.0.1:${BACKEND_PORT:-8001}}
exec node "${server}"
