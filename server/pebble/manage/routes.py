"""Hidden management pages, served under /<MANAGE_PATH>/.

There is no login. Every change is written to the append-only audit log so a
change made without permission is always visible afterwards.
"""
import secrets
from collections import defaultdict
from datetime import date, timedelta

from flask import (Blueprint, abort, flash, redirect, render_template, request, session,
                   url_for)

from pebble import db
from pebble.models import (Adjustment, Alert, AuditLog, Device, DeviceEvent, ExclusionRule, Kid,
                           Session, hash_token)
from pebble.services import record_audit
from pebble.timeutil import local_today, to_local, utc_now
from pebble.usage import summarize_day, summarize_today

manage = Blueprint('manage', __name__)

KID_FIELDS = ('name', 'weekday_limit_min', 'weekend_limit_min')
DEVICE_FIELDS = ('name', 'kid', 'platform', 'active')
RULE_FIELDS = ('kid', 'app_id', 'domain', 'title_pattern', 'reason', 'active')


# ---------------------------------------------------------------- helpers

@manage.before_request
def check_csrf():
    if request.method == 'POST':
        expected = session.get('csrf_token')
        if not expected or request.form.get('csrf_token') != expected:
            abort(400, 'Form expired, go back and reload the page.')


@manage.context_processor
def inject_helpers():
    def csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        return session['csrf_token']
    open_alerts = Alert.query.filter_by(acknowledged=False).count()
    return {'csrf_token': csrf_token, 'open_alerts': open_alerts, 'today': local_today()}


def snapshot(obj, fields):
    out = {}
    for f in fields:
        value = getattr(obj, f)
        out[f] = value.name if isinstance(value, Kid) else value
    return out


def audit_changes(entity, obj, before, fields):
    after = snapshot(obj, fields)
    changed = [f for f in fields if before.get(f) != after.get(f)]
    if changed:
        label = {'name': after.get('name')} if 'name' in fields and 'name' not in changed else {}
        record_audit('update', entity, obj.id, old={**label, **{f: before[f] for f in changed}},
                     new={**label, **{f: after[f] for f in changed}})
    return bool(changed)


def form_text(name, limit=500):
    value = (request.form.get(name) or '').strip()
    return value[:limit] or None


def form_minutes(name):
    """Empty = None (no limit). Accepts minutes ('90') or hours:minutes ('1:30')."""
    raw = (request.form.get(name) or '').strip()
    if not raw:
        return None
    try:
        if ':' in raw:
            hours, minutes = raw.split(':', 1)
            value = int(hours) * 60 + int(minutes)
        else:
            value = int(raw)
    except ValueError:
        raise ValueError(f'"{raw}" is not a number of minutes')
    if not 0 <= value <= 24 * 60:
        raise ValueError('limit must be between 0 and 1440 minutes')
    return value


def form_kid(name='kid_id', allow_all=False):
    raw = request.form.get(name) or ''
    if allow_all and raw in ('', 'all'):
        return None
    kid = db.session.get(Kid, int(raw)) if raw.isdigit() else None
    if kid is None:
        raise ValueError('choose a kid')
    return kid


def get_or_404(model, ident):
    return db.session.get(model, ident) or abort(404)


def parse_day(value, default):
    try:
        return min(date.fromisoformat(value), local_today()) if value else default
    except ValueError:
        abort(400)


# ---------------------------------------------------------------- overview

@manage.route('/')
def overview():
    kids = Kid.query.order_by(Kid.name).all()
    return render_template(
        'manage/overview.html',
        cards=[(kid, summarize_today(kid)) for kid in kids],
        alerts=Alert.query.filter_by(acknowledged=False).order_by(Alert.created_at.desc())
        .limit(8).all(),
        changes=AuditLog.query.order_by(AuditLog.at.desc()).limit(8).all(),
        devices=Device.query.filter_by(active=True).order_by(Device.name).all(),
        sync_stale_after=timedelta(minutes=15), now=utc_now())


# ---------------------------------------------------------------- kids

@manage.route('/kids', methods=['GET', 'POST'])
def kids():
    if request.method == 'POST':
        try:
            name = form_text('name', 60)
            if not name:
                raise ValueError('name is required')
            if Kid.query.filter(Kid.name.ilike(name)).first():
                raise ValueError(f'{name} already exists')
            kid = Kid(name=name, weekday_limit_min=form_minutes('weekday_limit_min'),
                      weekend_limit_min=form_minutes('weekend_limit_min'))
        except ValueError as e:
            flash(str(e).capitalize() + '.', 'error')
            return redirect(url_for('.kids'))
        db.session.add(kid)
        db.session.flush()
        record_audit('create', 'kid', kid.id, new=snapshot(kid, KID_FIELDS))
        db.session.commit()
        flash(f'Added {kid.name}.', 'ok')
        return redirect(url_for('.kids'))
    return render_template('manage/kids.html', kids=Kid.query.order_by(Kid.name).all())


