from datetime import timedelta

import pytest

from pebble import db
from pebble.models import Adjustment, Alert, AuditLog, Device, ExclusionRule, Kid, Session, hash_token
from pebble.timeutil import local_today, utc_now

M = '/secret-manage'


@pytest.fixture
def post(client):
    with client.session_transaction() as s:
        s['csrf_token'] = 'tok'

    def _post(path, data=None, **kwargs):
        return client.post(M + path, data={'csrf_token': 'tok', **(data or {})}, **kwargs)
    return _post


def last_audit():
    return AuditLog.query.order_by(AuditLog.id.desc()).first()


def test_pages_render(client, kid, device_token):
    for path in ('/', '/kids', f'/kids/{kid.id}/edit', f'/kids/{kid.id}/day', '/devices',
                 '/devices/1', '/rules', '/alerts', '/alerts?show=all', '/audit'):
        assert client.get(M + path).status_code == 200, path


def test_wrong_path_is_404(client):
    assert client.get('/manage/').status_code == 404


def test_post_without_csrf_is_rejected(client, kid):
    assert client.post(M + '/kids', data={'name': 'Sam'}).status_code == 400
    assert Kid.query.count() == 1


def test_add_kid_is_audited(post):
    r = post('/kids', {'name': 'Sam', 'weekday_limit_min': '1:30', 'weekend_limit_min': ''})
    assert r.status_code == 302
    sam = Kid.query.filter_by(name='Sam').one()
    assert sam.weekday_limit_min == 90 and sam.weekend_limit_min is None
    entry = last_audit()
    assert (entry.action, entry.entity, entry.new['name']) == ('create', 'kid', 'Sam')


def test_edit_kid_audits_only_changes(post, kid):
    post(f'/kids/{kid.id}/edit', {'name': 'Emma', 'weekday_limit_min': '240',
                                  'weekend_limit_min': '180'})
    entry = last_audit()
    assert entry.old == {'name': 'Emma', 'weekday_limit_min': 120}
    assert entry.new == {'name': 'Emma', 'weekday_limit_min': 240}


def test_bad_limit_is_rejected(post, kid):
    post(f'/kids/{kid.id}/edit', {'name': 'Emma', 'weekday_limit_min': 'lots'},
         follow_redirects=True)
    assert db.session.get(Kid, kid.id).weekday_limit_min == 120
    assert AuditLog.query.count() == 0


def test_add_device_shows_token_once(post, kid, client):
    r = post('/devices', {'kid_id': kid.id, 'name': 'Phone', 'platform': 'android'})
    device = Device.query.filter_by(name='Phone').one()
    token = r.get_data(as_text=True).split('class="copy token">')[1].split('<')[0]
    assert device.token_hash == hash_token(token)
    assert token not in client.get(M + f'/devices/{device.id}').get_data(as_text=True)
    assert last_audit().new['token'] == 'issued'


def test_new_token_invalidates_old_and_resets_sync_state(post, device_token, client):
    device = Device.query.one()
    device.install_id, device.last_seq = 'old-install', 50
    db.session.commit()
    post(f'/devices/{device.id}/token')
    assert device.token_hash != hash_token(device_token)
    assert (device.install_id, device.last_seq) == (None, 0)
    r = client.get('/api/v1/status', headers={'Authorization': f'Bearer {device_token}'})
    assert r.status_code == 401


def pair_code(response):
    return response.get_data(as_text=True).split('class="copy pair-code">')[1].split('<')[0]


def test_pairing_code_swaps_for_a_fresh_token(post, kid, client):
    r = post('/devices', {'kid_id': kid.id, 'name': 'PC', 'platform': 'windows'})
    shown_token = r.get_data(as_text=True).split('class="copy token">')[1].split('<')[0]
    code = pair_code(r)
    assert f'--code {code.replace(" ", "")}' in r.get_data(as_text=True)

    r = client.post('/api/v1/pair', json={'code': code})   # "123 456" with the space is fine
    assert r.status_code == 200
    assert r.json['device'] == 'PC' and r.json['kid'] == 'Emma'
    token = r.json['token']
    assert client.get('/api/v1/status',
                      headers={'Authorization': f'Bearer {token}'}).status_code == 200
    assert client.get('/api/v1/status',
                      headers={'Authorization': f'Bearer {shown_token}'}).status_code == 401
    assert last_audit().new == {'token': 'paired'}
    # One use only.
    assert client.post('/api/v1/pair', json={'code': code}).status_code == 404


def test_pairing_code_for_running_device_keeps_token_until_used(post, device_token, client):
    r = post('/devices/1/code')
    code = pair_code(r)
    assert 'class="copy token"' not in r.get_data(as_text=True)
    auth = {'Authorization': f'Bearer {device_token}'}
    assert client.get('/api/v1/status', headers=auth).status_code == 200
    assert client.post('/api/v1/pair', json={'code': code}).status_code == 200
    assert client.get('/api/v1/status', headers=auth).status_code == 401


