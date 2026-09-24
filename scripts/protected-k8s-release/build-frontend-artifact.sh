#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
artifact_dir="${DEEPTUTOR_FRONTEND_ARTIFACT_DIR:-${repo_root}/.deeptutor-build/frontend}"
npm_registry="${DEEPTUTOR_NPM_REGISTRY:-https://registry.npmjs.org/}"

cd "${repo_root}"
rm -rf "${artifact_dir}"
mkdir -p "${artifact_dir}"

cd "${repo_root}/web"
export NEXT_TELEMETRY_DISABLED="${NEXT_TELEMETRY_DISABLED:-1}"
npm config set registry "${npm_registry}"
npm config set fetch-timeout 600000
npm config set fetch-retries 5
npm config set fetch-retry-mintimeout 20000
npm config set fetch-retry-maxtimeout 120000
npm ci --legacy-peer-deps --no-audit --no-fund
printf 'NEXT_PUBLIC_APP_VERSION=\n' > .env.local
npm run build

cd "${repo_root}"
cp -a web/.next/standalone "${artifact_dir}/standalone"
cp -a web/.next/static "${artifact_dir}/static"
if [ -d web/public ]; then
  cp -a web/public "${artifact_dir}/public"
else
  mkdir -p "${artifact_dir}/public"
fi

rm -rf web/node_modules web/.next/cache "${HOME:-/tmp}/.npm"

test -s "${artifact_dir}/standalone/server.js"
test -d "${artifact_dir}/static"
test -d "${artifact_dir}/public"
