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
next_dist_dir="${DEEPTUTOR_NEXT_DIST_DIR:-.next}"
if [ -n "${DEEPTUTOR_NEXT_BUILD_CPUS:-}" ]; then
  case "${DEEPTUTOR_NEXT_BUILD_CPUS}" in
    ''|*[!0-9]*)
      echo "DEEPTUTOR_NEXT_BUILD_CPUS must be a positive integer" >&2
      exit 2
      ;;
    *)
      if [ "${DEEPTUTOR_NEXT_BUILD_CPUS}" -lt 1 ]; then
        echo "DEEPTUTOR_NEXT_BUILD_CPUS must be >= 1" >&2
        exit 2
      fi
      # Next derives its default worker count from CIRCLE_NODE_TOTAL - 1.
      # Exporting this keeps CI builds from fanning out to every host CPU in a
      # memory-limited Woodpecker container.
      export CIRCLE_NODE_TOTAL="$((DEEPTUTOR_NEXT_BUILD_CPUS + 1))"
      ;;
  esac
fi
npm config set registry "${npm_registry}"
npm config set fetch-timeout 600000
npm config set fetch-retries 5
npm config set fetch-retry-mintimeout 20000
npm config set fetch-retry-maxtimeout 120000
npm ci --legacy-peer-deps --no-audit --no-fund
printf 'NEXT_PUBLIC_APP_VERSION=\n' > .env.local
npm run build

cd "${repo_root}"
standalone_source=""
static_source=""
resolve_next_artifacts() {
  local candidate
  for candidate in "web/${next_dist_dir}/standalone" web/.next/standalone web/.next-deeptutor/standalone; do
    if [ -d "${candidate}" ]; then
      standalone_source="${candidate}"
      static_source="$(dirname "${candidate}")/static"
      return 0
    fi
  done
  return 1
}
if ! resolve_next_artifacts; then
  echo "Next standalone output not present after npm run build; retrying with direct next build..."
  cd "${repo_root}/web"
  node ./node_modules/next/dist/bin/next build --webpack
  cd "${repo_root}"
fi
for attempt in $(seq 0 180); do
  if resolve_next_artifacts; then
    break
  fi
  if [ "${attempt}" -eq 180 ]; then
    break
  fi
  if [ $((attempt % 10)) -eq 0 ]; then
    echo "Waiting for Next standalone output (${attempt}s elapsed)..."
  fi
  sleep 1
done
if [ -z "${standalone_source}" ] || [ ! -d "${standalone_source}" ]; then
  echo "Next standalone output not found; searched ${next_dist_dir}, .next and .next-deeptutor" >&2
  find web -maxdepth 3 -type d -name standalone -print >&2 || true
  find web -maxdepth 2 -type d \( -name '.next*' -o -name 'standalone' -o -name 'static' \) -print >&2 || true
  exit 2
fi
cp -a "${standalone_source}" "${artifact_dir}/standalone"
cp -a "${static_source}" "${artifact_dir}/static"
if [ -d web/public ]; then
  cp -a web/public "${artifact_dir}/public"
else
  mkdir -p "${artifact_dir}/public"
fi

rm -rf web/node_modules web/.next/cache "${HOME:-/tmp}/.npm"

test -s "${artifact_dir}/standalone/server.js"
test -d "${artifact_dir}/static"
test -d "${artifact_dir}/public"
