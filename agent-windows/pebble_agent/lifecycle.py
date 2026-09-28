"""Agent start/stop records, OS power events and "agent wasn't running" detection."""
from dataclasses import dataclass, field

from pebble_agent import __version__
from pebble_agent.tracker import iso


@dataclass(order=True)
class OsEvent:
    at: float
    type: str  # os_boot | os_shutdown | os_sleep | os_resume
    details: dict = field(default_factory=dict, compare=False)


def record_os_events(store, events):
    """Queue OS events newer than the last ones reported. Returns the new ones."""
    after = store.get('os_events_after', 0)
    new = sorted(e for e in events if e.at > after)
    for e in new:
        store.add(kind='event', at=iso(e.at), type=e.type, details=e.details or None)
    if new:
        store.set('os_events_after', new[-1].at)
    return new


def slept_seconds(events, start, end):
    """Seconds between os_sleep and the following os_resume that fall inside [start, end]."""
    total, asleep_at = 0.0, None
    for e in sorted(events):
        if e.type == 'os_sleep':
            asleep_at = e.at
        elif e.type == 'os_resume' and asleep_at is not None:
            total += max(0.0, min(e.at, end) - max(asleep_at, start))
            asleep_at = None
    if asleep_at is not None and asleep_at < end:
        total += end - max(asleep_at, start)
    return total


def record_start(store, config, user, now, boot_time, session_start, os_events):
    """Queue everything that happened while the agent wasn't running, then agent_start.

    session_start is when the current user logged on. If the agent was last alive
    before that, the user logged off or the PC restarted in between (new session).
    """
    record_os_events(store, os_events)
    last_alive = store.get(f'last_alive:{user}')
    new_session = last_alive is None or last_alive < session_start

    if last_alive is not None:
        # Same session: silent since it was last alive. New session: it should have
        # started at logon.
        gap_from = session_start if new_session else last_alive
        slept = slept_seconds(os_events, gap_from, now)
        if now - gap_from - slept >= config.gap_report_s:
            store.add(kind='event', at=iso(now), type='agent_gap',
                      details={'from': iso(gap_from), 'to': iso(now), 'slept_s': int(slept)})

    store.add(kind='event', at=iso(now), type='agent_start',
              details={'version': __version__, 'user': user, 'new_session': new_session,
                       'boot_time': iso(boot_time)})
    store.set(f'last_alive:{user}', now)
    return new_session


def record_stop(store, user, now, reason):
    store.add(kind='event', at=iso(now), type='agent_stop', details={'user': user, 'reason': reason})
    store.set(f'last_alive:{user}', now)
