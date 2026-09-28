from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request

from pebble import db
from pebble.api.ingest import process_sync
from pebble.models import PAIR_MAX_FAILURES, Device, hash_token
from pebble.services import raise_alert, record_audit
from pebble.timeutil import local_now, utc_now
from pebble.usage import active_rules, summarize_today

api = Blueprint('api', __name__)


def device_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        token = header[7:].strip() if header.startswith('Bearer ') else ''
        device = Device.query.filter_by(token_hash=hash_token(token), active=True).first() \
            if token else None
        if device is None:
            return jsonify(error='unknown or revoked device token'), 401
        g.device = device
        return f(*args, **kwargs)
    return wrapper


@api.route('/pair', methods=['POST'])
def pair():
    """Swap a one-time pairing code for a fresh device token."""
    payload = request.get_json(silent=True)
    code = ''.join(ch for ch in str(payload.get('code', '')) if ch.isdigit()) \
        if isinstance(payload, dict) else ''
    now = utc_now()
    device = Device.query.filter(Device.pair_code_hash == hash_token(code),
                                 Device.pair_expires > now, Device.active.is_(True)).first() \
        if len(code) == 6 else None

    if device is None:
        # Count the miss against every live code, so guessing burns them out quickly.
        for d in Device.query.filter(Device.pair_code_hash.isnot(None)).all():
            if d.pair_expires <= now:
                d.clear_pair_code()
                continue
            d.pair_failures += 1
            if d.pair_failures >= PAIR_MAX_FAILURES:
                d.clear_pair_code()
                raise_alert(d, 'pairing_code_cancelled',
                            f'{PAIR_MAX_FAILURES} wrong pairing codes were tried, so the code '
                            f'for {d.name} was cancelled. Issue a new one to set it up.')
        db.session.commit()
        return jsonify(error='unknown or expired pairing code'), 404

    token = Device.new_token()
    device.token_hash = hash_token(token)
    device.reset_sync_state()
    device.clear_pair_code()
    record_audit('update', 'device', device.id, new={'token': 'paired'})
    db.session.commit()
    return jsonify(token=token, device=device.name, kid=device.kid.name)


@api.route('/sync', methods=['POST'])
@device_auth
def sync():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='body must be a JSON object'), 400
    try:
        result = process_sync(g.device, payload, request.headers.get('X-Pebble-Install-Id'))
    except ValueError as e:
        db.session.rollback()
        return jsonify(error=str(e)), 400
    db.session.commit()

    kid = g.device.kid
    return jsonify(
        **result,
        server_time=local_now().isoformat(timespec='seconds'),
        sync_interval_s=current_app.config['SYNC_INTERVAL_S'],
        today=summarize_today(kid).as_api_dict(),
        exclusions=[r.to_agent_dict() for r in active_rules(kid)],
    )


@api.route('/status')
@device_auth
def status():
    return jsonify(today=summarize_today(g.device.kid).as_api_dict())
