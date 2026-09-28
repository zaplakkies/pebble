"""Daily screen-time calculation.

Raw sessions are never changed. Exclusion rules and adjustments are applied
here, every time a day is summarised, so editing a rule also corrects history.
Time on several devices at once counts once (union of intervals).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from flask import current_app

from pebble.models import Adjustment, Device, ExclusionRule, Session
from pebble.timeutil import day_bounds_utc, local_today


@dataclass
class SessionView:
    session: Session
    seconds: int
    excluded_reason: str | None = None


@dataclass
class DaySummary:
    day: date
    used_s: int
    limit_s: int | None
    status: str
    excluded_s: int = 0
    adjust_s: int = 0
    sessions: list = field(default_factory=list)
    by_app: list = field(default_factory=list)       # [(name, seconds)] counted time only
    by_domain: list = field(default_factory=list)
    documents: list = field(default_factory=list)

    @property
    def remaining_s(self):
        return None if self.limit_s is None else max(0, self.limit_s - self.used_s)

    @property
    def percent(self):
        if not self.limit_s:
            return 0
        return min(100, round(100 * self.used_s / self.limit_s))

    def as_api_dict(self):
        return {'date': self.day.isoformat(), 'used_s': self.used_s,
                'limit_s': self.limit_s, 'status': self.status}


def status_for(used_s, limit_s):
    if limit_s is None:
        return 'under'
    if used_s >= limit_s:
        return 'over'
    if used_s >= limit_s * current_app.config['NEAR_LIMIT_RATIO']:
        return 'near'
    return 'under'


def union_seconds(intervals):
    total, cur_start, cur_end = 0, None, None
    for start, end in sorted(intervals):
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += (cur_end - cur_start).total_seconds()
    return int(total)


def active_rules(kid):
    return ExclusionRule.query.filter(
        ExclusionRule.active.is_(True),
        (ExclusionRule.kid_id.is_(None)) | (ExclusionRule.kid_id == kid.id)).all()


def summarize_day(kid, day):
    day_start, day_end = day_bounds_utc(day)
    sessions = (Session.query.join(Device)
                .filter(Device.kid_id == kid.id, Session.start < day_end, Session.end > day_start)
                .order_by(Session.start).all())
    rules = active_rules(kid)
    adjustments = Adjustment.query.filter_by(kid_id=kid.id, day=day).all()
    excluded_sessions = {a.session_id: a.reason or 'Excluded by parent'
                         for a in adjustments if a.session_id}
    adjust_s = sum((a.minutes or 0) * 60 for a in adjustments if not a.session_id)

    views, counted, excluded_s = [], [], 0
    by_app, by_domain, documents = defaultdict(int), defaultdict(int), defaultdict(int)
    for s in sessions:
        start, end = max(s.start, day_start), min(s.end, day_end)
        seconds = int((end - start).total_seconds())
        reason = excluded_sessions.get(s.id)
        if reason is None:
            rule = next((r for r in rules if r.matches(s)), None)
            if rule:
                reason = rule.reason or 'Excluded app'
        views.append(SessionView(s, seconds, reason))
        if reason:
            excluded_s += seconds
            continue
        counted.append((start, end))
        by_app[s.display_name] += seconds
        if s.domain:
            by_domain[s.domain] += seconds
        if s.document:
            documents[s.document] += seconds

    used_s = max(0, union_seconds(counted) + adjust_s)
    limit_min = kid.limit_min_for(day)
    limit_s = None if limit_min is None else limit_min * 60

    def ranked(d):
        return sorted(d.items(), key=lambda kv: kv[1], reverse=True)

    return DaySummary(day=day, used_s=used_s, limit_s=limit_s, status=status_for(used_s, limit_s),
                      excluded_s=excluded_s, adjust_s=adjust_s, sessions=views,
                      by_app=ranked(by_app), by_domain=ranked(by_domain),
                      documents=ranked(documents))


def summarize_today(kid):
    return summarize_day(kid, local_today())


def history(kid, days=7, end_day=None):
    end_day = end_day or local_today()
    return [summarize_day(kid, end_day - timedelta(days=i)) for i in range(days - 1, -1, -1)]
