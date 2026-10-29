#!/usr/bin/env bash
# First setup of a fresh Ubuntu 24.04 server (the IONOS Cube). Run once as root:
#   bash bootstrap-ubuntu.sh
#
# What it does:
#   1. updates the system and turns on automatic security updates
#   2. creates the user "deploy" (same SSH key as root, may use sudo and docker)
#   3. installs Docker from the official Docker repository
#   4. adds 2 GB of swap (the Cube has 4 GB RAM, the models are big)
#   5. turns on a firewall (only SSH, HTTP, HTTPS) and fail2ban (blocks SSH guessing)
#
# It does NOT turn off the login of root. Do that by hand after you have checked that
# "ssh deploy@<ip>" works (see the end of the output), so you cannot lock yourself out.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root." >&2
    exit 1
fi

echo "== 1/5 update the system"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl ufw fail2ban unattended-upgrades

echo "== 2/5 create the user deploy"
if ! id deploy >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" deploy
fi
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
usermod -aG sudo deploy
# Login only works with the SSH key (no password), so sudo without a password is acceptable here
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-deploy
chmod 440 /etc/sudoers.d/90-deploy

echo "== 3/5 install Docker (official repository)"
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
usermod -aG docker deploy
systemctl enable --now docker

echo "== 4/5 swap (2 GB)"
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 5/5 firewall and fail2ban"
# ufw allows SSH first, so turning it on cannot lock us out
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl enable --now fail2ban

echo
echo "== done"
docker --version
docker compose version
free -h | sed -n '1,3p'
echo
echo "Next, on your Mac:  ssh -i ~/.ssh/ionos_ortsbild deploy@<ip>"
echo "If that works, turn off the root login (as deploy):"
echo "  sudo sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config"
echo "  sudo sed -i 's/^#\\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config"
echo "  sudo systemctl restart ssh"
