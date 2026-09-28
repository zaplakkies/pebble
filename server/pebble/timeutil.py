"""Time helpers.

The database stores naive UTC datetimes. Everything shown to people, and the
definition of "today", uses the server's local timezone.
"""
import os
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app


def _system_tz_name():
    localtime = os.path.realpath('/etc/localtime')
    if '/zoneinfo/' in localtime:
        return localtime.split('/zoneinfo/', 1)[1]
    try:
        return Path('/etc/timezone').read_text().strip() or 'UTC'
    except OSError:
        return 'UTC'


@lru_cache(maxsize=8)
def _zone(name):
    return ZoneInfo(name or _system_tz_name())


def local_tz():
    return _zone(current_app.config.get('TIMEZONE', ''))


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_timestamp(value):
    """Parse an ISO-8601 string to naive UTC. Naive input is taken as server local time."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def to_local(dt_utc):
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(local_tz())


def local_now():
    return datetime.now(local_tz())


def local_today():
    return local_now().date()


def day_bounds_utc(day: date):
    """Naive UTC [start, end) of a local calendar day (DST-safe)."""
    tz = local_tz()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return (start.astimezone(timezone.utc).replace(tzinfo=None),
            end.astimezone(timezone.utc).replace(tzinfo=None))
