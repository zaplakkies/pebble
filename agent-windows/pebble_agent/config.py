"""Locations and configuration.

On Windows everything lives under C:\\ProgramData\\Pebble:
    config.json   server URL + device token (admins write, users read)
    data\\         local queue database (users write; tampering shows as alerts)
Set PEBBLE_AGENT_HOME to use another folder (development and tests).
"""
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = sys.platform == 'win32'
INSTALL_DIR = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Pebble'


def home():
    if os.environ.get('PEBBLE_AGENT_HOME'):
        return Path(os.environ['PEBBLE_AGENT_HOME'])
    if IS_WINDOWS:
        return Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'Pebble'
    return Path.home() / '.pebble-agent'


def config_path():
    return home() / 'config.json'


def data_dir():
    return home() / 'data'


def log_path():
    # Per-user log so each account's agent can write it.
    if IS_WINDOWS and os.environ.get('LOCALAPPDATA'):
        return Path(os.environ['LOCALAPPDATA']) / 'Pebble' / 'agent.log'
    return home() / 'agent.log'


@dataclass
class Config:
    server: str
    token: str
    # Windows accounts to track (case-insensitive). Empty = everyone who logs on.
    track_users: list = field(default_factory=list)
    sample_interval_s: float = 5
    idle_after_s: int = 120
    # Fullscreen or video windows stay "in use" without input for this long.
    video_idle_after_s: int = 30 * 60
    max_session_s: int = 300
    # Minimum silence (minus sleep) reported as an agent_gap.
    gap_report_s: int = 10 * 60

    @classmethod
    def load(cls, path=None):
        path = Path(path or config_path())
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise SystemExit(f'No config at {path}. Run: pebble-agent install --server URL --token TOKEN')
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path=None):
        path = Path(path or config_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'server': self.server, 'token': self.token,
                                    'track_users': self.track_users}, indent=2),
                        encoding='utf-8')

    def tracks(self, user):
        return not self.track_users or user.lower() in {u.lower() for u in self.track_users}

    @property
    def base_url(self):
        return self.server.rstrip('/')
