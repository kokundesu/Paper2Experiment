#!/usr/bin/env bash
# Deploy (or redeploy) the demo from this machine to the VPS. Run from the repository root:
#
#   bash deploy/deploy.sh                  # full: server setup + frontend + API keys + run records
#   bash deploy/deploy.sh --app-only       # after a code change: pull, rebuild frontend, restart
#
# Settings (environment variables): SSH_HOST (an ~/.ssh/config host, default ovh-vps), DOMAIN (default:
# paper2experiment.allenhu.com, an A record in Cloudflare set to "DNS only" so Caddy gets the certificate itself,
# plus the server's IPv4 as <a-b-c-d>.sslip.io as a fallback address).
# The access code of the site's entrance is in deploy/demo-access.local.env (git-ignored: the repository is public),
# copied to /etc/p2e-demo.env on the server. Change it or its expiry there and redeploy (--app-only is enough).
# The server clones the project from GitHub, so push your commits before deploying.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
# Restarting the demo stops every run it started (systemd stops the whole service): refuse while any is going,
# unless FORCE=1. Runs still waiting in the queue are lost on a restart too; their count is in the online pill.
SSH_HOST=${SSH_HOST:-ovh-vps}
APP=/home/p2e/Paper2Exp
ACCESS="$ROOT/deploy/demo-access.local.env"
APP_ONLY=false
[ "${1:-}" = "--app-only" ] && APP_ONLY=true

if [ -z "${DOMAIN:-}" ]; then
  IP=$(ssh -G "$SSH_HOST" | awk '/^hostname /{print $2}')
  DOMAIN="paper2experiment.allenhu.com, ${IP//./-}.sslip.io"
fi

RUNNING=$(ssh "$SSH_HOST" 'pgrep -fc "p2e[.]cli demo run" || true')
if [ "${RUNNING:-0}" -gt 0 ] && [ "${FORCE:-0}" != 1 ]; then
  echo "!! $RUNNING experiment(s) running on the server; deploying would stop them. Wait, or run with FORCE=1." >&2
  exit 1
fi

echo "== build frontend"
(cd "$ROOT/Base/demo-web" && npm install --silent && npm run build --silent)

echo "== upload deploy files"
ssh "$SSH_HOST" 'mkdir -p ~/p2e-deploy'
rsync -a --delete --exclude '*.local*' "$ROOT/deploy/" "$SSH_HOST:p2e-deploy/"

if ! $APP_ONLY; then
  echo "== server setup (sudo)"
  ssh "$SSH_HOST" "sudo DOMAIN='$DOMAIN' bash ~/p2e-deploy/server-setup.sh"
else
  echo "== update project"
  ssh "$SSH_HOST" "sudo -u p2e -H bash -lc 'cd $APP && git fetch -q origin && git reset -q --hard origin/main \
    && (cd Base && ~/.local/bin/uv export -q --frozen --extra dev --no-hashes --no-emit-project) \
       | ~/.local/bin/uv pip sync -q --python .venv/bin/python - \
    && ~/.local/bin/uv pip install -q --python .venv/bin/python -e Base[dev] --no-deps'"
fi

echo "== access code"
if [ -f "$ACCESS" ]; then
  rsync -a "$ACCESS" "$SSH_HOST:p2e-deploy/access.env"
  ssh "$SSH_HOST" 'sudo install -m 600 -o root -g root ~/p2e-deploy/access.env /etc/p2e-demo.env && rm ~/p2e-deploy/access.env'
else
  echo "   (no deploy/demo-access.local.env: the site will be open without a code)"
fi

echo "== copy frontend, API keys and run records"
STAGE=p2e-deploy/stage
REMOTE_HOME=$(ssh "$SSH_HOST" 'echo $HOME')
ssh "$SSH_HOST" "rm -rf ~/$STAGE && mkdir -p ~/$STAGE"
rsync -a "$ROOT/Base/demo-web/dist/" "$SSH_HOST:$STAGE/dist/"
if ! $APP_ONLY; then
  rsync -a "$ROOT/Base/.env" "$SSH_HOST:$STAGE/.env"
  # Past runs are where the page's examples come from. The uv cache and this machine's run-folder setting stay here.
  rsync -a --exclude '.uv-cache' --exclude 'demo_drafts/settings.json' "$ROOT/Base/runs/" "$SSH_HOST:$STAGE/runs/"
fi
ssh "$SSH_HOST" "sudo bash -c '
  set -e
  rsync -a --delete $REMOTE_HOME/$STAGE/dist/ $APP/Base/demo-web/dist/
  if [ -f $REMOTE_HOME/$STAGE/.env ]; then install -m 600 $REMOTE_HOME/$STAGE/.env $APP/Base/.env; fi
  if [ -d $REMOTE_HOME/$STAGE/runs ]; then rsync -a $REMOTE_HOME/$STAGE/runs/ $APP/Base/runs/; fi
  chown -R p2e:p2e $APP/Base/demo-web/dist $APP/Base/runs $APP/Base/.env 2>/dev/null || true
  rm -rf $REMOTE_HOME/$STAGE
  systemctl restart p2e-demo
'"

echo "== check"
sleep 3
ssh "$SSH_HOST" 'systemctl is-active p2e-demo && curl -s -o /dev/null -w "local demo: HTTP %{http_code}\n" http://127.0.0.1:8780/'
echo "Site: https://${DOMAIN%%,*}  (access code in deploy/demo-access.local.env)"
