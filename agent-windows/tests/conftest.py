import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pebble_agent.config import Config  # noqa: E402
from pebble_agent.store import Store  # noqa: E402
from pebble_agent.tracker import Sample  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / 'queue.db')
    yield s
    s.close()


@pytest.fixture
def config():
    return Config(server='http://pebble.test', token='t', sample_interval_s=5,
                  idle_after_s=120, video_idle_after_s=1800, max_session_s=300,
                  gap_report_s=600)


class Clock:
    """Wall and monotonic clock that tests move by hand."""

    def __init__(self, start=1_790_000_000.0):
        self.wall, self.mono_value = start, 1000.0

    def __call__(self):
        return self.wall

    def mono(self):
        return self.mono_value

    def advance(self, seconds):
        self.wall += seconds
        self.mono_value += seconds


@pytest.fixture
def clock():
    return Clock()


class Probe:
    def __init__(self):
        self.current = None
        self.idle = 0.0

    def show(self, app_id, title=None, url=None, fullscreen=False, app_name=None):
        self.current = Sample(app_id, app_name or app_id, title, url, fullscreen)
        self.idle = 0.0

    def sample(self):
        return self.current

    def idle_seconds(self):
        return self.idle


@pytest.fixture
def probe():
    return Probe()
