# Pebble — Project Plan

Pebble tracks kids' screen time across Windows PCs and Android devices and
reports it to a Flask server on the home network. It works on **honesty and
visibility, not enforcement**: agents log what is used, the server shows it,
and anything that looks like tampering is flagged for a parent to see.

## Components

```
pebble/
├── server/          # Flask app — source of truth, dashboard, hidden management page
├── agent-windows/   # Python agent, packaged as .exe, tray icon
├── agent-android/   # Kotlin app (Android Studio project)
├── docs/
│   └── api.md       # shared agent ↔ server contract
└── PLAN.md
```

## Guiding decisions

| Topic | Decision |
|---|---|
| Enforcement | None. Log only; flag suspicious gaps and changes. |
| What counts | All foreground app time, minus idle time, minus exclusion rules. |
| Exclusions | Rules applied **at report time**, never at ingest. Raw data is always kept, so changing a rule recalculates history. |
| Manual adjustments | Parent can exclude individual sessions or add/remove minutes with a reason. All audited. |
| Detail captured | App, window title, browser URL/domain, document name (Word etc. via window title). |
| Hosting | A PC on the home LAN with a fixed IP / DHCP reservation. |
| Offline | Agents buffer locally and sync whenever the server is reachable. No special "home network" detection; they just retry. |
| Time | Server local time for everything shown. Agents send ISO-8601 timestamps with UTC offset; server stores UTC and computes "today" in its local timezone. |
| Auth | No user login. Dashboard is public on the LAN; management lives at a secret path from config. Agents authenticate with a per-device token. |
| Kid self-check | Each agent shows today's total: server figure when online, local estimate when offline. |

## Server (Flask)

**Stack:** Flask, SQLAlchemy, Flask-Migrate, SQLite, Jinja templates, Pico.css. Run with waitress on Windows or gunicorn on Linux.

**Models**
- `Kid`: name, daily limit (weekday / weekend)
- `Device`: kid, name, platform, token hash, last_seen, last_seq, agent_version
- `Session`: device, app_id, app_name, window_title, url, domain, start, end, raw (immutable)
- `DeviceEvent`: device, type, at, details (agent start/stop, boot, shutdown, clock jump, permission lost…)
- `ExclusionRule`: match on app_id / domain / title pattern, optional kid scope, reason, active
- `Adjustment`: kid, date, minutes (+/-) **or** session_id to exclude, reason
- `Alert`: device, kind, detail, created, acknowledged
- `AuditLog`: append-only record of every management change (what, old → new, when, IP, user-agent)

**Public pages**
- Home: each kid's used / remaining today, status (under / near / over limit), last sync per device
- Kid detail: timeline of the day, per-app and per-site breakdown, 7/30-day history

**Hidden management (`/<MANAGE_PATH>/…`)**
- Kids and limits, devices (create one → show its token once)
- Exclusion rules, session exclusions, manual adjustments
- Alerts inbox (tamper flags)
- Audit log viewer (read-only; no edit or delete anywhere)

**API:** see `docs/api.md`.

## Windows agent (Python)

- **Sampling (every ~5 s):** foreground window via `win32gui`, process exe via `psutil`, window title.
- **Idle:** `GetLastInputInfo`. More than 2 min without input closes the session. Screen lock, sleep and shutdown also close it.
- **Browsers (Chrome, Edge, Firefox):** read the address bar URL through UI Automation (`uiautomation`), best effort. The page title always comes from the window title. A browser extension can be added later if the URL scraping proves unreliable.
- **Documents:** Word, Excel and similar put the document name in the window title (`Essay.docx - Word`), so the agent parses that.
- **Sessions:** consecutive samples with the same app + title + URL merge into one session.
- **Local store:** SQLite queue with a sequence number and hash chain per record. Sync every 2 min when the server is reachable.
- **Tray icon (`pystray`):** tooltip and menu show "Today: 2h 14m (limit 3h)", from the server or a local estimate.
- **Deployment:** PyInstaller exe, installed by an admin under Program Files. A Task Scheduler task runs it at logon for every user and restarts it on failure. The kid's account is a standard user.

## Android agent (Kotlin)

- **Data source:** `UsageStatsManager.queryEvents` (needs the "Usage access" permission). Android keeps several days of event history, so if the agent is killed, it **backfills** what it missed once it runs again.
- **Schedule:** `WorkManager` job every 15 min. It reads events since the last checkpoint, builds sessions, queues them in Room and syncs.
- **Screen on/off:** `SCREEN_INTERACTIVE` / `SCREEN_NON_INTERACTIVE` usage events bound the sessions.
- **URLs (optional, later phase):** an `AccessibilityService` that reads the Chrome/Firefox address bar. It needs to be sideloaded and the permission granted manually. Without it, Android shows app names only.
- **Kid self-check:** the app screen, plus a home-screen widget showing today's total.
- **Tamper resistance:** Device Admin to make uninstalling harder, or pair with Google Family Link.

## Tamper detection (honesty system)

Pebble can't prevent tampering, but it can make it visible. The server raises an `Alert` for:

1. **Silent device:** no heartbeat for longer than N minutes while the device was evidently on. On Windows, the agent reports boot and shutdown times from the Event Log (IDs 6005/6006, plus sleep/resume), so a gap *between* boot and shutdown with no agent is suspicious. On Android, backfilled usage covering the silent period proves the device was in use.
2. **Sequence gap:** record sequence numbers skip, meaning local records were deleted.
3. **Broken hash chain:** a local record was edited.
4. **Clock tampering:** the agent compares its monotonic clock with wall-clock time and reports jumps. The server also compares the device clock with its own clock on every sync.
5. **Unclean stop:** `agent_start` arrives with no preceding `agent_stop`, and the OS didn't shut down. The process was killed.
6. **Permission revoked (Android):** Usage Access or Accessibility was turned off.
7. **Management changes:** everything done on the hidden page goes to the audit log. A daily "changes made" summary appears on the alerts page, so a kid who found the page can't quietly raise their limit.
8. **Agent reinstalled / token reused** from a different install ID.

## Build phases

1. ✅ **Contract:** `docs/api.md`.
2. ✅ **Server core:** models, ingestion API with tamper checks (sequence gaps, hash chain, reinstall, clock skew/jumps, unclean stops, permission loss), daily computation with exclusions and adjustments, public dashboard, `tools/fake_agent.py` for test data, and CLI commands for kids, devices and alerts. Still to do: "silent while powered on" detection, which needs the Windows agent's boot/shutdown events.
3. ✅ **Server management:** hidden pages at `/<MANAGE_PATH>/` for kids and limits, devices (tokens, revoke, new token), exclusion rules (with the most-used apps and sites to pick from), per-day adjustments (give back or count extra minutes, don't count a session), alerts inbox, and the append-only audit log. Forms are protected against cross-site requests (CSRF), and the public dashboard shows when settings last changed.
4. 🟡 **Windows agent:** written and unit-tested on Linux, including an end-to-end test against the real server: sampling, sessions, idle and video handling, queue with hash chain, sync, offline estimate, tray icon, browser URLs, document names, event-log power events, agent-gap and clock-jump detection, and an installer that sets up a scheduled task. Still to do: testing and packaging on a real Windows PC.
5. **Android agent:** usage events, backfill, sync, widget, then tamper events, then the optional accessibility URL capture.
6. **Polish:** weekly summaries, rewards / bonus minutes, charts.
