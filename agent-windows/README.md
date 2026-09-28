# Pebble Windows agent

Records which app is in the foreground (with window title, browser URL and
document name), queues the records locally and sends them to the Pebble
server whenever it can reach it. A tray icon shows today's screen time.
Nothing is blocked: the agent only records.

## Installing on a kid's PC

1. On the management page (from your own device), add the device (platform Windows)
   and note the 6-digit pairing code. It works once, for 15 minutes; an existing
   device gets a new one with "Pairing code" on its page.
2. On the PC, download `pebble-agent.exe` from `http://<server>/downloads`.
3. In an **administrator** PowerShell in the download folder:

   ```powershell
   .\pebble-agent.exe install --server http://192.168.3.10 --code 482913 --users emma
   ```

   `--token <TOKEN>` works instead of `--code` (the token is also shown once).

   `--users` limits tracking to those Windows accounts (comma-separated). Leave
   it out to track everyone who logs on, including parents.
4. Give the kids **standard** Windows accounts. An administrator can remove the agent.

The installer:
- swaps the pairing code for a device token, and checks the token with the server
- copies the exe to `C:\Program Files\Pebble`
- writes `C:\ProgramData\Pebble\config.json` (users can read but not change it)
- registers the scheduled task **Pebble Agent**, which starts the agent at every
  logon, restarts it if it crashes, and relaunches it every 5 minutes if it was
  killed

Other commands: `pebble-agent.exe status` (today's time and connection check),
`pebble-agent.exe uninstall [--keep-data]` (as administrator).

Log file: `%LOCALAPPDATA%\Pebble\agent.log` (one per Windows account).

## What it records and how

| What | How |
|---|---|
| Foreground app | Every 5 s: `GetForegroundWindow`, process exe, and the exe's description ("Microsoft Word"). Store apps are resolved through `ApplicationFrameHost`. |
| Window title | As shown. Browser name suffixes are removed. |
| Browser URL | Address bar via UI Automation (Chrome, Edge, Firefox, Brave, Opera, Vivaldi). Best effort. |
| Document | Parsed from the title: `Essay.docx - Word` → `Essay.docx`. |
| Idle | No keyboard or mouse input for 2 min ends the session. Fullscreen windows and video sites/apps allow 30 min. |
| Not usage | Lock screen, sign-in screen, another user's session being on screen. |

Sessions are split every 5 minutes so the dashboard stays close to live.

## Tamper signals

The server turns these into alerts (see `docs/api.md`):

- **Agent not running while the PC was on:** on start, the agent compares when it
  was last alive with the logon time and subtracts any sleep time from the event log.
- **Killed:** a restart in the same logon session without a clean stop.
- **Clock changed:** the wall clock and monotonic clock disagree.
- **Queue edited or deleted:** sequence numbers and the hash chain break.
- **Boot, shutdown, sleep, resume and unexpected shutdowns:** from the System event log.

## Development

The logic (tracker, store, sync, lifecycle, titles, event-log parsing) is
platform-neutral and tested on any OS. Only `winapi.py`, `browser.py`, `tray.py`
and `install.py` need Windows.

```bash
# Linux/macOS, reusing the server's venv (the end-to-end test starts the real server)
../server/venv/bin/python -m pytest
```

On Windows, `build.ps1` creates a venv, runs the tests and builds
`dist\pebble-agent.exe` with PyInstaller. Publish it to the server's downloads page from
a machine with SSH access:

```bash
server/deploy/publish-download.sh agent-windows/dist/pebble-agent.exe
```

For debugging without installing: `set PEBBLE_AGENT_HOME=%TEMP%\pebble-dev`, write a
`config.json` there, then `python -m pebble_agent run --no-tray`.
