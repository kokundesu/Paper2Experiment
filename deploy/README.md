# Deploying the demo to a VPS

The demo (`p2e demo serve`) runs on an Ubuntu 24.04 VPS behind Caddy, which adds HTTPS and a password.

```
browser ──HTTPS + password──▶ Caddy :443 ──▶ p2e demo serve 127.0.0.1:8780 (user p2e) ──▶ agent runs
```

| File | What it does |
|---|---|
| `deploy.sh` | Run on your machine. Builds the frontend, uploads the files, runs the server setup, copies `Base/.env` and the run records |
| `server-setup.sh` | Runs on the server as root. Firewall (22/80/443 only), fail2ban, automatic security updates, user `p2e`, uv + Python 3.11 + micromamba, project checkout, systemd service, Caddy |
| `p2e-demo.service` | systemd unit that keeps the demo running and restarts it after a crash or reboot |
| `Caddyfile.template` | HTTPS site with basic auth in front of the demo |

## Why it is set up this way

- **Password on the whole site.** The demo has no accounts, and every run spends API credit.
- **A separate user, `p2e`.** The agents run code from arbitrary repositories. The sandbox only isolates by convention, so
  the runs must not have root or the login user's SSH access.
- **Domain `<ip>.sslip.io`.** Let's Encrypt only issues certificates for host names, and sslip.io resolves
  `51-79-156-230.sslip.io` to `51.79.156.230`. Set `DOMAIN=` to use your own domain instead.

## Usage

```bash
bash deploy/deploy.sh              # first deploy, or to redo everything
bash deploy/deploy.sh --app-only   # after pushing code changes: pull, rebuild frontend, restart
```

The server clones the project from GitHub, so push before deploying. The site login is generated on the first deploy
and stored in `deploy/demo-login.local.txt`, which git ignores.

## On the server

```bash
ssh ovh-vps
sudo systemctl status p2e-demo          # is the demo running
sudo journalctl -u p2e-demo -f          # demo logs
sudo journalctl -u caddy -f             # HTTPS / certificate logs
```
