from datetime import timedelta

from pebble import db
from pebble.models import Device, Kid, Session
from pebble.timeutil import utc_now


def add_device(kid, name, platform='windows', last_seen=None, active=True):
    d = Device(kid=kid, name=name, platform=platform, token_hash=name,
               last_seen=last_seen, active=active)
    db.session.add(d)
    db.session.commit()
    return d


def test_board_lists_kids_today_and_device_last_seen(client, kid):
    now = utc_now()
    laptop = add_device(kid, 'Emma laptop', last_seen=now - timedelta(minutes=5))
    add_device(kid, 'Emma tablet', platform='android')
    add_device(kid, 'Old phone', platform='android', active=False)
    db.session.add(Session(device=laptop, record_id='r1', seq=1, app_id='chrome.exe',
                           start=now - timedelta(minutes=30), end=now - timedelta(minutes=10)))
    db.session.add(Kid(name='Ben'))
    db.session.commit()

    body = client.get('/board.json').get_json()

    assert body['time'] and body['date']
    assert [k['name'] for k in body['kids']] == ['Ben', 'Emma']
    ben, emma = body['kids']
    assert ben['devices'] == [] and ben['limit_s'] is None and ben['status'] == 'under'
    assert emma['limit_s'] in (120 * 60, 180 * 60)
    # Just after midnight the session falls on yesterday, so 0 is allowed too.
    assert 0 <= emma['used_s'] <= 20 * 60
    assert [d['name'] for d in emma['devices']] == ['Emma laptop', 'Emma tablet']
    assert 299 <= emma['devices'][0]['last_seen_s'] <= 302
    assert emma['devices'][1] == {'name': 'Emma tablet', 'platform': 'android',
                                  'last_seen_s': None}
