#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 droplet. Run as root:  bash server-setup.sh
set -euo pipefail
apt-get update -y
apt-get install -y ufw rsync
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH
ufw --force enable                    # nothing inbound but ssh; telegram polling is outbound
mkdir -p /opt/juno/data
echo "server ready. from your mac:  scripts/deploy.sh root@$(curl -s ifconfig.me)"
