# Pebble server

Flask app that receives usage from the agents, shows each kid's screen time,
and flags signs of tampering. See `../PLAN.md` for the overall design and
`../docs/api.md` for the agent API.

## Development

```bash
cd server
python3 -m venv venv
venv/bin/pip install -r requirements.txt pytest
cp .env.example .env            # then edit it

venv/bin/flask db upgrade       # create/upgrade the database
venv/bin/flask kid add Emma --weekday 120 --weekend 180
venv/bin/flask device add Emma "Emma laptop" --platform windows   # prints the device token
venv/bin/flask run --debug      # http://127.0.0.1:5000

# Send made-up usage (in another terminal)
venv/bin/python tools/fake_agent.py --token <TOKEN> --minutes 90
venv/bin/python tools/fake_agent.py --token <TOKEN> --tamper gap   # also: modify, clock, reinstall
venv/bin/flask alerts

venv/bin/python -m pytest
```

After changing `pebble/models.py`: `venv/bin/flask db migrate -m "what changed"`, check the
generated file in `migrations/versions/`, then `venv/bin/flask db upgrade`.

## Management commands

These stand in for the hidden management page until phase 3.

| Command | |
|---|---|
| `flask kid add NAME [--weekday MIN] [--weekend MIN]` | Add a kid (no option = no limit) |
| `flask kid list` | |
| `flask device add KID "DEVICE NAME" --platform windows\|android` | Prints the device token once |
| `flask device list` | Last seen, sequence number |
| `flask device revoke ID` | Token stops working |
| `flask alerts [--all]` | Tamper alerts |

## Deploying on the Ubuntu server

From this repo, deploy the committed code with:

```bash
server/deploy/deploy.sh                 # defaults to george@192.168.3.10
```

The script uploads `HEAD`, keeps the server's `venv`, database and `.env`, runs
migrations, and restarts the service. The first run also creates the `pebble`
user, a `.env` with a random `SECRET_KEY` and `MANAGE_PATH`, the systemd
service and the firewall rule. The manual steps below show what it does.


```bash
sudo apt install python3-venv
sudo useradd --system --create-home --home-dir /opt/pebble pebble
# copy the server/ folder to /opt/pebble/server (scp, rsync or git clone), then:
cd /opt/pebble/server
sudo chown -R pebble:pebble /opt/pebble
sudo -u pebble python3 -m venv venv
sudo -u pebble venv/bin/pip install -r requirements.txt
sudo -u pebble cp .env.example .env && sudo -u pebble nano .env   # SECRET_KEY, MANAGE_PATH
sudo -u pebble venv/bin/flask db upgrade

sudo cp deploy/pebble.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pebble
sudo ufw allow from 192.168.0.0/16 to any port 80 proto tcp     # LAN only; match your subnet
```

The dashboard is then at `http://<server-ip>/`. Run management commands as:
`cd /opt/pebble/server && sudo -u pebble venv/bin/flask kid list`.

Make sure the server's timezone is right (`timedatectl`), or set `TIMEZONE` in `.env`.
Logs: `journalctl -u pebble -f`.

**Back up** `/opt/pebble/server/instance/pebble.db`, for example with a nightly
`sqlite3 pebble.db ".backup /somewhere/pebble-$(date +%F).db"` cron job.
