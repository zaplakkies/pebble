from datetime import date, timedelta

from flask import Blueprint, abort, render_template, request

from pebble import db
from pebble.models import AuditLog, Kid
from pebble.timeutil import local_today
from pebble.usage import history, summarize_day, summarize_today

main = Blueprint('main', __name__)


@main.route('/')
def index():
    kids = Kid.query.order_by(Kid.name).all()
    cards = [(kid, summarize_today(kid)) for kid in kids]
    last_change = AuditLog.query.order_by(AuditLog.at.desc()).first()
    return render_template('main/index.html', cards=cards, today=local_today(),
                           last_change=last_change)


@main.route('/kid/<int:kid_id>')
def kid(kid_id):
    kid = db.session.get(Kid, kid_id) or abort(404)
    today = local_today()
    try:
        day = date.fromisoformat(request.args['day']) if 'day' in request.args else today
    except ValueError:
        abort(400)
    day = min(day, today)
    summary = summarize_day(kid, day)
    week = history(kid, days=7, end_day=day)
    # 10% headroom so a limit line at the maximum is still visible
    week_max = 1.1 * max([s.used_s for s in week] + [s.limit_s or 0 for s in week] + [1])
    return render_template('main/kid.html', kid=kid, summary=summary, week=week,
                           week_max=week_max, today=today,
                           prev_day=day - timedelta(days=1),
                           next_day=day + timedelta(days=1) if day < today else None)
