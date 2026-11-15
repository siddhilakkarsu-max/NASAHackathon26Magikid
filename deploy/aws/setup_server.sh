#!/usr/bin/env bash
# One-time (and safe to re-run) setup of a fresh Ubuntu 24.04 server (AWS Lightsail or EC2) for Marswalk Planner.
# deploy.sh copies the code to ~/marswalk first, then runs this on the server as the "ubuntu" user:
#   - 2 GB swap, Python venv + requirements, the app as a systemd service on 127.0.0.1:8000
#   - Caddy in front: HTTPS at https://<ip-with-dashes>.sslip.io (free name, real certificate), plus plain :80
#   - ~/marswalk/ai.env (chmod 600) with the Claude key, read from $ANTHROPIC_API_KEY when given
set -euo pipefail
APP=/home/ubuntu/marswalk
cd "$APP"

echo "== security updates (Lightsail flags pending Linux CVEs on new instances)"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get -y -qq -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
  full-upgrade >/dev/null
if command -v php >/dev/null; then echo "note: PHP is installed on this server ($(php -r 'echo PHP_VERSION;')); Marswalk doesn't use it"; fi

echo "== packages"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip caddy curl unattended-upgrades >/dev/null

echo "== swap (2 GB, so building a new area never runs out of memory)"
if ! sudo swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== python"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "== AI settings (ai.env)"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  umask 077
  cat > ai.env <<EOF
# Claude (Anthropic API) runs the planner's AI. Keep this file private (chmod 600); never commit it.
export ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
export CLAUDE_MODEL=claude-haiku-5-5
export CLAUDE_EFFORT=medium
export AI_PARALLEL=8
EOF
fi
[ -f ai.env ] || { echo "ai.env missing: rerun with ANTHROPIC_API_KEY set"; exit 1; }
chmod 600 ai.env

echo "== app service"
sudo tee /etc/systemd/system/marswalk.service >/dev/null <<EOF
[Unit]
Description=Marswalk Planner (FastAPI)
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=$APP
ExecStart=/bin/bash -c 'source $APP/ai.env && exec $APP/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 5'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q marswalk
sudo systemctl restart marswalk

echo "== Caddy (HTTPS)"
IP=$(curl -s -4 --max-time 5 https://checkip.amazonaws.com || curl -s -4 --max-time 5 https://ifconfig.co || true)
HOST=""
[ -n "$IP" ] && HOST="$(echo "$IP" | tr . -).sslip.io"
{
  echo "# Marswalk Planner behind Caddy: plain http on :80, and HTTPS on the free sslip.io name when known."
  if [ -n "$HOST" ]; then
    printf '%s {\n\tencode gzip\n\treverse_proxy 127.0.0.1:8000\n}\n' "$HOST"
  fi
  printf ':80 {\n\tencode gzip\n\treverse_proxy 127.0.0.1:8000\n}\n'
} | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl reload caddy || sudo systemctl restart caddy

echo "== check"
for i in $(seq 60); do curl -sf http://127.0.0.1:8000/api/sites >/dev/null && break; sleep 1; done
curl -s -o /dev/null -w "app: %{http_code}\n" http://127.0.0.1:8000/
[ -n "$HOST" ] && echo "Public address: https://$HOST  (and http://$IP)"
[ -f /var/run/reboot-required ] && echo "REBOOT-REQUIRED" || true
