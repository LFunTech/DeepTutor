#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
artifact_dir="${DEEPTUTOR_PYTHON_PREFIX_ARTIFACT_DIR:-${repo_root}/.deeptutor-build/python-prefix}"
apt_debian_mirror="${DEEPTUTOR_APT_DEBIAN_MIRROR:-http://deb.debian.org/debian}"
apt_security_mirror="${DEEPTUTOR_APT_SECURITY_MIRROR:-http://deb.debian.org/debian-security}"
pip_index_url="${DEEPTUTOR_PIP_INDEX_URL:-https://pypi.org/simple}"
rustup_dist_server="${DEEPTUTOR_RUSTUP_DIST_SERVER:-https://static.rust-lang.org}"
rustup_update_root="${DEEPTUTOR_RUSTUP_UPDATE_ROOT:-https://static.rust-lang.org/rustup}"
cargo_registry_mirror="${DEEPTUTOR_CARGO_REGISTRY_MIRROR:-sparse+https://index.crates.io/}"

cd "${repo_root}"
rm -rf "${artifact_dir}"
mkdir -p "${artifact_dir}"

if [ -f /etc/apt/sources.list.d/debian.sources ]; then
  sed -i \
    -e "s|http://security.debian.org/debian-security|${apt_security_mirror}|g" \
    -e "s|https://security.debian.org/debian-security|${apt_security_mirror}|g" \
    -e "s|http://deb.debian.org/debian-security|${apt_security_mirror}|g" \
    -e "s|https://deb.debian.org/debian-security|${apt_security_mirror}|g" \
    -e "s|http://deb.debian.org/debian|${apt_debian_mirror}|g" \
    -e "s|https://deb.debian.org/debian|${apt_debian_mirror}|g" \
    /etc/apt/sources.list.d/debian.sources
fi
if [ -f /etc/apt/sources.list ]; then
  sed -i \
    -e "s|http://security.debian.org/debian-security|${apt_security_mirror}|g" \
    -e "s|https://security.debian.org/debian-security|${apt_security_mirror}|g" \
    -e "s|http://deb.debian.org/debian-security|${apt_security_mirror}|g" \
    -e "s|https://deb.debian.org/debian-security|${apt_security_mirror}|g" \
    -e "s|http://deb.debian.org/debian|${apt_debian_mirror}|g" \
    -e "s|https://deb.debian.org/debian|${apt_debian_mirror}|g" \
    /etc/apt/sources.list
fi
printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n' > /etc/apt/apt.conf.d/80-ci-retries

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  curl \
  git \
  build-essential \
  libgl1 \
  libglib2.0-0 \
  libsm6 \
  libxext6 \
  libxrender1 \
  pkg-config \
  libssl-dev
rm -rf /var/lib/apt/lists/*

mkdir -p /root/.cargo
printf '[source.crates-io]\nreplace-with = "mirror"\n\n[source.mirror]\nregistry = "%s"\n\n[registries.mirror]\nindex = "%s"\n' \
  "${cargo_registry_mirror}" "${cargo_registry_mirror}" > /root/.cargo/config.toml

export RUSTUP_DIST_SERVER="${rustup_dist_server}"
export RUSTUP_UPDATE_ROOT="${rustup_update_root}"
export CARGO_HOME=/root/.cargo
export PATH="/root/.cargo/bin:${PATH}"
export PIP_NO_CACHE_DIR=1
export PIP_DISABLE_PIP_VERSION_CHECK=1

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
python -m pip install --index-url "${pip_index_url}" --upgrade pip
python -m pip install --index-url "${pip_index_url}" --prefix "${artifact_dir}" -r requirements.txt

rm -rf /root/.cargo /root/.rustup "${HOME:-/root}/.cache/pip"
find "${artifact_dir}" -type d -name __pycache__ -prune -exec rm -rf {} +

test -d "${artifact_dir}/lib/python3.11/site-packages"
