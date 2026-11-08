# Deploying the demo to a VPS

The demo (`p2e demo serve`) runs on an Ubuntu 24.04 VPS behind Caddy, which adds HTTPS. Visitors come in through the
demo's own entrance: a name (shown to the others as who is online) and a 4-digit access code. It is at
https://paper2experiment.allenhu.com (an A record in Cloudflare, "DNS only"), with
`51-79-156-230.sslip.io` as a fallback address.

```
browser ──HTTPS──▶ Caddy :443 ──▶ p2e demo serve 127.0.0.1:8780 (user p2e: entrance, queue, API keys)
                                                   │ sudo -u p2e-run
                                                   ▼
                                     agent commands (user p2e-run, /srv/p2e only, no keys)
```

| File | What it does |
|---|---|
| `deploy.sh` | Run on your machine. Builds the frontend, uploads the files, runs the server setup, copies `Base/.env` and the run records |
| `server-setup.sh` | Runs on the server as root. Firewall (22/80/443 only), fail2ban, automatic security updates, users `p2e` and `p2e-run`, `/srv/p2e`, uv + Python 3.11 + micromamba, project checkout, systemd service, Caddy |
| `p2e-demo.service` | systemd unit that keeps the demo running, restarts it after a crash or reboot, and holds the server settings (command user, monthly cap, 2 runs at once) |
| `Caddyfile.template` | HTTPS in front of the demo |
| `demo-access.local.env` | Git-ignored, yours only: `P2E_DEMO_CODE` and `P2E_DEMO_CODE_EXPIRES`. deploy.sh copies it to `/etc/p2e-demo.env` |

## The entrance, who is online, and the queue

- **Access code.** The page opens on a card over a frosted copy of the home page: a name and the 4-digit code. The
  server checks the code and sets a signed session cookie that lasts until the code expires, so a returning visitor goes
  straight in under the same name ("Sign out" in the online menu to change it). Every API call without the cookie is
  refused. Wrong codes: 5 per address per 15 minutes, 60 an hour in total. Changing the code ends all sessions.
- **Online.** Each open page reports every 15 s; the top bar shows how many people are online (the menu lists their
  names), how many runs are going out of the 2 slots, and how many wait.
- **Queue.** At most `P2E_DEMO_MAX_RUNS` (2) runs at once. More wait in line, first come first served, and start by
  themselves; the run window shows the place in line, and Stop takes a run out of it.

## Protecting the API keys

| Risk | What stops it |
|---|---|
| Someone uses the site to spend credit | The access code (expiring, rate-limited), and a **$5 monthly cap** on every LLM call of the demo and its runs together (`P2E_MONTHLY_BUDGET_USD`, ledger in `Base/runs/.spend/`). Drafting and starting are refused once it is used up; a run stops before a request that would cross it. The page shows this month's spend. |
| The code being reproduced reads the keys | Every agent command runs as `p2e-run`, which can read neither `/home/p2e` (the project and its `.env`) nor the server's process. It only has `/srv/p2e`. |
| A run's file is served to the browser | The file endpoint refuses anything that resolves outside the run's workspace (a symlink to `.env`, say). |
| The key is used somewhere else | Outside what this server can control: set a spend limit on the key at the provider as well (Anthropic Console → workspace spend limit; OpenAI → project budget), and use keys made only for this server. |

## Usage

```bash
bash deploy/deploy.sh              # first deploy, or after changing the server setup
bash deploy/deploy.sh --app-only   # after pushing code changes: pull, rebuild frontend, restart
```

The server clones the project from GitHub, so push before deploying. To change the access code or how long it works,
or the cap of a single month (`P2E_MONTHLY_BUDGET_OVERRIDES=2026-11=20`), edit `deploy/demo-access.local.env` and run
`bash deploy/deploy.sh --app-only`.

A deploy restarts the demo, and a restart stops every run it started. deploy.sh refuses while an experiment is running;
`FORCE=1 bash deploy/deploy.sh ...` overrides that.

## On the server

```bash
ssh ovh-vps
sudo systemctl status p2e-demo                        # is the demo running
sudo journalctl -u p2e-demo -f                        # demo logs
sudo journalctl -u caddy -f                           # HTTPS / certificate logs
sudo cat /home/p2e/Paper2Exp/Base/runs/.spend/*.json  # this month's LLM spend
```
