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

## Installing on an Android TV box

The same APK runs on Android TV (it appears on the TV home screen). A TV is shared, so
on the management page add it under a kid called **Family** (create that kid once), so
its time doesn't land on one child.

TV boxes usually have no Chrome and often no Usage access page, so install with adb
from a computer on the same network:

1. On the box: Settings → Device Preferences → About, press **Build** 7 times. Then in
   Developer options turn on **USB debugging** / **Network debugging**. Some operator
   boxes hide these; then use a USB stick and a file manager app to install, and you'll
   still need adb for step 3.
2. `adb connect <box-ip>:5555` (accept the prompt on the TV), then
   `adb install -r dist/pebble-agent.apk`.
3. `adb shell appops set home.pebble.agent GET_USAGE_STATS allow` (Usage access).
4. Open Pebble on the TV, enter the server and the pairing code with the remote.
5. Turn debugging off again, so nobody else can use it.

There's no battery step on a TV: it is always plugged in, so Android doesn't hold back
background work.

What counts on a TV:

- Time stops when the box goes to sleep, and should stop when the screensaver starts
  (Android pauses the app; not yet confirmed on a real box). Set
  Settings → Device Preferences → Screen saver → **Put device to sleep** to a short time,
  so a box left on doesn't keep counting.
- If the TV set is switched off but the box isn't, and an app keeps playing, that time
  counts until the box sleeps. Boxes that follow the TV's power over HDMI-CEC avoid this.
- The TV home screen counts like any app. If that inflates the figure, add an exclusion
  rule for the launcher's package.

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
