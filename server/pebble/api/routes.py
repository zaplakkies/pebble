from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request

from pebble import db
from pebble.api.ingest import process_sync
from pebble.models import Device, hash_token
from pebble.timeutil import local_now
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
