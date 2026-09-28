from datetime import datetime, timedelta, timezone

from pebble.models import Alert, DeviceEvent, Session

SAST = timezone(timedelta(hours=2))


def ts(minutes_ago):
    return (datetime.now(SAST) - timedelta(minutes=minutes_ago)).isoformat(timespec='seconds')


def alert_kinds():
    return [a.kind for a in Alert.query.all()]


def test_rejects_missing_or_bad_token(client, device_token):
    assert client.post('/api/v1/sync', json={}).status_code == 401
    assert client.post('/api/v1/sync', json={},
                       headers={'Authorization': 'Bearer nope'}).status_code == 401


def test_sync_stores_sessions_and_reports_today(sync, records):
    r = sync([records.session(ts(30), ts(10), url='https://www.youtube.com/watch?v=1',
                              title='Video - YouTube')])
    assert r.status_code == 200
    data = r.get_json()
    assert data['accepted_through_seq'] == 1
    assert data['today']['used_s'] == 20 * 60
    assert data['today']['status'] == 'under'
    session = Session.query.one()
    assert session.domain == 'youtube.com'
    assert alert_kinds() == []


def test_resending_same_records_is_idempotent(sync, records):
    batch = [records.session(ts(30), ts(10))]
    sync(batch)
    r = sync(batch)
    assert r.get_json()['accepted_through_seq'] == 1
    assert Session.query.count() == 1
    assert alert_kinds() == []


def test_bad_record_is_rejected_but_seq_advances(sync, records):
    r = sync([records.session(ts(10), ts(30)), records.session(ts(30), ts(20))])
    data = r.get_json()
    assert data['accepted_through_seq'] == 2
    assert len(data['rejected']) == 1
    assert Session.query.count() == 1


def test_sequence_gap_raises_alert(sync, records):
    sync([records.session(ts(50), ts(40))])
    records.seq += 2  # records 2 and 3 "deleted" on the device
    sync([records.session(ts(30), ts(20))])
    assert alert_kinds() == ['records_missing']
    assert '#2–#3' in Alert.query.one().detail


def test_modified_record_raises_alert(sync, records):
    rec = records.session(ts(30), ts(20))
    rec['end'] = ts(25)
    sync([rec])
    assert alert_kinds() == ['record_modified']


def test_broken_chain_raises_alert(sync, records):
    sync([records.session(ts(50), ts(40))])
    records.last_hash = 'f' * 64
    sync([records.session(ts(30), ts(20))])
    assert alert_kinds() == ['chain_broken']


def test_reinstall_raises_alert_and_restarts_sequence(sync, records, app):
    sync([records.session(ts(50), ts(40))])
    fresh = type(records)()
    sync([fresh.session(ts(30), ts(20))], install_id='install-2')
    assert alert_kinds() == ['install_changed']
    assert Session.query.count() == 2


def test_clock_skew_raises_alert_once(sync, records):
    wrong = (datetime.now(SAST) - timedelta(hours=1)).isoformat()
    sync([], device_time=wrong)
    sync([], device_time=wrong)
    assert alert_kinds() == ['clock_skew']


def test_agent_start_without_stop_is_unclean(sync, records):
    sync([records(kind='event', at=ts(60), type='agent_start'),
          records(kind='event', at=ts(30), type='agent_start')])
    assert alert_kinds() == ['unclean_stop']
    assert DeviceEvent.query.count() == 2


def test_clean_restart_raises_nothing(sync, records):
    sync([records(kind='event', at=ts(60), type='agent_start'),
          records(kind='event', at=ts(40), type='agent_stop'),
          records(kind='event', at=ts(30), type='agent_start')])
    assert alert_kinds() == []


def test_status_endpoint(client, device_token):
    r = client.get('/api/v1/status', headers={'Authorization': f'Bearer {device_token}'})
    assert r.status_code == 200
    assert r.get_json()['today']['limit_s'] in (120 * 60, 180 * 60)


def test_dashboard_pages_render(client, sync, records, kid):
    sync([records.session(ts(30), ts(10), title='Essay.docx - Word', document='Essay.docx',
                          app_id='WINWORD.EXE', app_name='Microsoft Word')])
    assert b'Emma' in client.get('/').data
    page = client.get(f'/kid/{kid.id}').data
    assert b'Essay.docx' in page and b'Microsoft Word' in page
    assert client.get(f'/kid/{kid.id}?day=nonsense').status_code == 400


def test_agent_start_in_new_session_is_not_unclean(sync, records):
    sync([records(kind='event', at=ts(60), type='agent_start'),
          records(kind='event', at=ts(30), type='agent_start', details={'new_session': True})])
    assert alert_kinds() == []


def test_agent_gap_raises_alert(sync, records):
    sync([records(kind='event', at=ts(1), type='agent_gap',
                  details={'from': ts(90), 'to': ts(30), 'slept_s': 600})])
    alert = Alert.query.one()
    assert alert.kind == 'agent_not_running'
    assert 'about 50 min' in alert.detail


def test_downloads(client, app, tmp_path):
    app.config['DOWNLOADS_DIR'] = str(tmp_path)
    assert b'Nothing here yet' in client.get('/downloads').data
    (tmp_path / 'pebble-agent.exe').write_bytes(b'MZ')
    assert b'pebble-agent.exe' in client.get('/downloads').data
    assert client.get('/downloads/pebble-agent.exe').data == b'MZ'
    assert client.get('/downloads/../run.py').status_code == 404
    (tmp_path / 'pebble-agent.apk').write_bytes(b'PK')
    assert client.get('/downloads/pebble-agent.apk').mimetype == 'application/vnd.android.package-archive'
