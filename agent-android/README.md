# Pebble Android agent

Reads which apps were in the foreground from Android's usage history, queues the
sessions locally and sends them to the Pebble server. A home-screen widget and the
app screen show today's time. Nothing is blocked: the agent only records.

## Installing on a kid's phone or tablet

1. On the management page (from your own device), add the device (platform Android)
   and note the 6-digit pairing code. It works once, for 15 minutes.
2. On the device, open `http://<server>/downloads` in Chrome and download
   `pebble-agent.apk`. Allow Chrome to install unknown apps when asked.
   **Family Link:** a supervised account can't do this until a parent allows it
   in Family Link (see below).
3. Open Pebble, enter the server (`192.168.3.10`) and the pairing code.
4. Work through the checklist in the app:
   - **Usage access**: Pebble can't see anything without it.
   - **Run in the background**: exempts Pebble from battery optimisation, so
     Android keeps running it every 15 minutes. On Samsung, also check
     Settings → Battery → Background usage limits and make sure Pebble isn't in
     "Sleeping apps" or "Deep sleeping apps".
   - **Autostart** (Xiaomi, Oppo, Vivo, Huawei only): allow it in the page that opens.
5. Optional: add the Pebble widget to the home screen.

### Family Link

Supervised accounts can block installing apps from outside the Play Store and
some special-access settings. If the install or Usage access is blocked, allow it
for that device from the parent's Family Link app, then continue. (Not yet tried
on a real Family Link device; update this with the exact steps once done.)

## How it works

| What | How |
|---|---|
| Foreground app | `UsageStatsManager.queryEvents`: `ACTIVITY_RESUMED` / `PAUSED` / `STOPPED`, per package. App names from the package manager. |
| Not usage | Screen off (`SCREEN_NON_INTERACTIVE`), lock screen (`KEYGUARD_SHOWN`), shutdown. |
| Schedule | WorkManager every 15 minutes, and whenever the app screen opens. Each run reads events since the last run, so nothing is lost if a run is late: Android keeps several days of history (**backfill**). |
| Queue | SQLite with sequence numbers and the hash chain from `docs/api.md`. |
| Today | The server's figure plus queued sessions, minus exclusion rules (package rules only; Android has no titles or URLs yet). |

URLs and window titles are not captured yet. That needs an optional accessibility
service in a later phase.

## Tamper signals

- **Usage access turned off/on:** `permission_lost` / `permission_restored`. The
  history is picked up once access is back.
- **Agent not running while the device was used:** a run more than an hour after the
  previous one, with at least 10 minutes of use in between, sends `agent_gap`
  (plus `backfill` for the recovered sessions). This catches force-stopping Pebble.
- **Clock changed:** wall clock vs `elapsedRealtime` between runs.
- **Reboot:** `agent_start` with `new_session`, plus `os_boot` / `os_shutdown` from
  usage events.
- **Uninstalled or force-stopped and never opened again:** the device goes silent;
  the dashboard shows the last sync.

## Building

A JDK and the Android command-line SDK live in your home folder (no Android Studio):

```
~/android-dev/jdk                   Temurin JDK 21
~/Android/Sdk                       platforms;android-35, build-tools;35.0.0, platform-tools
~/android-dev/pebble-release.jks    release signing key
~/android-dev/keystore.properties   storeFile, storePassword, keyAlias, keyPassword
```

**Back up the signing key and its properties file.** Android only installs an update
signed with the same key; with a new key, every device must uninstall and pair again.

```bash
./build.sh                                                  # tests, lint, dist/pebble-agent.apk
../server/deploy/publish-download.sh dist/pebble-agent.apk  # put it on /downloads
```

`./gradlew testDebugUnitTest` runs the unit tests (sessions, hashing, tamper checks,
today's estimate) on any machine. `adb install -r dist/pebble-agent.apk` installs
over USB when developer options are available.
