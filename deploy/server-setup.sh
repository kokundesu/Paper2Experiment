#!/usr/bin/env bash
# One-time (and re-runnable) setup of the demo on an Ubuntu 24.04 VPS. Run as root on the server:
#
#   sudo DOMAIN=<host name> AUTH_PASSWORD='<site password>' bash server-setup.sh   (deploy.sh does this)
#
# It hardens the machine (firewall, fail2ban, automatic security updates), creates the unprivileged user `p2e` that
# runs the demo (agents execute the code of arbitrary repositories, so they must not run as root or as the login
# user), installs uv, Python 3.11 and micromamba for that user, clones or updates the project, and puts the demo
# behind Caddy (HTTPS + password). The frontend is built on the deploying machine and copied by deploy.sh, so the
# server needs no Node.js.
set -euo pipefail

DOMAIN=${DOMAIN:?set DOMAIN, e.g. 51-79-156-230.sslip.io}
AUTH_USER=${AUTH_USER:-demo}
AUTH_PASSWORD=${AUTH_PASSWORD:?set AUTH_PASSWORD, the password of the site}
REPO_URL=${REPO_URL:-https://github.com/kokundesu/Paper2Experiment.git}
BRANCH=${BRANCH:-main}
APP_USER=p2e
APP_HOME=/home/$APP_USER
APP_DIR=$APP_HOME/Paper2Exp
HERE=$(cd "$(dirname "$0")" && pwd)

export DEBIAN_FRONTEND=noninteractive

echo "== packages"
apt-get update -q
apt-get install -y -q git curl ca-certificates build-essential gfortran pkg-config bzip2 rsync \
  ufw fail2ban unattended-upgrades debian-keyring debian-archive-keyring apt-transport-https gnupg

echo "== firewall: only SSH, HTTP and HTTPS"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable

echo "== fail2ban (sshd jail) and automatic security updates"
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 30m
EOF
systemctl enable --now fail2ban >/dev/null
systemctl restart fail2ban
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "== caddy"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy
fi

echo "== app user $APP_USER"
id "$APP_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$APP_USER"

as_app() { sudo -u "$APP_USER" -H bash -lc "$1"; }

echo "== uv, micromamba"
as_app 'command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh'
as_app 'test -x ~/.p2e-mamba/bin/micromamba || (mkdir -p ~/.p2e-mamba && curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C ~/.p2e-mamba bin/micromamba)'

echo "== project ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  as_app "cd $APP_DIR && git fetch -q origin && git checkout -q $BRANCH && git reset -q --hard origin/$BRANCH"
else
  as_app "git clone -q -b $BRANCH $REPO_URL $APP_DIR"
fi
as_app "cd $APP_DIR && ~/.local/bin/uv venv -q --allow-existing --python 3.11.16 .venv \
  && (cd Base && ~/.local/bin/uv export -q --frozen --extra dev --no-hashes --no-emit-project) \
     | ~/.local/bin/uv pip sync -q --python .venv/bin/python - \
  && ~/.local/bin/uv pip install -q --python .venv/bin/python -e Base[dev] --no-deps"
test -f "$APP_DIR/Base/.env" && chmod 600 "$APP_DIR/Base/.env" && chown "$APP_USER:$APP_USER" "$APP_DIR/Base/.env"

echo "== systemd service"
install -m 644 "$HERE/p2e-demo.service" /etc/systemd/system/p2e-demo.service
systemctl daemon-reload
systemctl enable p2e-demo >/dev/null
systemctl restart p2e-demo

echo "== caddy site $DOMAIN"
AUTH_HASH=$(caddy hash-password --plaintext "$AUTH_PASSWORD")
sed -e "s|{{DOMAIN}}|$DOMAIN|" -e "s|{{AUTH_USER}}|$AUTH_USER|" -e "s|{{AUTH_HASH}}|$AUTH_HASH|" \
  "$HERE/Caddyfile.template" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl reload caddy || systemctl restart caddy

echo "== done: https://$DOMAIN (user $AUTH_USER)"