@manage.route('/kids/<int:kid_id>/edit', methods=['GET', 'POST'])
def kid_edit(kid_id):
    kid = get_or_404(Kid, kid_id)
    if request.method == 'POST':
        before = snapshot(kid, KID_FIELDS)
        try:
            name = form_text('name', 60)
            if not name:
                raise ValueError('name is required')
            clash = Kid.query.filter(Kid.name.ilike(name), Kid.id != kid.id).first()
            if clash:
                raise ValueError(f'{name} already exists')
            kid.name = name
            kid.weekday_limit_min = form_minutes('weekday_limit_min')
            kid.weekend_limit_min = form_minutes('weekend_limit_min')
        except ValueError as e:
            db.session.rollback()
            flash(str(e).capitalize() + '.', 'error')
            return redirect(url_for('.kid_edit', kid_id=kid.id))
        if audit_changes('kid', kid, before, KID_FIELDS):
            flash(f'Saved {kid.name}.', 'ok')
        db.session.commit()
        return redirect(url_for('.kids'))
    return render_template('manage/kid_edit.html', kid=kid)


@manage.route('/kids/<int:kid_id>/delete', methods=['POST'])
def kid_delete(kid_id):
    kid = get_or_404(Kid, kid_id)
    if kid.devices or Adjustment.query.filter_by(kid_id=kid.id).first() \
            or ExclusionRule.query.filter_by(kid_id=kid.id).first():
        flash(f'{kid.name} still has devices, adjustments or rules. Remove those first.', 'error')
        return redirect(url_for('.kid_edit', kid_id=kid.id))
    record_audit('delete', 'kid', kid.id, old=snapshot(kid, KID_FIELDS))
    db.session.delete(kid)
    db.session.commit()
    flash(f'Deleted {kid.name}.', 'ok')
    return redirect(url_for('.kids'))


# ---------------------------------------------------------------- kid day: adjustments

@manage.route('/kids/<int:kid_id>/day')
def kid_day(kid_id):
    kid = get_or_404(Kid, kid_id)
    today = local_today()
    day = parse_day(request.args.get('day'), today)
    summary = summarize_day(kid, day)
    session_adjustments = {a.session_id: a for a in Adjustment.query.filter(
        Adjustment.session_id.in_([v.session.id for v in summary.sessions]))}
    minute_adjustments = Adjustment.query.filter_by(kid_id=kid.id, day=day, session_id=None) \
        .order_by(Adjustment.created_at).all()
    return render_template('manage/kid_day.html', kid=kid, summary=summary,
                           session_adjustments=session_adjustments,
                           minute_adjustments=minute_adjustments,
                           prev_day=day - timedelta(days=1),
                           next_day=day + timedelta(days=1) if day < today else None)


@manage.route('/kids/<int:kid_id>/adjust', methods=['POST'])
def kid_adjust(kid_id):
    kid = get_or_404(Kid, kid_id)
    day = parse_day(request.form.get('day'), local_today())
    try:
        minutes = int(request.form.get('minutes', ''))
        if request.form.get('direction') == 'remove':
            minutes = -abs(minutes)
        if minutes == 0 or abs(minutes) > 24 * 60:
            raise ValueError
    except ValueError:
        flash('Enter a number of minutes.', 'error')
        return redirect(url_for('.kid_day', kid_id=kid.id, day=day.isoformat()))
    adj = Adjustment(kid_id=kid.id, day=day, minutes=minutes, reason=form_text('reason', 200))
    db.session.add(adj)
    db.session.flush()
    record_audit('create', 'adjustment', adj.id, new={
        'kid': kid.name, 'day': day.isoformat(), 'minutes': minutes, 'reason': adj.reason})
    db.session.commit()
    action = 'Counted an extra' if minutes > 0 else 'Gave back'
    flash(f'{action} {abs(minutes)} min for {kid.name}.', 'ok')
    return redirect(url_for('.kid_day', kid_id=kid.id, day=day.isoformat()))


