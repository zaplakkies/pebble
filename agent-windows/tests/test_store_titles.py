from pebble_agent import titles
from pebble_agent.store import canonical_hash


def test_records_form_a_hash_chain(store):
    a = store.add(kind='event', at='2026-09-28T10:00:00+02:00', type='agent_start')
    b = store.add(kind='event', at='2026-09-28T10:01:00+02:00', type='agent_stop')
    assert (a['seq'], b['seq']) == (1, 2)
    assert a['prev_hash'] is None and b['prev_hash'] == a['hash']
    assert a['hash'] == canonical_hash(a)
    assert [r['seq'] for r in store.pending()] == [1, 2]


def test_acknowledge_keeps_sequence_going(store, tmp_path):
    store.add(kind='event', at='x', type='agent_start')
    store.acknowledge(1)
    assert store.pending() == []
    assert store.add(kind='event', at='y', type='agent_stop')['seq'] == 2


def test_state_survives_reopen(tmp_path):
    from pebble_agent.store import Store
    s = Store(tmp_path / 'q.db')
    install_id = s.install_id
    s.add(kind='event', at='x', type='agent_start')
    s.close()
    s = Store(tmp_path / 'q.db')
    assert s.install_id == install_id
    assert s.add(kind='event', at='y', type='agent_stop')['seq'] == 2


def test_document_names():
    assert titles.document_name('WINWORD.EXE', 'Essay.docx - Word') == 'Essay.docx'
    assert titles.document_name('WINWORD.EXE', 'Essay - Compatibility Mode - Word') == 'Essay'
    assert titles.document_name('EXCEL.EXE', 'Marks.xlsx - Excel') == 'Marks.xlsx'
    assert titles.document_name('notepad.exe', '*notes.txt - Notepad') == 'notes.txt'
    assert titles.document_name('Code.exe', '● main.py - pebble - Visual Studio Code') == 'main.py'
    assert titles.document_name('chrome.exe', 'Essay - Google Docs') == 'Essay'
    assert titles.document_name('chrome.exe', 'report.pdf - Google Chrome') is None
    assert titles.document_name('javaw.exe', 'Minecraft 1.21') is None


def test_browser_titles_and_urls():
    assert titles.strip_browser_suffix('Video - YouTube - Google Chrome') == 'Video - YouTube'
    assert titles.strip_browser_suffix('Page - Personal - Microsoft​ Edge') == 'Page - Personal'
    assert titles.normalize_url('youtube.com/watch?v=1') == 'https://youtube.com/watch?v=1'
    assert titles.normalize_url('https://x.org/') == 'https://x.org/'
    assert titles.normalize_url('how to draw a cat') is None
    assert titles.normalize_url('') is None
    assert titles.domain_of('https://www.youtube.com/x') == 'youtube.com'


def test_friendly_names():
    assert titles.friendly_name('chrome.exe') == 'Google Chrome'
    assert titles.friendly_name('RobloxPlayerBeta.exe') == 'Roblox'
    assert titles.friendly_name('game.exe') == 'Game'
    assert titles.friendly_name('x.exe', 'Fancy Game') == 'Fancy Game'


def test_exclusion_matching_matches_server_rules():
    rules = [{'app_id': 'WINWORD.EXE'}, {'domain': 'google.com'}, {'title_pattern': '*maths*'}]
    assert titles.excluded(rules, 'winword.exe', None, None)
    assert titles.excluded(rules, 'chrome.exe', None, 'https://classroom.google.com/c/1')
    assert not titles.excluded(rules, 'chrome.exe', None, 'https://notgoogle.com/')
    assert titles.excluded(rules, 'x.exe', 'Grade 7 Maths', None)
    assert not titles.excluded([{}], 'x.exe', 'y', None)


EVENT_XML = """<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><Provider Name='Microsoft-Windows-Kernel-Power' Guid='{331c3b3a-2005-44c2-ac5e-77220c37d6b4}'/><EventID>42</EventID><Version>6</Version><Level>4</Level><Task>64</Task><TimeCreated SystemTime='2026-09-28T13:05:10.1234567Z'/><Channel>System</Channel><Computer>KIDS-PC</Computer></System><EventData><Data Name='TargetState'>4</Data></EventData></Event><Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><Provider Name='Microsoft-Windows-Power-Troubleshooter' Guid='{cdc05e28-c449-49c6-b9d2-88cf761644df}' EventSourceName='Microsoft-Windows-Power-Troubleshooter'/><EventID Qualifiers='0'>1</EventID><TimeCreated SystemTime='2026-09-28T14:00:00.0000000Z'/></System></Event><Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><Provider Name='EventLog'/><EventID Qualifiers='32768'>6008</EventID><TimeCreated SystemTime='2026-09-28T07:00:01.5Z'/></System></Event><Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><Provider Name='Some-Other'/><EventID>1</EventID><TimeCreated SystemTime='2026-09-28T07:00:01Z'/></System></Event>"""


def test_parse_event_log():
    from datetime import datetime, timezone
    from pebble_agent import eventlog
    events = eventlog.parse(EVENT_XML)
    assert [(e.type, e.details) for e in events] == [
        ('os_shutdown', {'unexpected': True}), ('os_sleep', {}), ('os_resume', {})]
    assert events[1].at == datetime(2026, 9, 28, 13, 5, 10, 123456, tzinfo=timezone.utc).timestamp()
