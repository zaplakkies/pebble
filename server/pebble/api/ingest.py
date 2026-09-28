"""Processing of agent /sync payloads, including tamper checks."""
import hashlib
import json
from datetime import timedelta
from urllib.parse import urlsplit

from flask import current_app

from pebble.models import DeviceEvent, Session
from pebble.services import raise_alert
from pebble.timeutil import parse_timestamp, to_local, utc_now
from pebble import db

EVENT_TYPES = {'agent_start', 'agent_stop', 'os_boot', 'os_shutdown', 'os_sleep', 'os_resume',
               'clock_jump', 'permission_lost', 'permission_restored', 'backfill'}
LIFECYCLE_TYPES = ('agent_start', 'agent_stop', 'os_shutdown')
MAX_SESSION = timedelta(hours=24)


class RecordError(ValueError):
    pass


def record_hash(record):
    """sha256 of the record's canonical JSON without its own "hash" field."""
    body = {k: v for k, v in record.items() if k != 'hash'}
    canonical = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def domain_of(url):
    if not url:
        return None
    if '://' not in url:
        url = 'http://' + url
    host = urlsplit(url).hostname
    if host and host.startswith('www.'):
        host = host[4:]
    return host


def _text(value, limit):
    if value is None:
        return None
    return str(value)[:limit] or None


def _time(record, key):
    value = record.get(key)
    if not isinstance(value, str):
        raise RecordError(f'missing {key}')
    try:
        return parse_timestamp(value)
    except ValueError:
        raise RecordError(f'bad timestamp in {key}')


def _fmt_local(dt_utc):
    return to_local(dt_utc).strftime('%Y-%m-%d %H:%M')


def process_sync(device, payload, install_id):
    now = utc_now()

    if install_id:
        if device.install_id and device.install_id != install_id:
            raise_alert(device, 'install_changed',
                        'Agent was reinstalled or its token is being used by another install.')
            device.last_seq, device.last_hash = 0, None
        device.install_id = install_id[:64]

    device.agent_version = _text(payload.get('agent_version'), 20) or device.agent_version
    device.last_seen = now

    device_time = payload.get('device_time')
    if isinstance(device_time, str):
        try:
            skew = (parse_timestamp(device_time) - now).total_seconds()
        except ValueError:
            skew = 0
        if abs(skew) > current_app.config['CLOCK_SKEW_ALERT_S']:
            raise_alert(device, 'clock_skew',
                        f'Device clock is {int(skew / 60):+d} min off the server clock.',
                        dedupe_hours=6)

    records = payload.get('records') or []
    if not isinstance(records, list):
        raise ValueError('records must be a list')

    rejected = []
    valid = [r for r in records if isinstance(r, dict) and isinstance(r.get('seq'), int)]
    for rec in records:
        if rec not in valid:
            rejected.append({'id': rec.get('id') if isinstance(rec, dict) else None,
                             'error': 'record must be an object with an integer seq'})
    for rec in sorted(valid, key=lambda r: r['seq']):
        try:
            _ingest_record(device, rec)
        except RecordError as e:
            rejected.append({'id': rec.get('id'), 'seq': rec['seq'], 'error': str(e)})

    return {'accepted_through_seq': device.last_seq, 'rejected': rejected}


def _ingest_record(device, rec):
    record_id = rec.get('id')
    if not isinstance(record_id, str) or not record_id:
        raise RecordError('missing id')
    if (Session.query.filter_by(record_id=record_id).first()
            or DeviceEvent.query.filter_by(record_id=record_id).first()):
        return  # already stored, agent is resending

    _check_chain(device, rec)

    kind = rec.get('kind')
    if kind == 'session':
        _ingest_session(device, rec)
    elif kind == 'event':
        _ingest_event(device, rec)
    else:
        raise RecordError(f'unknown kind {kind!r}')


def _check_chain(device, rec):
    seq = rec['seq']
    if seq <= device.last_seq:
        raise_alert(device, 'seq_out_of_order',
                    f'Received new record #{seq} after #{device.last_seq}; '
                    'the agent state may have been reset.', dedupe_hours=6)
    elif seq > device.last_seq + 1:
        missing = f'#{device.last_seq + 1}' if seq == device.last_seq + 2 \
            else f'#{device.last_seq + 1}–#{seq - 1}'
        raise_alert(device, 'records_missing',
                    f'Records {missing} never arrived; they may have been deleted on the device.')

    if rec.get('hash') != record_hash(rec):
        raise_alert(device, 'record_modified',
                    f'Record #{seq} does not match its hash; it was altered on the device.')
    elif seq == device.last_seq + 1 and device.last_hash and rec.get('prev_hash') != device.last_hash:
        raise_alert(device, 'chain_broken',
                    f'Record #{seq} does not follow on from #{device.last_seq}.')

    if seq > device.last_seq:
        device.last_seq, device.last_hash = seq, _text(rec.get('hash'), 64)


def _ingest_session(device, rec):
    start, end = _time(rec, 'start'), _time(rec, 'end')
    if end <= start:
        raise RecordError('end must be after start')
    if end - start > MAX_SESSION:
        raise RecordError('session longer than 24h')
    app_id = _text(rec.get('app_id'), 200)
    if not app_id:
        raise RecordError('missing app_id')
    url = _text(rec.get('url'), 2000)
    db.session.add(Session(
        device_id=device.id, record_id=rec['id'][:64], seq=rec['seq'], start=start, end=end,
        app_id=app_id, app_name=_text(rec.get('app_name'), 200), title=_text(rec.get('title'), 500),
        url=url, domain=_text(domain_of(url), 255), document=_text(rec.get('document'), 500)))


def _ingest_event(device, rec):
    at = _time(rec, 'at')
    event_type = rec.get('type')
    if event_type not in EVENT_TYPES:
        raise RecordError(f'unknown event type {event_type!r}')
    details = rec.get('details') if isinstance(rec.get('details'), dict) else None

    if event_type == 'agent_start':
        previous = (DeviceEvent.query
                    .filter(DeviceEvent.device_id == device.id, DeviceEvent.at <= at,
                            DeviceEvent.type.in_(LIFECYCLE_TYPES))
                    .order_by(DeviceEvent.at.desc()).first())
        if previous and previous.type == 'agent_start':
            raise_alert(device, 'unclean_stop',
                        f'Agent stopped without shutting down cleanly after {_fmt_local(previous.at)} '
                        '(killed, crashed or power loss).')
    elif event_type == 'permission_lost':
        what = (details or {}).get('permission', 'a required permission')
        raise_alert(device, 'permission_lost', f'{what} was turned off at {_fmt_local(at)}.')
    elif event_type == 'clock_jump':
        delta = (details or {}).get('delta_s', 0)
        raise_alert(device, 'clock_jump',
                    f'Device clock was changed by {int(delta / 60):+d} min at {_fmt_local(at)}.')

    db.session.add(DeviceEvent(device_id=device.id, record_id=rec['id'][:64], seq=rec['seq'],
                               at=at, type=event_type, details=details))
