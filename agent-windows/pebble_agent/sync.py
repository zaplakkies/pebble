"""Sending queued records to the server and caching what it says about today."""
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from pebble_agent import __version__, titles
from pebble_agent.tracker import iso

log = logging.getLogger(__name__)
BATCH = 500


class SyncError(Exception):
    pass


class Unauthorized(SyncError):
    pass


def http_json(method, url, token, install_id, payload=None, timeout=15):
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        'Content-Type': 'application/json', 'Authorization': f'Bearer {token}',
        'X-Pebble-Install-Id': install_id, 'User-Agent': f'pebble-agent/{__version__}'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise Unauthorized('server does not recognise this device token')
        raise SyncError(f'server returned HTTP {e.code}')
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SyncError(f'cannot reach server: {getattr(e, "reason", e)}')


class Syncer:
    def __init__(self, config, store, before_sync=None, clock=time.time, mono=time.monotonic,
                 request=http_json):
        self.config, self.store = config, store
        self.before_sync = before_sync
        self.clock, self.mono, self.request = clock, mono, request
        self.wake = threading.Event()
        self.last_error = None

    def sync_once(self):
        """Send up to BATCH records. Returns True if more are waiting."""
        if self.before_sync:
            self.before_sync()
        batch = self.store.pending(BATCH)
        result = self.request('POST', f'{self.config.base_url}/api/v1/sync', self.config.token,
                              self.store.install_id, {
                                  'agent_version': __version__,
                                  'device_time': iso(self.clock()),
                                  'monotonic_s': round(self.mono(), 1),
                                  'records': batch})
        accepted = int(result.get('accepted_through_seq', 0))
        if batch:
            self.store.acknowledge(min(accepted, batch[-1]['seq']))
        for rejected in result.get('rejected') or []:
            log.warning('Server rejected record %s: %s', rejected.get('seq'), rejected.get('error'))
        self.store.set('today', result.get('today'))
        self.store.set('exclusions', result.get('exclusions') or [])
        self.store.set('sync_interval_s', result.get('sync_interval_s', 120))
        self.store.set('last_sync', self.clock())
        self.last_error = None
        return len(batch) == BATCH and self.store.pending_count() > 0

    def run(self, stop):
        backoff = 15
        while not stop.is_set():
            try:
                while self.sync_once() and not stop.is_set():
                    pass
                wait, backoff = self.store.get('sync_interval_s', 120), 15
            except Unauthorized as e:
                self.last_error = str(e)
                log.error('%s; retrying in 10 min', e)
                wait = 600
            except SyncError as e:
                self.last_error = str(e)
                log.info('%s; %d records queued', e, self.store.pending_count())
                wait, backoff = backoff, min(backoff * 2, 300)
            except Exception:
                self.last_error = 'unexpected error (see log)'
                log.exception('Sync failed')
                wait = 120
            self.wake.wait(wait)
            self.wake.clear()


def _parse(ts):
    return datetime.fromisoformat(ts).timestamp()


def today_status(store, tracker=None, now=None):
    """Today's time: the server's last figure plus anything not yet sent.

    Returns dict(used_s, limit_s, status, estimate: bool, last_sync, pending).
    """
    now = now or time.time()
    today = date.fromtimestamp(now)
    midnight = datetime.combine(today, datetime.min.time()).timestamp()
    tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time()).timestamp()
    server = store.get('today') or {}
    same_day = server.get('date') == today.isoformat()
    used = server.get('used_s', 0) if same_day else 0
    limit = server.get('limit_s') if same_day else None
    rules = store.get('exclusions', [])

    extra, pending = 0.0, 0
    for rec in store.pending(100000):
        if rec.get('kind') != 'session':
            continue
        pending += 1
        if titles.excluded(rules, rec.get('app_id'), rec.get('title'), rec.get('url')):
            continue
        start, end = max(_parse(rec['start']), midnight), min(_parse(rec['end']), tomorrow)
        extra += max(0.0, end - start)
    open_session = tracker.current if tracker else None
    if open_session and not titles.excluded(rules, open_session.sample.app_id,
                                            open_session.sample.title, open_session.sample.url):
        extra += max(0.0, open_session.last - max(open_session.start, midnight))

    used = int(used + extra)
    if limit is None:
        status = 'unknown' if not same_day else 'under'
    elif used >= limit:
        status = 'over'
    elif used >= limit * 0.9:
        status = 'near'
    else:
        status = 'under'
    return {'used_s': used, 'limit_s': limit, 'status': status, 'estimate': pending > 0 or not same_day,
            'last_sync': store.get('last_sync'), 'pending': pending}


def fmt_duration(seconds):
    minutes = int(seconds or 0) // 60
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m' if hours else f'{minutes}m'