@manage.route('/sessions/<int:session_id>/exclude', methods=['POST'])
def session_exclude(session_id):
    s = get_or_404(Session, session_id)
    kid = s.device.kid
    back = url_for('.kid_day', kid_id=kid.id, day=request.form.get('day'))
    if Adjustment.query.filter_by(session_id=s.id).first():
        return redirect(back)
    adj = Adjustment(kid_id=kid.id, day=to_local(s.start).date(), session_id=s.id,
                     reason=form_text('reason', 200) or 'Excluded by parent')
    db.session.add(adj)
    db.session.flush()
    record_audit('create', 'adjustment', adj.id, new={
        'kid': kid.name, 'excluded_session': f'{s.display_name} {to_local(s.start):%Y-%m-%d %H:%M}'
        f'–{to_local(s.end):%H:%M}', 'reason': adj.reason})
    db.session.commit()
    return redirect(back)


@manage.route('/adjustments/<int:adj_id>/delete', methods=['POST'])
def adjustment_delete(adj_id):
    adj = get_or_404(Adjustment, adj_id)
    old = {'kid': adj.kid.name, 'day': adj.day.isoformat(), 'reason': adj.reason}
    if adj.session_id:
        s = adj.session
        old['excluded_session'] = f'{s.display_name} {to_local(s.start):%Y-%m-%d %H:%M}'
    else:
        old['minutes'] = adj.minutes
    record_audit('delete', 'adjustment', adj.id, old=old)
    kid_id = adj.kid_id
    db.session.delete(adj)
    db.session.commit()
    return redirect(url_for('.kid_day', kid_id=kid_id, day=request.form.get('day')))


# ---------------------------------------------------------------- devices

def _show_token(device, token, message):
    record_audit('update' if message == 'regenerated' else 'create', 'device', device.id,
                 new={**snapshot(device, DEVICE_FIELDS), 'token': message})
    db.session.commit()
    return render_template('manage/device_token.html', device=device, token=token,
                           server_url=request.host_url.rstrip('/'))


@manage.route('/devices', methods=['GET', 'POST'])
def devices():
    if request.method == 'POST':
        try:
            kid = form_kid()
            name = form_text('name', 60)
            platform = request.form.get('platform')
            if not name:
                raise ValueError('device name is required')
            if platform not in ('windows', 'android'):
                raise ValueError('choose a platform')
        except ValueError as e:
            flash(str(e).capitalize() + '.', 'error')
            return redirect(url_for('.devices'))
        token = Device.new_token()
        device = Device(kid=kid, name=name, platform=platform, token_hash=hash_token(token))
        db.session.add(device)
        db.session.flush()
        return _show_token(device, token, 'issued')
    return render_template('manage/devices.html',
                           devices=Device.query.order_by(Device.active.desc(), Device.name).all(),
                           kids=Kid.query.order_by(Kid.name).all(), now=utc_now())


@manage.route('/devices/<int:device_id>', methods=['GET', 'POST'])
def device_edit(device_id):
    device = get_or_404(Device, device_id)
    if request.method == 'POST':
        before = snapshot(device, DEVICE_FIELDS)
        try:
            device.kid = form_kid()
            device.name = form_text('name', 60) or device.name
        except ValueError as e:
            db.session.rollback()
            flash(str(e).capitalize() + '.', 'error')
            return redirect(url_for('.device_edit', device_id=device.id))
        if audit_changes('device', device, before, DEVICE_FIELDS):
            flash(f'Saved {device.name}.', 'ok')
        db.session.commit()
        return redirect(url_for('.devices'))
    events = DeviceEvent.query.filter_by(device_id=device.id) \
        .order_by(DeviceEvent.at.desc()).limit(30).all()
    return render_template('manage/device_edit.html', device=device, events=events,
                           kids=Kid.query.order_by(Kid.name).all())


@manage.route('/devices/<int:device_id>/active', methods=['POST'])
def device_active(device_id):
    device = get_or_404(Device, device_id)
    before = snapshot(device, DEVICE_FIELDS)
    device.active = request.form.get('active') == '1'
    audit_changes('device', device, before, DEVICE_FIELDS)
    db.session.commit()
    flash(f'{device.name} {"re-enabled" if device.active else "revoked; its token no longer works"}.',
          'ok')
    return redirect(url_for('.device_edit', device_id=device.id))


@manage.route('/devices/<int:device_id>/token', methods=['POST'])
def device_token(device_id):
    device = get_or_404(Device, device_id)
    token = Device.new_token()
    device.token_hash = hash_token(token)
    # A fresh token means a fresh agent setup, so don't flag the new install as tampering.
    device.install_id, device.last_seq, device.last_hash = None, 0, None
    device.active = True
    return _show_token(device, token, 'regenerated')


# ---------------------------------------------------------------- exclusion rules

def _usage_last_week():
    since = utc_now() - timedelta(days=7)
    return Session.query.join(Device).filter(Session.end > since).all()


