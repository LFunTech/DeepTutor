#!/bin/bash
set -e

BACKEND_PORT=${BACKEND_PORT:-8001}
BACKEND_HOST=${BACKEND_HOST:-0.0.0.0}
BACKEND_WORKERS=${BACKEND_WORKERS:-1}

echo "[Backend]  🚀 Starting FastAPI backend on ${BACKEND_HOST}:${BACKEND_PORT}..."

# Run uvicorn directly - the application's logging system already handles:
# 1. Console output (visible in docker logs)
# 2. File logging to data/user/logs/ai_tutor_*.log
#
# BACKEND_HOST defaults to 0.0.0.0 (LAN-reachable, matches bridge-mode
# port publishing). Set BACKEND_HOST=127.0.0.1 when running with
# network_mode: host to keep the backend on loopback only.
#
# --ws-max-size: chat attachments travel base64 inside one WS message; derive
# the frame cap from the configured attachment policy (system.json) so uploads
# the policy allows are not severed by uvicorn's 16MB default.
#
# --timeout-keep-alive: the frontend proxy (web/proxy.ts) forwards over Node's
# http.globalAgent, which reaps idle sockets on a 5s timer — identical to
# uvicorn's default, so both ends raced to close the same socket and the loser's
# request died with ECONNRESET (a 500 in the UI). Stay well above the proxy's
# reaper so the client is the only side retiring idle connections.
WS_MAX_SIZE=$(python -c "from deeptutor.services.config import get_ws_max_size; print(get_ws_max_size())" 2>/dev/null || echo 16777216)
KEEP_ALIVE=$(python -c "from deeptutor.services.config import HTTP_KEEP_ALIVE_TIMEOUT; print(HTTP_KEEP_ALIVE_TIMEOUT)" 2>/dev/null || echo 300)
exec python -m uvicorn deeptutor.api.main:app --host ${BACKEND_HOST} --port ${BACKEND_PORT} --workers ${BACKEND_WORKERS} --no-access-log --no-proxy-headers --ws-max-size ${WS_MAX_SIZE} --timeout-keep-alive ${KEEP_ALIVE}
