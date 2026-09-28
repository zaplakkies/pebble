from datetime import timedelta

from flask import has_request_context, request

from pebble import db
from pebble.models import Alert, AuditLog
from pebble.timeutil import utc_now


def raise_alert(device, kind, detail, dedupe_hours=None):
    """Create an alert. With dedupe_hours, skip if an unacknowledged one of the same kind is recent."""
    if dedupe_hours:
        since = utc_now() - timedelta(hours=dedupe_hours)
        exists = Alert.query.filter(
            Alert.device_id == (device.id if device else None), Alert.kind == kind,
            Alert.acknowledged.is_(False), Alert.created_at >= since).first()
        if exists:
            return exists
    alert = Alert(device_id=device.id if device else None, kind=kind, detail=detail[:500])
    db.session.add(alert)
    return alert


def record_audit(action, entity, entity_id=None, old=None, new=None):
    """Append an audit entry. Call before commit so it lands in the same transaction."""
    if has_request_context():
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = (request.user_agent.string or '')[:300]
    else:
        ip, user_agent = 'cli', None
    db.session.add(AuditLog(action=action, entity=entity, entity_id=entity_id,
                            old=old, new=new, ip=ip, user_agent=user_agent))
