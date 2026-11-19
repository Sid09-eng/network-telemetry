#!/usr/bin/env bash
# Bring up the local, synthetic NetPulse demonstration on a prepared Linux host.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "NetPulse topology execution requires Linux (a Linux devcontainer or VM is fine)." >&2
  exit 1
fi

for command in python3 docker containerlab make curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done

if ! python3 -c 'import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] <= (3, 12)))'; then
  echo "Python 3.11 or 3.12 is required." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

if ! grep -Eq '^GRAFANA_ADMIN_PASSWORD=.+$' .env; then
  echo "Set a unique GRAFANA_ADMIN_PASSWORD in .env before running NetPulse." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

wait_for_http() {
  local url="$1"
  local deadline=$((SECONDS + 60))
  local remaining
  while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    if (( remaining <= 0 )); then
      break
    fi
    if curl --fail --silent --connect-timeout 2 --max-time "$remaining" "$url" >/dev/null; then
      return 0
    fi
    if (( SECONDS < deadline )); then
      sleep 1
    fi
  done
  echo "Timed out waiting for ${url} after 60 seconds." >&2
  return 1
}

make check
make topology-up
make topology-check
make monitoring-up
wait_for_http http://127.0.0.1:9090/-/ready
echo
echo "NetPulse is ready: Grafana is available at http://127.0.0.1:3000"
