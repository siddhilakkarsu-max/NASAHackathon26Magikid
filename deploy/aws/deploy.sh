#!/usr/bin/env bash
# Deploy Marswalk Planner from this machine to an AWS Lightsail / EC2 Ubuntu server.
#   deploy/aws/deploy.sh <server-ip> <path-to-ssh-key.pem>          # copy the code, restart the app
#   ANTHROPIC_API_KEY=... deploy/aws/deploy.sh <ip> <key> --setup   # first time: also install everything
# Copies the committed code (git HEAD), so local experiments aren't published. Built areas, downloads and
# ai.env on the server are kept between deploys.
set -euo pipefail
IP=${1:?usage: deploy.sh <server-ip> <ssh-key.pem> [--setup]}
KEY=${2:?usage: deploy.sh <server-ip> <ssh-key.pem> [--setup]}
SETUP=${3:-}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15 "ubuntu@$IP")

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git -C "$ROOT" archive --format=tar HEAD | tar -x -C "$TMP"
rm -rf "$TMP/tests" "$TMP/docs"
if grep -rlIE "sk-ant-[A-Za-z0-9_-]{20,}" "$TMP" >/dev/null; then echo "refusing: something in the code looks like an API key"; exit 1; fi

"${SSH[@]}" "mkdir -p ~/marswalk"
rsync -az -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" "$TMP/" "ubuntu@$IP:marswalk/"
if [ "$SETUP" = "--setup" ]; then
  # the key travels over SSH on stdin and only into ~/marswalk/ai.env (chmod 600)
  printf '%s' "${ANTHROPIC_API_KEY:-}" | "${SSH[@]}" 'read -r K; ANTHROPIC_API_KEY="$K" bash ~/marswalk/deploy/aws/setup_server.sh'
else
  "${SSH[@]}" "cd ~/marswalk && .venv/bin/pip install -q -r requirements.txt && sudo systemctl restart marswalk && for i in \$(seq 60); do curl -sf http://127.0.0.1:8000/api/sites >/dev/null && break; sleep 1; done; curl -s -o /dev/null -w 'app: %{http_code}\n' http://127.0.0.1:8000/"
fi
echo "Deployed $(git -C "$ROOT" rev-parse --short HEAD) to $IP"