def test_pairing_code_expires(post, device_token, client):
    code = pair_code(post('/devices/1/code'))
    device = Device.query.one()
    device.pair_expires = utc_now() - timedelta(seconds=1)
    db.session.commit()
    assert client.post('/api/v1/pair', json={'code': code}).status_code == 404
    assert device.pair_code_hash is None


def test_pairing_code_not_usable_on_revoked_device(post, device_token, client):
    code = pair_code(post('/devices/1/code'))
    post('/devices/1/active', {'active': '0'})
    assert client.post('/api/v1/pair', json={'code': code}).status_code == 404


def test_guessing_cancels_live_pairing_codes(post, device_token, client):
    code = pair_code(post('/devices/1/code')).replace(' ', '')
    wrong = f'{(int(code) + 1) % 10**6:06d}'
    for _ in range(10):
        assert client.post('/api/v1/pair', json={'code': wrong}).status_code == 404
    assert client.post('/api/v1/pair', json={'code': code}).status_code == 404
    assert [a.kind for a in Alert.query.all()] == ['pairing_code_cancelled']


def test_pair_rejects_junk(client, device_token):
    for body in (None, [], {}, {'code': 'abc'}, {'code': 12}):
        assert client.post('/api/v1/pair', json=body).status_code == 404


def test_revoke_device(post, device_token, client):
    post('/devices/1/active', {'active': '0'})
    r = client.get('/api/v1/status', headers={'Authorization': f'Bearer {device_token}'})
    assert r.status_code == 401
    assert last_audit().new == {'name': 'Emma laptop', 'active': False}


def test_rule_needs_a_criterion(post):
    post('/rules', {'kid_id': 'all', 'reason': 'nothing'})
    assert ExclusionRule.query.count() == 0


def test_add_edit_delete_rule(post, kid):
    post('/rules', {'kid_id': 'all', 'domain': 'www.Classroom.Google.com', 'reason': 'School'})
    rule = ExclusionRule.query.one()
    assert rule.domain == 'classroom.google.com' and rule.kid_id is None and rule.active
    post(f'/rules/{rule.id}', {'kid_id': kid.id, 'domain': 'classroom.google.com',
                               'reason': 'School', 'active': '0'})
    assert last_audit().new == {'kid': 'Emma', 'active': False}
    post(f'/rules/{rule.id}/delete')
    assert ExclusionRule.query.count() == 0
    assert last_audit().action == 'delete'


def _session(device_id):
    now = utc_now()
    s = Session(device_id=device_id, record_id='r1', seq=1, start=now - timedelta(minutes=40),
                end=now - timedelta(minutes=10), app_id='chrome.exe', app_name='Chrome')
    db.session.add(s)
    db.session.commit()
    return s


def test_exclude_session_and_count_again(post, kid, device_token):
    s = _session(Device.query.one().id)
    post(f'/sessions/{s.id}/exclude', {'day': local_today().isoformat()})
    adj = Adjustment.query.one()
    assert adj.session_id == s.id
    post(f'/sessions/{s.id}/exclude')  # second click does nothing
    assert Adjustment.query.count() == 1
    post(f'/adjustments/{adj.id}/delete')
    assert Adjustment.query.count() == 0
    assert [e.action for e in AuditLog.query.order_by(AuditLog.id)] == ['create', 'delete']


def test_minute_adjustments(post, kid):
    post(f'/kids/{kid.id}/adjust', {'minutes': '30', 'direction': 'remove', 'reason': 'Lesson'})
    post(f'/kids/{kid.id}/adjust', {'minutes': '10', 'direction': 'add'})
    assert sorted(a.minutes for a in Adjustment.query) == [-30, 10]
    post(f'/kids/{kid.id}/adjust', {'minutes': 'abc'})
    assert Adjustment.query.count() == 2


def test_acknowledging_alerts_is_audited(post, device_token):
    device = Device.query.one()
    db.session.add_all([Alert(device=device, kind='records_missing', detail='x'),
                        Alert(device=device, kind='clock_skew', detail='y')])
    db.session.commit()
    first = Alert.query.first()
    post('/alerts/ack', {'alert_id': first.id})
    assert Alert.query.filter_by(acknowledged=False).count() == 1
    post('/alerts/ack')
    assert Alert.query.filter_by(acknowledged=False).count() == 0
    assert last_audit().entity == 'alert'


def test_delete_kid_blocked_while_it_has_devices(post, kid, device_token):
    post(f'/kids/{kid.id}/delete')
    assert Kid.query.count() == 1


def test_public_page_shows_last_change(post, client):
    post('/kids', {'name': 'Sam'})
    assert b'Settings last changed' in client.get('/').data
