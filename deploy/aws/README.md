# Hosting Marswalk Planner on AWS Lightsail

One small Ubuntu server runs the app; Caddy in front gives it HTTPS on a free `sslip.io` name
(`https://1-2-3-4.sslip.io` for IP 1.2.3.4), so no domain is needed. The AI is Claude through the Anthropic API,
so no GPU is needed.

## 1. Create the server (AWS console, ~5 minutes)

1. Open **Lightsail** (https://lightsail.aws.amazon.com) → **Create instance**.
2. Region: one close to your visitors. Platform **Linux/Unix**, blueprint **OS Only → Ubuntu 24.04 LTS**.
3. SSH key: keep the default key for the region (you download it in step 6).
4. Plan: **2 GB RAM** is comfortable; **1 GB** also works (the setup adds 2 GB swap). Check the price shown.
5. Name it `marswalk` → **Create instance**.
6. When it is running:
   - **Networking** tab → **Attach static IP** (free while attached), so the address never changes.
   - **Networking** tab → IPv4 firewall → **Add rule**: HTTPS (TCP 443). HTTP (80) and SSH (22) are already open.
   - **Account → SSH keys** → download the default key for that region (a `.pem` file), e.g. to `~/.ssh/`,
     then `chmod 600 ~/.ssh/LightsailDefaultKey-*.pem`.
7. In the Anthropic console, set a **monthly spending limit** for the Claude key: every visitor's mission uses it.

## 2. Install and deploy (from this repo, on your computer)

```bash
# first time: installs Python, the app service, Caddy, swap, and stores the Claude key on the server only
ANTHROPIC_API_KEY=sk-ant-... deploy/aws/deploy.sh <static-ip> ~/.ssh/LightsailDefaultKey-<region>.pem --setup

# every later update (deploys the committed code, git HEAD)
deploy/aws/deploy.sh <static-ip> ~/.ssh/LightsailDefaultKey-<region>.pem
```

The setup prints the public address, e.g. `https://1-2-3-4.sslip.io` (the certificate is issued on the first visit,
which takes a few seconds). `http://<static-ip>` works too.

## Running it

- Logs: `ssh -i <key> ubuntu@<ip> 'journalctl -u marswalk -f'`
- Restart: `ssh -i <key> ubuntu@<ip> 'sudo systemctl restart marswalk'`
- Change the AI settings: edit `~/marswalk/ai.env` on the server (keep it `chmod 600`), then restart.
- Areas built on demand and downloaded data stay on the server's disk between deploys.
- To stop paying: delete the instance **and** release the static IP in Lightsail.
