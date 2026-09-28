# Pebble Agent API — v1

Base URL: `http://<server>:<port>/api/v1`
All bodies are JSON. All timestamps are ISO-8601 **with UTC offset**
(`2026-09-28T15:04:05+02:00`).

## Authentication

Each device is created on the management page, which shows its token once.
The agent stores the token and sends it on every request:

```
Authorization: Bearer <device-token>
X-Pebble-Install-Id: <uuid generated once per agent install>
```

An unknown or revoked token gets `401`. If the install ID differs from the
one previously seen for this token (agent reinstalled, or the token was copied),
the request is accepted normally, but the server raises an alert and expects
`seq` to restart at 1.

## POST /sync

The agent calls this endpoint to upload data and to heartbeat. Call it every
sync interval, even when there are no records to send.

Request:
```json
{
  "agent_version": "0.1.0",
  "device_time": "2026-09-28T15:04:05+02:00",
  "monotonic_s": 183422.5,
  "records": [
    {
      "seq": 1042,
      "id": "7c1e…uuid",
      "prev_hash": "<hash of the previous record, null for the first>",
      "hash": "<see Hashing below>",
      "kind": "session",
      "start": "2026-09-28T14:50:00+02:00",
      "end":   "2026-09-28T14:58:30+02:00",
      "app_id": "chrome.exe",
      "app_name": "Google Chrome",
      "title": "Minecraft speedrun - YouTube - Google Chrome",
      "url": "https://www.youtube.com/watch?v=…",
      "document": null
    },
    {
      "seq": 1043,
      "id": "…",
      "prev_hash": "…",
      "hash": "…",
      "kind": "event",
      "at": "2026-09-28T14:58:31+02:00",
      "type": "clock_jump",
      "details": { "delta_s": -3600 }
    }
  ]
}
```

- `seq` starts at 1 and increases by one per record, per install, without gaps.
  Send records in `seq` order, at most 1000 per request (body limit 5 MB).
  A device that has been offline a long time sends several requests in a row.
- `app_id` is the exe name on Windows and the package name on Android (`com.google.android.youtube`).
- `url`, `document` and `title` may be `null`.
- Event `type` values: `agent_start`, `agent_stop`, `os_boot`, `os_shutdown`,
  `os_sleep`, `os_resume`, `clock_jump`, `permission_lost`, `permission_restored`,
  `backfill` (Android: records recovered from OS history), `agent_gap`.
- `agent_start` details may include `"new_session": true` when the user logged
  off/on or the OS restarted since the agent last ran. The server then doesn't
  expect a preceding `agent_stop` (Windows ends the agent at logoff without warning).
- `agent_gap` details: `{"from": ts, "to": ts, "slept_s": n}`. The agent wasn't
  running between `from` and `to` although the device was on (minus `slept_s`
  asleep). The server raises an `agent_not_running` alert.

Response `200`:
```json
{
  "accepted_through_seq": 1043,
  "rejected": [],
  "server_time": "2026-09-28T15:04:06+02:00",
  "sync_interval_s": 120,
  "today": {
    "date": "2026-09-28",
    "used_s": 8040,
    "limit_s": 10800,
    "status": "under"
  },
  "exclusions": [
    { "app_id": "winword.exe" },
    { "domain": "classroom.google.com" },
    { "title_pattern": "*.docx - word" }
  ]
}
```

- Records are idempotent by `id`. The agent deletes its local records up to
  `accepted_through_seq`.
- The server flags a sequence gap or a broken hash chain. It still stores the records.
- `rejected` lists records the server could not use (`[{"id", "seq", "error"}]`,
  e.g. `end` before `start`). They still count as received: the agent drops them
  with the rest, so one bad record can never block the queue.
- The agent keeps `exclusions` so it can compute a local estimate while offline.
- `status` is one of `under`, `near` (≥ 90%) or `over`.

### Exclusion matching (for the agent's local estimate)

All fields present in a rule must match:
- `app_id`: case-insensitive equality.
- `domain`: the session's domain equals it or is a subdomain of it.
- `title_pattern`: case-insensitive glob (`*`, `?`) over the whole window title.

The local estimate may differ from the server (e.g. overlap between devices
or parent adjustments). The server figure is authoritative.

## Hashing

`hash` = lowercase hex SHA-256 of the record serialised as canonical JSON
**without the `hash` key**: keys sorted, no whitespace (`","` and `":"`
separators), UTF-8, non-ASCII characters not escaped. In Python:

```python
body = {k: v for k, v in record.items() if k != 'hash'}
json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
```

Because `prev_hash` is part of the record, each hash covers the whole chain.
Agents persist `seq` and the last hash so the chain survives restarts.
`server/tools/fake_agent.py` is a working reference.

## GET /status

A lightweight call for the tray or widget refresh. It returns the `today`
object above for the device's kid, with the same auth as `/sync`.
