#!/usr/bin/env bash
set -euo pipefail

apt-get update
apt-get install -y ca-certificates curl git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
architecture="$(dpkg --print-architecture)"
codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
echo "deb [arch=${architecture} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

CONTAINERLAB_VERSION="0.83.0"
case "${architecture}" in
  amd64|arm64) ;;
  *)
    echo "unsupported Containerlab architecture: ${architecture}" >&2
    exit 1
    ;;
esac
containerlab_deb="/tmp/containerlab_${CONTAINERLAB_VERSION}_linux_${architecture}.deb"
curl -fsSL "https://github.com/srl-labs/containerlab/releases/download/v${CONTAINERLAB_VERSION}/containerlab_${CONTAINERLAB_VERSION}_linux_${architecture}.deb" \
  -o "${containerlab_deb}"
apt-get install -y "${containerlab_deb}"
rm -f "${containerlab_deb}"
containerlab version

mkdir -p /opt/netpulse
cat > /opt/netpulse/README <<'EOF'
NetPulse host prepared.

Docker and Containerlab 0.83.0 are installed. Deploy a reviewed NetPulse checkout to /opt/netpulse,
then run the documented topology and Docker Compose commands as an approved operator. This startup
script intentionally does not embed a repository URL, branch, credentials, or GCP project identifiers.
EOF
