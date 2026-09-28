"""Turns foreground-window samples into session records.

A session is a stretch of one app + window title + URL in the foreground while
the user is active. Sessions end on a switch, idle, lock or sleep, and are
split every `max_session_s` so the server sees ongoing use promptly.
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from pebble_agent import titles

log = logging.getLogger(__name__)

# Wall clock and monotonic clock disagreeing by more than this = someone changed the time.
CLOCK_JUMP_S = 90
ALIVE_EVERY_S = 30


def iso(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec='seconds')


@dataclass
class Sample:
    app_id: str
    app_name: str
    title: str | None = None
    url: str | None = None
    fullscreen: bool = False


@dataclass
class OpenSession:
    sample: Sample
    start: float
    last: float
    key: tuple = field(init=False)

    def __post_init__(self):
        self.key = (self.sample.app_id.lower(), self.sample.title, self.sample.url)


class Tracker:
    def __init__(self, store, probe, config, user='user', clock=time.time, mono=time.monotonic):
        self.store, self.probe, self.config, self.user = store, probe, config, user
        self.clock, self.mono = clock, mono
        self.current = None
        self._prev = None
        self._alive_written = 0

    @property
    def alive_key(self):
        return f'last_alive:{self.user}'

    def tick(self):
        now, mono = self.clock(), self.mono()
        if self._prev:
            prev_wall, prev_mono = self._prev
            drift = (now - prev_wall) - (mono - prev_mono)
            if abs(drift) > CLOCK_JUMP_S:
                self.close()
                self.store.add(kind='event', at=iso(now), type='clock_jump',
                               details={'delta_s': int(drift)})
                log.warning('Clock changed by %+d s', drift)
            elif now - prev_wall > self.config.sample_interval_s * 3 + 10:
                self.close()  # asleep or suspended in between: end at the last active sample
        self._prev = (now, mono)

        sample = self._usable_sample(now)
        if sample is None:
            pass
        elif self.current and self.current.key == self._key(sample) \
                and now - self.current.start < self.config.max_session_s:
            self.current.last = now
        else:
            if self.current:
                self._emit(self.current, end=now)
            self.current = OpenSession(sample, start=now, last=now)

        if now - self._alive_written >= ALIVE_EVERY_S:
            self.store.set(self.alive_key, now)
            self._alive_written = now

    def close(self, end=None):
        """End the open session (at its last active sample unless `end` is given)."""
        if self.current:
            self._emit(self.current, end=self.current.last if end is None else end)
            self.current = None

    def _usable_sample(self, now):
        try:
            sample = self.probe.sample()
            idle = self.probe.idle_seconds()
        except Exception:
            log.exception('Sampling failed')
            sample, idle = None, 0
        if sample is None or sample.app_id.lower() in titles.NOT_USAGE:
            self.close()
            return None
        limit = self.config.video_idle_after_s \
            if sample.fullscreen or titles.looks_like_video(sample.app_id, sample.title) \
            else self.config.idle_after_s
        if idle >= limit:
            if self.current:
                self.close(end=max(self.current.start, min(self.current.last, now - idle)))
            return None
        return sample

    @staticmethod
    def _key(sample):
        return (sample.app_id.lower(), sample.title, sample.url)

    def _emit(self, session, end):
        if end - session.start < 1:
            return
        s = session.sample
        self.store.add(kind='session', start=iso(session.start), end=iso(end),
                       app_id=s.app_id, app_name=s.app_name, title=s.title, url=s.url,
                       document=titles.document_name(s.app_id, s.title))
