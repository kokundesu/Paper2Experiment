# Deploying the demo to a VPS

The demo (`p2e demo serve`) runs on an Ubuntu 24.04 VPS behind Caddy, which adds HTTPS and a password. It is at
https://paper2experiment.allenhu.com (an A record in Cloudflare, "DNS only"), with
`51-79-156-230.sslip.io` as a fallback address.

```
browser ──HTTPS + password──▶ Caddy :443 ──▶ p2e demo serve 127.0.0.1:8780 (user p2e, holds the API keys)
                                                   │ sudo -u p2e-run
                                                   ▼
                                     agent commands (user p2e-run, /srv/p2e only, no keys)
```

| File | What it does |
|---|---|
| `deploy.sh` | Run on your machine. Builds the frontend, uploads the files, runs the server setup, copies `Base/.env` and the run records |
| `server-setup.sh` | Runs on the server as root. Firewall (22/80/443 only), fail2ban, automatic security updates, users `p2e` and `p2e-run`, `/srv/p2e`, uv + Python 3.11 + micromamba, project checkout, systemd service, Caddy |
| `p2e-demo.service` | systemd unit that keeps the demo running, restarts it after a crash or reboot, and holds the server settings (command user, monthly cap) |
| `Caddyfile.template` | HTTPS site with basic auth in front of the demo |

## Protecting the API keys

| Risk | What stops it |
|---|---|
| Someone uses the site to spend credit | A password on the whole site, and a **$5 monthly cap** on every LLM call of the demo and its runs together (`P2E_MONTHLY_BUDGET_USD`, ledger in `Base/runs/.spend/`). Drafting and starting are refused once it is used up; a run stops before a request that would cross it. The page shows this month's spend. |
| The code being reproduced reads the keys | Every agent command runs as `p2e-run`, which can read neither `/home/p2e` (the project and its `.env`) nor the server's process. It only has `/srv/p2e`. |
| A run's file is served to the browser | The file endpoint refuses anything that resolves outside the run's workspace (a symlink to `.env`, say). |
| The key is used somewhere else | Outside what this server can control: set a spend limit on the key at the provider as well (Anthropic Console → workspace spend limit; OpenAI → project budget), and use keys made only for this server. |

## Usage

```bash
bash deploy/deploy.sh              # first deploy, or after changing the server setup
bash deploy/deploy.sh --app-only   # after pushing code changes: pull, rebuild frontend, restart
```

The server clones the project from GitHub, so push before deploying. The site login is generated on the first deploy
and stored in `deploy/demo-login.local.txt`, which git ignores.

## On the server

```bash
ssh ovh-vps
sudo systemctl status p2e-demo                        # is the demo running
sudo journalctl -u p2e-demo -f                        # demo logs
sudo journalctl -u caddy -f                           # HTTPS / certificate logs
sudo cat /home/p2e/Paper2Exp/Base/runs/.spend/*.json  # this month's LLM spend
```
