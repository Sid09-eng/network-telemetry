#!/usr/bin/env bash
# Bring up the local, synthetic NetPulse demonstration on a prepared Linux host.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "NetPulse topology execution requires Linux (a Linux devcontainer or VM is fine)." >&2
  exit 1
fi

for command in python3 docker containerlab make; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

make check
make topology-up
make topology-check
make monitoring-up
curl --fail --silent --show-error http://127.0.0.1:9090/-/ready
echo
echo "NetPulse is ready: Grafana is available at http://127.0.0.1:3000"
