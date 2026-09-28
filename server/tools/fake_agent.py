#!/usr/bin/env python3
"""Fake Pebble agent: sends made-up usage to the server for testing.

Also a reference for real agents: see make_record() for sequence numbers and
the hash chain. Standard library only.

    python tools/fake_agent.py --token TOKEN --minutes 90
    python tools/fake_agent.py --token TOKEN --platform android --minutes 45
    python tools/fake_agent.py --token TOKEN --tamper gap      # simulate deleted records
"""
import argparse
import hashlib
import json
import random
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

WINDOWS_APPS = [
    ('chrome.exe', 'Google Chrome', [
        ('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'Minecraft 100 days - YouTube - Google Chrome'),
        ('https://www.roblox.com/games/920587237', 'Adopt Me! - Roblox - Google Chrome'),
        ('https://classroom.google.com/c/NjI', 'Grade 7 Maths - Google Classroom - Google Chrome'),
        ('https://en.wikipedia.org/wiki/Volcano', 'Volcano - Wikipedia - Google Chrome'),
    ]),
    ('msedge.exe', 'Microsoft Edge', [
        ('https://www.coolmathgames.com/0-run', 'Run - Cool Math Games - Microsoft Edge'),
    ]),
    ('WINWORD.EXE', 'Microsoft Word', [(None, 'Volcano project.docx - Word'),
                                       (None, 'Book report.docx - Word')]),
    ('javaw.exe', 'Minecraft', [(None, 'Minecraft 1.21')]),
    ('Discord.exe', 'Discord', [(None, '#general | Friends - Discord')]),
]
ANDROID_APPS = [
    ('com.google.android.youtube', 'YouTube', [(None, None)]),
    ('com.roblox.client', 'Roblox', [(None, None)]),
    ('com.whatsapp', 'WhatsApp', [(None, None)]),
    ('com.zhiliaoapp.musically', 'TikTok', [(None, None)]),
    ('com.android.chrome', 'Chrome', [('https://www.google.com/search?q=dogs', None)]),
]


def canonical_hash(record):
    body = {k: v for k, v in record.items() if k != 'hash'}
    canonical = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Agent:
    def __init__(self, state_path):
        self.state_path = state_path
        if state_path.exists():
            self.state = json.loads(state_path.read_text())
        else:
            self.state = {'install_id': str(uuid.uuid4()), 'seq': 0, 'last_hash': None}

    def save(self):
        self.state_path.write_text(json.dumps(self.state, indent=2))

    def make_record(self, **fields):
        self.state['seq'] += 1
        record = {'seq': self.state['seq'], 'id': str(uuid.uuid4()),
                  'prev_hash': self.state['last_hash'], **fields}
        record['hash'] = canonical_hash(record)
        self.state['last_hash'] = record['hash']
        return record


def iso(dt):
    return dt.astimezone().isoformat(timespec='seconds')


def build_sessions(agent, platform, minutes):
    apps = WINDOWS_APPS if platform == 'windows' else ANDROID_APPS
    now = datetime.now().astimezone()
    t = now - timedelta(minutes=minutes)
    records = [agent.make_record(kind='event', at=iso(t - timedelta(seconds=5)),
                                 type='agent_start', details={'version': 'fake'})]
    while t < now:
        app_id, app_name, variants = random.choice(apps)
        url, title = random.choice(variants)
        length = timedelta(minutes=random.randint(2, 20), seconds=random.randint(0, 59))
        end = min(t + length, now)
        document = title.rsplit(' - ', 1)[0] if title and title.endswith(' - Word') else None
        records.append(agent.make_record(
            kind='session', start=iso(t), end=iso(end), app_id=app_id, app_name=app_name,
            title=title, url=url, document=document))
        t = end + timedelta(seconds=random.randint(0, 90))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--server', default='http://127.0.0.1:5000')
    parser.add_argument('--token', required=True)
    parser.add_argument('--platform', choices=['windows', 'android'], default='windows')
    parser.add_argument('--minutes', type=int, default=60, help='minutes of activity ending now')
    parser.add_argument('--tamper', choices=['gap', 'modify', 'clock', 'reinstall'])
    args = parser.parse_args()

    state_path = Path(__file__).parent / f'.fake_agent_{args.token[:8]}.json'
    if args.tamper == 'reinstall' and state_path.exists():
        state_path.unlink()
    agent = Agent(state_path)
    if args.tamper == 'gap':
        agent.state['seq'] += 3  # as if three records were deleted before sending

    records = build_sessions(agent, args.platform, args.minutes)
    if args.tamper == 'modify':
        records[-1]['end'] = iso(datetime.now() - timedelta(minutes=1, seconds=1))
    device_time = datetime.now().astimezone()
    if args.tamper == 'clock':
        device_time -= timedelta(hours=1)

    body = json.dumps({'agent_version': 'fake-0.1', 'device_time': iso(device_time),
                       'records': records}).encode()
    request = urllib.request.Request(
        args.server.rstrip('/') + '/api/v1/sync', data=body, method='POST',
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {args.token}',
                 'X-Pebble-Install-Id': agent.state['install_id']})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
    except urllib.error.HTTPError as e:
        sys.exit(f'Server said {e.code}: {e.read().decode()}')
    except urllib.error.URLError as e:
        sys.exit(f'Could not reach server: {e.reason}')

    agent.save()
    today = result['today']
    print(f"Sent {len(records)} records, server accepted through #{result['accepted_through_seq']}.")
    if result.get('rejected'):
        print(f"Rejected: {result['rejected']}")
    print(f"Today: {today['used_s'] // 60} min used, limit "
          f"{today['limit_s'] // 60 if today['limit_s'] is not None else 'none'} min, {today['status']}.")


if __name__ == '__main__':
    main()
