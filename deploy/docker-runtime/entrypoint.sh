#!/bin/bash
set -e

echo "============================================"
echo "🚀 Starting DeepTutor"
echo "============================================"

export DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES=1

# Docker is JSON-driven. Ignore runtime env names even if the host or a stale
# Compose environment provides them; the entrypoint re-exports values from
# data/user/settings/*.json below.
for key in \
    BACKEND_PORT \
    BACKEND_WORKERS \
    DEEPTUTOR_BACKEND_WORKERS \
    FRONTEND_PORT \
    NEXT_PUBLIC_API_BASE_EXTERNAL \
    NEXT_PUBLIC_API_BASE \
    CORS_ORIGIN \
    CORS_ORIGINS \
    DISABLE_SSL_VERIFY \
    CHAT_ATTACHMENT_DIR \
    AUTH_ENABLED \
    NEXT_PUBLIC_AUTH_ENABLED \
    AUTH_USERNAME \
    AUTH_PASSWORD_HASH \
    AUTH_TOKEN_EXPIRE_HOURS \
    AUTH_COOKIE_SECURE \
    POCKETBASE_URL \
    POCKETBASE_PORT \
    POCKETBASE_EXTERNAL_URL \
    POCKETBASE_ADMIN_EMAIL \
    POCKETBASE_ADMIN_PASSWORD \
    DEEPTUTOR_API_BASE_URL \
    DEEPTUTOR_AUTH_ENABLED; do
    unset "$key"
done

# Initialize user data directories if empty
echo "📁 Checking data directories..."
echo "   Ensuring runtime settings and workspace layout..."
python -c "
from pathlib import Path
from deeptutor.services.setup import init_user_directories
init_user_directories(Path('/app'))
" 2>/dev/null || echo "   ⚠️ Directory initialization skipped (will be created on first use)"

# Idempotent: re-chown /app/data so the unprivileged `deeptutor` user (UID 1000)
# owns it. Cheap on no-op; the only first-start cost is one stat per file.
chown -R deeptutor:deeptutor /app/data 2>/dev/null || true

# Optional dependencies (#762). A container is disposable, so anything
# `docker exec … pip install`ed into a running one is gone at the next
# `compose down`. Declare them on the deployment instead and every container
# started from it has them:
#
#   environment:
#     DEEPTUTOR_EXTRAS: "math-animator,partners"
#     DEEPTUTOR_APT_PACKAGES: "ffmpeg"
#
# Both steps are idempotent — a warm container only pays a check — and neither
# is allowed to be fatal: a missing wheel leaves that one feature unavailable,
# exactly as it was before, rather than taking the whole deployment down.
# The pip cache lives on the data volume so a rebuild reuses the downloads it
# already paid for instead of fetching them again.
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/app/data/.cache/pip}"
mkdir -p "$PIP_CACHE_DIR" 2>/dev/null || true

if [ -n "${DEEPTUTOR_APT_PACKAGES:-}" ]; then
    echo "🔧 Ensuring system packages: ${DEEPTUTOR_APT_PACKAGES}"
    apt_missing=""
    for pkg in $(echo "${DEEPTUTOR_APT_PACKAGES}" | tr ',' ' '); do
        dpkg -s "$pkg" >/dev/null 2>&1 || apt_missing="$apt_missing $pkg"
    done
    if [ -z "$apt_missing" ]; then
        echo "   ✅ System packages already present"
    elif ! (apt-get update -qq && apt-get install -y --no-install-recommends $apt_missing); then
        echo "   ⚠️ apt-get failed; these packages stay unavailable:$apt_missing"
    fi
fi

if [ -n "${DEEPTUTOR_EXTRAS:-}" ]; then
    echo "🔧 Ensuring Python extras: ${DEEPTUTOR_EXTRAS}"
    python /app/scripts/install_extras.py "${DEEPTUTOR_EXTRAS}" || true
    chown -R deeptutor:deeptutor "$PIP_CACHE_DIR" 2>/dev/null || true
fi

echo "⚙️  Loading runtime JSON settings..."
eval "$(python - <<'PY'
import shlex
from deeptutor.services.config import export_runtime_settings_to_env

for key, value in export_runtime_settings_to_env(overwrite=True).items():
    print(f"export {key}={shlex.quote(str(value))}")
PY
)"

export BACKEND_PORT=${BACKEND_PORT:-8001}
export FRONTEND_PORT=${FRONTEND_PORT:-3782}

# DEEPTUTOR_API_BASE_URL and DEEPTUTOR_AUTH_ENABLED are exported by the
# export_runtime_settings_to_env eval above (see render_environment in
# deeptutor/services/config/runtime_settings.py). web/proxy.ts reads them at
# request time to rewrite /api/* and /ws/* to the backend and to gate the login
# redirect. Keeping them in the single JSON-backed exporter means the Docker and
# `deeptutor start` paths stay in sync.
echo "📌 API Base URL (proxy): ${DEEPTUTOR_API_BASE_URL:-http://localhost:${BACKEND_PORT}}"
echo "📌 Auth enabled: ${DEEPTUTOR_AUTH_ENABLED:-false}"

echo "📌 Backend Port: ${BACKEND_PORT}"
echo "📌 Frontend Port: ${FRONTEND_PORT}"

echo "============================================"
echo "📦 Configuration loaded from:"
echo "   - data/user/settings/system.json"
echo "   - data/user/settings/auth.json"
echo "   - data/user/settings/integrations.json"
echo "   - data/user/settings/model_catalog.json"
echo "   - data/user/settings/main.yaml"
echo "   - data/user/settings/agents.yaml"
echo "============================================"

# Hand off to supervisord as PID 1. The daemon-level config deliberately omits
# `user=` so supervisord inherits PID 1's UID and stays portable across rootful
# and rootless-keep-id runtimes; children drop to the deeptutor user via
# per-program `user=`. Full rationale lives next to the [supervisord] section
# in the build step that writes /etc/supervisor/supervisord.conf.
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
