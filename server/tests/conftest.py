import hashlib
import json
import uuid

import pytest

from pebble import create_app, db
from pebble.config import Config
from pebble.models import Device, Kid, hash_token


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    TIMEZONE = 'Africa/Johannesburg'
    MANAGE_PATH = 'secret-manage'


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def kid(app):
    kid = Kid(name='Emma', weekday_limit_min=120, weekend_limit_min=180)
    db.session.add(kid)
    db.session.commit()
    return kid


@pytest.fixture
def device_token(kid):
    token = 'test-token'
    db.session.add(Device(kid=kid, name='Emma laptop', platform='windows',
                          token_hash=hash_token(token)))
    db.session.commit()
    return token


class RecordMaker:
    """Builds records the way a real agent does: sequence numbers plus a hash chain."""

    def __init__(self):
        self.seq, self.last_hash = 0, None

    def __call__(self, **fields):
        self.seq += 1
        record = {'seq': self.seq, 'id': str(uuid.uuid4()), 'prev_hash': self.last_hash, **fields}
        body = json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        record['hash'] = hashlib.sha256(body.encode()).hexdigest()
        self.last_hash = record['hash']
        return record

    def session(self, start, end, app_id='chrome.exe', **extra):
        return self(kind='session', start=start, end=end, app_id=app_id, **extra)


@pytest.fixture
def records():
    return RecordMaker()


@pytest.fixture
def sync(client, device_token):
    def _sync(recs, install_id='install-1', **extra):
        return client.post('/api/v1/sync', json={'records': recs, **extra},
                           headers={'Authorization': f'Bearer {device_token}',
                                    'X-Pebble-Install-Id': install_id})
    return _sync
