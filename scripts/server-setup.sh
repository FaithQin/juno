#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 24.04 droplet. Run as root:  bash server-setup.sh
set -euo pipefail
# a fresh droplet runs its own updates on first boot; wait for the package lock to free up
while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || pgrep -x apt-get >/dev/null; do
  echo "waiting for the system's first-boot updates to finish..."; sleep 10
done
apt-get -o DPkg::Lock::Timeout=600 update -y
apt-get -o DPkg::Lock::Timeout=600 install -y ufw rsync
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH
ufw --force enable                    # nothing inbound but ssh; telegram polling is outbound
mkdir -p /opt/juno/data
echo "server ready. from your mac:  scripts/deploy.sh root@$(curl -s ifconfig.me)"
