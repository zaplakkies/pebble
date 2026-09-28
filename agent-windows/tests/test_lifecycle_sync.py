import threading
from datetime import date, datetime
from pathlib import Path
import sys

import pytest

from pebble_agent.lifecycle import OsEvent, record_os_events, record_start, slept_seconds
from pebble_agent.sync import Syncer, today_status
from pebble_agent.tracker import Tracker, iso

H = 3600


def events(store):
    return [(r['type'], r.get('details')) for r in store.pending() if r['kind'] == 'event']


def test_first_start_has_no_gap(store, config):
    record_start(store, config, 'emma', now=10 * H, boot_time=9 * H, session_start=9 * H,
                 os_events=[])
    assert [e[0] for e in events(store)] == ['agent_start']
    assert events(store)[0][1]['new_session'] is True


def test_killed_in_same_session_reports_gap(store, config):
    store.set('last_alive:emma', 10 * H)
    record_start(store, config, 'emma', now=11 * H, boot_time=8 * H, session_start=9 * H,
                 os_events=[])
    (gap_type, gap), (start_type, start) = events(store)
    assert gap_type == 'agent_gap' and gap['slept_s'] == 0
    assert start_type == 'agent_start' and start['new_session'] is False


def test_sleep_is_not_a_gap(store, config):
    store.set('last_alive:emma', 10 * H)
    os_events = [OsEvent(10 * H + 10, 'os_sleep'), OsEvent(11 * H - 60, 'os_resume')]
    record_start(store, config, 'emma', now=11 * H, boot_time=8 * H, session_start=9 * H,
                 os_events=os_events)
    assert [e[0] for e in events(store)] == ['os_sleep', 'os_resume', 'agent_start']


def test_new_logon_is_not_a_gap_if_agent_started_promptly(store, config):
    store.set('last_alive:emma', 10 * H)  # before this logon: user logged off/on
    record_start(store, config, 'emma', now=12 * H + 30, boot_time=11 * H,
                 session_start=12 * H, os_events=[])
    assert [e[0] for e in events(store)] == ['agent_start']
    assert events(store)[0][1]['new_session'] is True


def test_agent_started_late_after_logon_is_a_gap(store, config):
    store.set('last_alive:emma', 10 * H)
    record_start(store, config, 'emma', now=13 * H, boot_time=11 * H, session_start=12 * H,
                 os_events=[])
    assert [e[0] for e in events(store)] == ['agent_gap', 'agent_start']


def test_os_events_reported_once(store):
    evs = [OsEvent(100, 'os_boot'), OsEvent(200, 'os_sleep')]
    assert len(record_os_events(store, evs)) == 2
    assert record_os_events(store, evs + [OsEvent(300, 'os_resume')])[0].type == 'os_resume'
    assert len(events(store)) == 3


def test_slept_seconds_clips_to_window():
    evs = [OsEvent(50, 'os_sleep'), OsEvent(150, 'os_resume'), OsEvent(300, 'os_sleep')]
    assert slept_seconds(evs, 100, 400) == 50 + 100


# ---------------------------------------------------------------- sync and estimate

class FakeServer:
    def __init__(self, today):
        self.today, self.calls = today, []

    def __call__(self, method, url, token, install_id, payload=None):
        self.calls.append(payload)
        seqs = [r['seq'] for r in payload['records']]
        return {'accepted_through_seq': max(seqs) if seqs else 0, 'today': self.today,
                'exclusions': [{'app_id': 'WINWORD.EXE'}], 'sync_interval_s': 60}


def test_sync_sends_and_acknowledges(store, config):
    for i in range(3):
        store.add(kind='event', at=iso(1000 + i), type='os_boot')
    server = FakeServer({'date': '2026-09-28', 'used_s': 100, 'limit_s': 7200, 'status': 'under'})
    syncer = Syncer(config, store, request=server)
    assert syncer.sync_once() is False
    assert store.pending() == []
    assert len(server.calls[0]['records']) == 3
    assert store.get('exclusions') == [{'app_id': 'WINWORD.EXE'}]


def test_estimate_adds_unsent_time_and_skips_excluded(store, config, probe, clock):
    today = date.fromtimestamp(clock.wall).isoformat()
    store.set('today', {'date': today, 'used_s': 600, 'limit_s': 3600, 'status': 'under'})
    store.set('exclusions', [{'app_id': 'WINWORD.EXE'}])
    t = Tracker(store, probe, config, user='emma', clock=clock, mono=clock.mono)

    def advance(seconds):
        for _ in range(seconds // 5):
            clock.advance(5)
            t.tick()
    probe.show('chrome.exe', 'Page')
    t.tick()
    advance(295)
    probe.show('WINWORD.EXE', 'Essay.docx - Word')  # ends chrome session: +300 s
    advance(300)
    probe.show('javaw.exe', 'Minecraft')  # Word session excluded
    advance(120)  # open Minecraft session: +120 s
    s = today_status(store, t, now=clock.wall)
    assert s["used_s"] == 600 + 300 + 115
    assert s['estimate'] is True and s['status'] == 'under'


def test_estimate_without_sync_today(store):
    s = today_status(store, now=datetime(2026, 9, 28, 12).timestamp())
    assert s['status'] == 'unknown' and s['used_s'] == 0


# ---------------------------------------------------------------- against the real server

SERVER_DIR = Path(__file__).resolve().parents[2] / 'server'


@pytest.fixture
def live_server():
    pytest.importorskip('flask')
    sys.path.insert(0, str(SERVER_DIR))
    from werkzeug.serving import make_server
    from pebble import create_app, db
    from pebble.config import Config as ServerConfig
    from pebble.models import Device, Kid, hash_token

    class TestConfig(ServerConfig):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = 'sqlite://'
        SQLALCHEMY_ENGINE_OPTIONS = {'connect_args': {'check_same_thread': False},
                                     'poolclass': __import__('sqlalchemy.pool').pool.StaticPool}

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        kid = Kid(name='Emma', weekday_limit_min=120, weekend_limit_min=120)
        db.session.add_all([kid, Device(kid=kid, name='PC', platform='windows',
                                        token_hash=hash_token('real-token'))])
        db.session.commit()
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield app, f'http://127.0.0.1:{server.server_port}'
    server.shutdown()


def test_agent_records_are_accepted_by_real_server(live_server, store, config, probe, clock):
    app, url = live_server
    config.server, config.token = url, 'real-token'
    clock.wall = datetime.now().timestamp() - 1800
    record_start(store, config, 'emma', now=clock.wall, boot_time=clock.wall - 60,
                 session_start=clock.wall - 30, os_events=[OsEvent(clock.wall - 60, 'os_boot')])
    t = Tracker(store, probe, config, user='emma', clock=clock, mono=clock.mono)
    probe.show('chrome.exe', 'Video - YouTube', 'https://www.youtube.com/watch?v=1')
    t.tick()
    for _ in range(120):  # 10 minutes, split into two sessions
        clock.advance(5)
        t.tick()
    probe.show('WINWORD.EXE', 'Essay.docx - Word')
    for _ in range(60):
        clock.advance(5)
        t.tick()
    t.close()

    syncer = Syncer(config, store)
    syncer.sync_once()
    assert store.pending() == []

    with app.app_context():
        from pebble.models import Alert, Session
        assert Alert.query.count() == 0, [a.detail for a in Alert.query]
        # Chrome split at 5 and 10 min, plus 5 s until the tick that saw Word.
        assert Session.query.count() == 4
        assert {s.domain for s in Session.query} == {'youtube.com', None}
    today = store.get('today')
    assert today['used_s'] == 15 * 60
    assert today_status(store)['estimate'] is False
