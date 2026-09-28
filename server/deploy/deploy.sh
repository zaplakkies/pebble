#!/usr/bin/env bash
# Deploy the committed server code (HEAD) to the home server.
# First run also creates the pebble user, venv, .env and systemd service.
#
#   server/deploy/deploy.sh [user@host]
set -euo pipefail

HOST=${1:-george@192.168.3.10}
APP=/opt/pebble
SUBNET=192.168.3.0/24

cd "$(git rev-parse --show-toplevel)"
if ! git diff --quiet HEAD -- server; then
    echo "Note: uncommitted changes in server/ are NOT deployed (deploying HEAD)." >&2
fi
REV=$(git rev-parse --short HEAD)
# Generated locally; only used if the server has no .env yet.
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
MANAGE_PATH=manage-$(python3 -c 'import secrets; print(secrets.token_hex(6))')

echo "Uploading $REV to $HOST..."
git archive --format=tar HEAD server | ssh "$HOST" "cat > /tmp/pebble-$REV.tar"

ssh "$HOST" "sudo bash -s" <<EOF
set -euo pipefail
if ! python3 -c 'import ensurepip' 2>/dev/null || ! command -v curl >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv curl >/dev/null
fi
id pebble >/dev/null 2>&1 || useradd --system --create-home --home-dir $APP --shell /usr/sbin/nologin pebble
mkdir -p $APP/server/instance

# Replace code, keep venv, database and .env
find $APP/server -mindepth 1 -maxdepth 1 ! -name venv ! -name instance ! -name .env -exec rm -rf {} +
tar -xf /tmp/pebble-$REV.tar -C $APP/server --strip-components=1
rm -f /tmp/pebble-$REV.tar
echo $REV > $APP/server/REVISION

if [ ! -f $APP/server/.env ]; then
    umask 077
    printf 'SECRET_KEY=%s\nMANAGE_PATH=%s\nTIMEZONE=\nSYNC_INTERVAL_S=120\n' '$SECRET_KEY' '$MANAGE_PATH' > $APP/server/.env
    echo "Created .env with management path /$MANAGE_PATH/"
fi
chown -R pebble:pebble $APP

cd $APP/server
if [ ! -x venv/bin/pip ]; then
    rm -rf venv
    sudo -u pebble python3 -m venv venv
fi
sudo -u pebble venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
sudo -u pebble venv/bin/flask db upgrade

install -m 644 deploy/pebble.service /etc/systemd/system/pebble.service
systemctl daemon-reload
systemctl enable -q pebble
systemctl restart pebble
if ufw status | grep -q "Status: active"; then
    ufw allow from $SUBNET to any port 8000 proto tcp >/dev/null
fi

for i in \$(seq 10); do
    curl -fs -o /dev/null http://127.0.0.1:8000/ && break
    sleep 1
done
echo "pebble service: \$(systemctl is-active pebble), revision \$(cat REVISION)"
curl -fsS -o /dev/null -w "dashboard HTTP %{http_code}\n" http://127.0.0.1:8000/
EOF
echo "Done: http://${HOST#*@}:8000/"
