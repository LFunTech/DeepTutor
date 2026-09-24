#!/bin/bash
set -e

FRONTEND_PORT=${FRONTEND_PORT:-3782}
FRONTEND_HOST=${FRONTEND_HOST:-0.0.0.0}
echo "[Frontend] 🚀 Starting Next.js frontend on ${FRONTEND_HOST}:${FRONTEND_PORT}..."

export PORT=${FRONTEND_PORT}
export HOSTNAME=${FRONTEND_HOST}
exec node /app/web/server.js
