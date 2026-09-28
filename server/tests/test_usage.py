from datetime import date, datetime

from pebble import db
from pebble.models import Adjustment, Device, ExclusionRule, Kid, Session
from pebble.usage import summarize_day

DAY = date(2026, 9, 28)  # a Monday; Africa/Johannesburg is UTC+2


def utc(h, m=0, day=28):
    return datetime(2026, 9, day, h, m)


def add_session(device, start, end, app_id='chrome.exe', **extra):
    s = Session(device=device, record_id=f'r{Session.query.count()}', seq=1,
                start=start, end=end, app_id=app_id, **extra)
    db.session.add(s)
    db.session.commit()
    return s


def make_device(kid, name='laptop'):
    d = Device(kid=kid, name=name, platform='windows', token_hash=name)
    db.session.add(d)
    db.session.commit()
    return d


def test_basic_total_and_status(kid):
    d = make_device(kid)
    add_session(d, utc(8), utc(9, 50))  # 110 min of a 120 min limit
    s = summarize_day(kid, DAY)
    assert s.used_s == 110 * 60
    assert s.status == 'near'
    add_session(d, utc(10), utc(10, 30))
    assert summarize_day(kid, DAY).status == 'over'


def test_day_boundary_uses_server_local_time(kid):
    d = make_device(kid)
    # 21:30–22:30 UTC on the 27th = 23:30–00:30 local: 30 min on each local day.
    add_session(d, utc(21, 30, day=27), utc(22, 30, day=27))
    assert summarize_day(kid, date(2026, 9, 27)).used_s == 30 * 60
    assert summarize_day(kid, DAY).used_s == 30 * 60


def test_overlapping_devices_count_once(kid):
    laptop, phone = make_device(kid, 'laptop'), make_device(kid, 'phone')
    add_session(laptop, utc(8), utc(9))
    add_session(phone, utc(8, 30), utc(9, 30))
    assert summarize_day(kid, DAY).used_s == 90 * 60


def test_exclusion_rules(kid):
    d = make_device(kid)
    add_session(d, utc(8), utc(9), app_id='WINWORD.EXE')
    add_session(d, utc(9), utc(9, 30), domain='classroom.google.com')
    add_session(d, utc(10), utc(10, 20), domain='youtube.com')
    db.session.add_all([
        ExclusionRule(app_id='winword.exe', reason='Homework'),
        ExclusionRule(kid_id=kid.id, domain='google.com', reason='School'),
    ])
    db.session.commit()
    s = summarize_day(kid, DAY)
    assert s.used_s == 20 * 60
    assert s.excluded_s == 90 * 60
    assert [v.excluded_reason for v in s.sessions] == ['Homework', 'School', None]


def test_rule_for_other_kid_does_not_apply(kid):
    other = Kid(name='Sam')
    db.session.add(other)
    db.session.commit()
    add_session(make_device(kid), utc(8), utc(9), app_id='game.exe')
    db.session.add(ExclusionRule(kid_id=other.id, app_id='game.exe'))
    db.session.commit()
    assert summarize_day(kid, DAY).used_s == 60 * 60


def test_title_pattern_rule(kid):
    add_session(make_device(kid), utc(8), utc(9), title='Essay.docx - Word')
    db.session.add(ExclusionRule(title_pattern='*.docx - word'))
    db.session.commit()
    assert summarize_day(kid, DAY).used_s == 0


def test_adjustments(kid):
    d = make_device(kid)
    s1 = add_session(d, utc(8), utc(9))
    add_session(d, utc(10), utc(11))
    db.session.add_all([
        Adjustment(kid_id=kid.id, day=DAY, session_id=s1.id, reason='Online lesson'),
        Adjustment(kid_id=kid.id, day=DAY, minutes=-15, reason='Chores bonus'),
    ])
    db.session.commit()
    s = summarize_day(kid, DAY)
    assert s.used_s == 45 * 60
    assert s.adjust_s == -15 * 60
    assert s.sessions[0].excluded_reason == 'Online lesson'


def test_no_limit(kid):
    kid.weekday_limit_min = None
    db.session.commit()
    add_session(make_device(kid), utc(8), utc(20))
    s = summarize_day(kid, DAY)
    assert s.limit_s is None and s.status == 'under'


def test_session_exclusion_applies_across_midnight(kid):
    s = add_session(make_device(kid), utc(21, 30, day=27), utc(22, 30, day=27))
    db.session.add(Adjustment(kid_id=kid.id, day=date(2026, 9, 27), session_id=s.id))
    db.session.commit()
    assert summarize_day(kid, date(2026, 9, 27)).used_s == 0
    assert summarize_day(kid, DAY).used_s == 0
