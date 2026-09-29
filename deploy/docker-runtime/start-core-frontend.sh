#!/bin/bash
set -e

CORE_FRONTEND_PORT=${CORE_FRONTEND_PORT:-3785}
FRONTEND_HOST=${FRONTEND_HOST:-0.0.0.0}
echo "[Frontend:core] 🚀 Starting core Next.js frontend on ${FRONTEND_HOST}:${CORE_FRONTEND_PORT}..."

export PORT=${CORE_FRONTEND_PORT}
export HOSTNAME=${FRONTEND_HOST}
exec node /app/web/server.js
