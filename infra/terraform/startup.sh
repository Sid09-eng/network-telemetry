#!/usr/bin/env bash
set -euo pipefail
apt-get update
apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
mkdir -p /opt/netpulse
cat > /opt/netpulse/README <<'EOF'
NetPulse host prepared.

Deploy a reviewed NetPulse checkout to /opt/netpulse, then run the documented Docker Compose
commands as an approved operator. This startup script intentionally does not embed a repository
URL, branch, credentials, or GCP project identifiers.
EOF
