import fnmatch
import hashlib
import secrets
from datetime import timedelta

from pebble import db
from pebble.timeutil import utc_now


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


# A pairing code is a short one-time code typed on the device instead of the long token.
PAIR_CODE_TTL = timedelta(minutes=15)
# Wrong codes tried (by anyone) while a code is live before that code is cancelled.
PAIR_MAX_FAILURES = 10


class Kid(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    # Minutes per day; None means no limit.
    weekday_limit_min = db.Column(db.Integer, nullable=True)
    weekend_limit_min = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    devices = db.relationship('Device', backref='kid', lazy=True)

    def limit_min_for(self, day):
        return self.weekend_limit_min if day.weekday() >= 5 else self.weekday_limit_min

    def __repr__(self):
        return f"Kid('{self.name}')"


class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kid_id = db.Column(db.Integer, db.ForeignKey('kid.id'), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    platform = db.Column(db.String(20), nullable=False)  # windows | android
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    # Sync state
    install_id = db.Column(db.String(64), nullable=True)
    agent_version = db.Column(db.String(20), nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)
    last_seq = db.Column(db.Integer, nullable=False, default=0)
    last_hash = db.Column(db.String(64), nullable=True)

    # Pairing (see PAIR_CODE_TTL)
    pair_code_hash = db.Column(db.String(64), unique=True, nullable=True)
    pair_expires = db.Column(db.DateTime, nullable=True)
    pair_failures = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    sessions = db.relationship('Session', backref='device', lazy=True)
    events = db.relationship('DeviceEvent', backref='device', lazy=True)

    @staticmethod
    def new_token():
        return secrets.token_urlsafe(32)

    def new_pair_code(self):
        """Issue a 6-digit one-time pairing code, replacing any earlier one."""
        while True:
            code = f'{secrets.randbelow(10**6):06d}'
            if not Device.query.filter_by(pair_code_hash=hash_token(code)).first():
                break
        self.pair_code_hash = hash_token(code)
        self.pair_expires = utc_now() + PAIR_CODE_TTL
        self.pair_failures = 0
        return code

    def clear_pair_code(self):
        self.pair_code_hash, self.pair_expires, self.pair_failures = None, None, 0

    def reset_sync_state(self):
        """A fresh token means a fresh agent setup, so don't flag the new install as tampering."""
        self.install_id, self.last_seq, self.last_hash = None, 0, None

    def __repr__(self):
        return f"Device('{self.name}', '{self.platform}')"


class Session(db.Model):
    """A continuous stretch of foreground use of one app/title/url. Never modified after ingest."""
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False, index=True)
    record_id = db.Column(db.String(64), unique=True, nullable=False)
    seq = db.Column(db.Integer, nullable=False)
    start = db.Column(db.DateTime, nullable=False, index=True)
    end = db.Column(db.DateTime, nullable=False, index=True)
    app_id = db.Column(db.String(200), nullable=False)
    app_name = db.Column(db.String(200), nullable=True)
    title = db.Column(db.String(500), nullable=True)
    url = db.Column(db.String(2000), nullable=True)
    domain = db.Column(db.String(255), nullable=True, index=True)
    document = db.Column(db.String(500), nullable=True)
    received_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    @property
    def display_name(self):
        return self.app_name or self.app_id


class DeviceEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False, index=True)
    record_id = db.Column(db.String(64), unique=True, nullable=False)
    seq = db.Column(db.Integer, nullable=False)
    at = db.Column(db.DateTime, nullable=False, index=True)
    type = db.Column(db.String(40), nullable=False)
    details = db.Column(db.JSON, nullable=True)
    received_at = db.Column(db.DateTime, nullable=False, default=utc_now)


class ExclusionRule(db.Model):
    """Time matching this rule does not count. All non-empty criteria must match."""
    id = db.Column(db.Integer, primary_key=True)
    kid_id = db.Column(db.Integer, db.ForeignKey('kid.id'), nullable=True)  # None = all kids
    app_id = db.Column(db.String(200), nullable=True)
    domain = db.Column(db.String(255), nullable=True)
    title_pattern = db.Column(db.String(500), nullable=True)  # glob, e.g. "*.docx - Word"
    reason = db.Column(db.String(200), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    kid = db.relationship('Kid')

    def matches(self, session):
        if not (self.app_id or self.domain or self.title_pattern):
            return False
        if self.app_id and (session.app_id or '').lower() != self.app_id.lower():
            return False
        if self.domain:
            d, rule = (session.domain or '').lower(), self.domain.lower()
            if not (d == rule or d.endswith('.' + rule)):
                return False
        if self.title_pattern and not fnmatch.fnmatch(
                (session.title or '').lower(), self.title_pattern.lower()):
            return False
        return True

    def to_agent_dict(self):
        return {k: v for k, v in (('app_id', self.app_id), ('domain', self.domain),
                                  ('title_pattern', self.title_pattern)) if v}


class Adjustment(db.Model):
    """Either +/- minutes on a day, or excluding one session from the count."""
    id = db.Column(db.Integer, primary_key=True)
    kid_id = db.Column(db.Integer, db.ForeignKey('kid.id'), nullable=False)
    day = db.Column(db.Date, nullable=False, index=True)
    minutes = db.Column(db.Integer, nullable=True)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=True)
    reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    kid = db.relationship('Kid')
    session = db.relationship('Session')


class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=True, index=True)
    kind = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    acknowledged = db.Column(db.Boolean, nullable=False, default=False)

    device = db.relationship('Device')


class AuditLog(db.Model):
    """Append-only record of management changes. Nothing in the app edits or deletes rows."""
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    action = db.Column(db.String(40), nullable=False)   # create | update | delete
    entity = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    old = db.Column(db.JSON, nullable=True)
    new = db.Column(db.JSON, nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