def _rule_from_form(rule):
    rule.kid = form_kid(allow_all=True)
    rule.app_id = form_text('app_id', 200)
    rule.domain = (form_text('domain', 255) or '').lower().removeprefix('www.') or None
    rule.title_pattern = form_text('title_pattern', 500)
    rule.reason = form_text('reason', 200)
    rule.active = request.form.get('active', '1') == '1'
    if not (rule.app_id or rule.domain or rule.title_pattern):
        raise ValueError('fill in at least one of app, website or title pattern')


@manage.route('/rules', methods=['GET', 'POST'])
def rules():
    if request.method == 'POST':
        rule = ExclusionRule()
        try:
            _rule_from_form(rule)
        except ValueError as e:
            flash(str(e).capitalize() + '.', 'error')
            prefill = {k: v for k, v in request.form.items() if k != 'csrf_token'}
            return redirect(url_for('.rules', **prefill) + '#new')
        db.session.add(rule)
        db.session.flush()
        record_audit('create', 'rule', rule.id, new=snapshot(rule, RULE_FIELDS))
        db.session.commit()
        flash('Rule added. Past days are recalculated automatically.', 'ok')
        return redirect(url_for('.rules'))

    all_rules = ExclusionRule.query.order_by(ExclusionRule.active.desc(),
                                             ExclusionRule.created_at).all()
    sessions = _usage_last_week()
    matched = defaultdict(int)
    apps, domains = defaultdict(int), defaultdict(int)
    app_names = {}
    for s in sessions:
        secs = int((s.end - s.start).total_seconds())
        apps[s.app_id] += secs
        app_names.setdefault(s.app_id, s.display_name)
        if s.domain:
            domains[s.domain] += secs
        for r in all_rules:
            if (r.kid_id is None or r.kid_id == s.device.kid_id) and r.matches(s):
                matched[r.id] += secs
    return render_template(
        'manage/rules.html', rules=all_rules, matched=matched,
        kids=Kid.query.order_by(Kid.name).all(), prefill=request.args,
        top_apps=sorted(apps.items(), key=lambda kv: -kv[1])[:12], app_names=app_names,
        top_domains=sorted(domains.items(), key=lambda kv: -kv[1])[:12])


@manage.route('/rules/<int:rule_id>', methods=['GET', 'POST'])
def rule_edit(rule_id):
    rule = get_or_404(ExclusionRule, rule_id)
    if request.method == 'POST':
        before = snapshot(rule, RULE_FIELDS)
        try:
            _rule_from_form(rule)
        except ValueError as e:
            db.session.rollback()
            flash(str(e).capitalize() + '.', 'error')
            return redirect(url_for('.rule_edit', rule_id=rule.id))
        if audit_changes('rule', rule, before, RULE_FIELDS):
            flash('Rule saved.', 'ok')
        db.session.commit()
        return redirect(url_for('.rules'))
    return render_template('manage/rule_edit.html', rule=rule,
                           kids=Kid.query.order_by(Kid.name).all())


@manage.route('/rules/<int:rule_id>/delete', methods=['POST'])
def rule_delete(rule_id):
    rule = get_or_404(ExclusionRule, rule_id)
    record_audit('delete', 'rule', rule.id, old=snapshot(rule, RULE_FIELDS))
    db.session.delete(rule)
    db.session.commit()
    flash('Rule deleted.', 'ok')
    return redirect(url_for('.rules'))


# ---------------------------------------------------------------- alerts and audit log

@manage.route('/alerts')
def alerts():
    show_all = request.args.get('show') == 'all'
    query = Alert.query if show_all else Alert.query.filter_by(acknowledged=False)
    return render_template('manage/alerts.html', show_all=show_all,
                           alerts=query.order_by(Alert.created_at.desc()).limit(300).all())


@manage.route('/alerts/ack', methods=['POST'])
def alerts_ack():
    ids = request.form.getlist('alert_id', type=int)
    query = Alert.query.filter_by(acknowledged=False)
    if ids:
        query = query.filter(Alert.id.in_(ids))
    acked = query.all()
    for a in acked:
        a.acknowledged = True
    if acked:
        record_audit('update', 'alert', acked[0].id if len(acked) == 1 else None,
                     old={'acknowledged': False},
                     new={'acknowledged': True, 'alerts': [f'{a.kind} #{a.id}' for a in acked]})
    db.session.commit()
    return redirect(url_for('.alerts'))


@manage.route('/audit')
def audit():
    page = AuditLog.query.order_by(AuditLog.at.desc(), AuditLog.id.desc()) \
        .paginate(per_page=50, error_out=False)
    return render_template('manage/audit.html', page=page)
