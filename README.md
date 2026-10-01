# Pebble

Pebble tracks kids' screen time across Windows PCs and Android devices and reports it to a
Flask server on the home network. It records and shows usage; it does not block anything.

## Components

| Folder | What it is | Docs |
|---|---|---|
| `server/` | Flask app: dashboard, management page, agent API | [server/README.md](server/README.md) |
| `agent-windows/` | Python agent packaged as an `.exe` with a tray icon | [agent-windows/README.md](agent-windows/README.md) |
| `agent-android/` | Kotlin Android app | [agent-android/README.md](agent-android/README.md) |
| `docs/` | Agent ↔ server contract | [docs/api.md](docs/api.md) |

Design decisions and the overall plan are in [PLAN.md](PLAN.md).

## Quick start (server)

```bash
cd server
python3 -m venv venv
venv/bin/pip install -r requirements.txt pytest
cp .env.example .env
venv/bin/flask db upgrade
venv/bin/flask run --debug
```

## Android release signing

The release keystore (`pebble-release.jks`) and `keystore.properties` live outside this
repository in `~/android-dev/`. Keep a backup: without that keystore, updates to the
installed app cannot be signed.
