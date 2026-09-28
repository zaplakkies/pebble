from datetime import datetime

from pebble_agent.tracker import Tracker


def sessions(store):
    return [r for r in store.pending() if r['kind'] == 'session']


def duration(rec):
    return (datetime.fromisoformat(rec['end']) - datetime.fromisoformat(rec['start'])).seconds


def run(tracker, clock, seconds, step=5):
    for _ in range(int(seconds // step)):
        clock.advance(step)
        tracker.tick()


def make(store, probe, config, clock):
    return Tracker(store, probe, config, user='emma', clock=clock, mono=clock.mono)


def test_switching_apps_creates_sessions(store, probe, config, clock):
    t = make(store, probe, config, clock)
    probe.show('chrome.exe', 'Video - YouTube', 'https://youtube.com/watch?v=1')
    t.tick()
    run(t, clock, 60)
    probe.show('WINWORD.EXE', 'Essay.docx - Word')
    run(t, clock, 30)
    t.close()
    recs = sessions(store)
    assert [r['app_id'] for r in recs] == ['chrome.exe', 'WINWORD.EXE']
    assert duration(recs[0]) == 65  # until the tick that saw the switch
    assert recs[1]['document'] == 'Essay.docx'
    assert recs[0]['url'] == 'https://youtube.com/watch?v=1'


def test_long_sessions_are_split(store, probe, config, clock):
    t = make(store, probe, config, clock)
    probe.show('javaw.exe', 'Minecraft')
    t.tick()
    run(t, clock, 700)
    t.close()
    recs = sessions(store)
    assert len(recs) == 3
    assert sum(duration(r) for r in recs) == 700
    assert recs[0]['end'] == recs[1]['start']


def test_idle_ends_session_at_last_input(store, probe, config, clock):
    t = make(store, probe, config, clock)
    probe.show('notepad.exe', 'notes.txt - Notepad')
    t.tick()
    run(t, clock, 60)
    for _ in range(30):  # 150 s without input
        clock.advance(5)
        probe.idle += 5
        t.tick()
    recs = sessions(store)
    assert len(recs) == 1 and duration(recs[0]) == 60
    assert t.current is None


def test_video_is_not_idle(store, probe, config, clock):
    t = make(store, probe, config, clock)
    probe.show('chrome.exe', 'Cats - YouTube')
    t.tick()
    for _ in range(60):  # 5 min watching, no input
        clock.advance(5)
        probe.idle += 5
        t.tick()
    t.close()
    assert duration(sessions(store)[0]) == 300


def test_lock_screen_is_not_usage(store, probe, config, clock):
    t = make(store, probe, config, clock)
    probe.show('chrome.exe', 'Page')
    t.tick()
    run(t, clock, 30)
    probe.show('LockApp.exe', 'Windows Default Lock Screen')
    run(t, clock, 60)
    recs = sessions(store)
    assert len(recs) == 1 and duration(recs[0]) == 30


def test_sleep_gap_closes_session(store, probe, config, clock):
    t = make(store, probe, config, clock)
    probe.show('chrome.exe', 'Page')
    t.tick()
    run(t, clock, 30)
    clock.advance(3600)  # laptop lid closed for an hour (monotonic includes sleep on Windows)
    t.tick()
    run(t, clock, 20)
    t.close()
    recs = sessions(store)
    assert [duration(r) for r in recs] == [30, 20]


def test_clock_change_is_reported(store, probe, config, clock):
    t = make(store, probe, config, clock)
    probe.show('chrome.exe', 'Page')
    t.tick()
    run(t, clock, 30)
    clock.wall -= 7200  # kid sets the clock back two hours
    clock.advance(5)
    t.tick()
    events = [r for r in store.pending() if r['kind'] == 'event']
    assert events[0]['type'] == 'clock_jump'
    assert events[0]['details']['delta_s'] == -7200
    assert duration(sessions(store)[0]) == 30


def test_last_alive_is_written(store, probe, config, clock):
    t = make(store, probe, config, clock)
    probe.show('x.exe')
    t.tick()
    run(t, clock, 60)
    assert clock.wall - store.get('last_alive:emma') <= 30
