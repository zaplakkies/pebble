from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (Blueprint, abort, current_app, jsonify, render_template, request,
                   send_from_directory)

from pebble import db
from pebble.models import AuditLog, Kid
from pebble.timeutil import local_now, local_today, utc_now
from pebble.usage import history, summarize_day, summarize_today

main = Blueprint('main', __name__)


@main.route('/')
def index():
    kids = Kid.query.order_by(Kid.name).all()
    cards = [(kid, summarize_today(kid)) for kid in kids]
    last_change = AuditLog.query.order_by(AuditLog.at.desc()).first()
    return render_template('main/index.html', cards=cards, today=local_today(),
                           last_change=last_change)


@main.route('/board.json')
def board():
    """The dashboard as JSON, for the e-paper display. Read-only, like the dashboard itself."""
    now, utc = local_now(), utc_now()
    kids = []
    for kid in Kid.query.order_by(Kid.name).all():
        today = summarize_today(kid)
        devices = [{'name': d.name, 'platform': d.platform,
                    'last_seen_s': None if d.last_seen is None
                    else max(0, int((utc - d.last_seen).total_seconds()))}
                   for d in sorted(kid.devices, key=lambda d: d.id) if d.active]
        kids.append({'name': kid.name, **today.as_api_dict(), 'devices': devices})
    return jsonify(date=now.strftime('%a %d %b'), time=now.strftime('%H:%M'), kids=kids)


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


APK_TYPE = 'application/vnd.android.package-archive'


@main.route('/downloads')
def downloads():
    folder = Path(current_app.config['DOWNLOADS_DIR'])
    files = []
    if folder.is_dir():
        for f in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.is_file() and not f.name.startswith('.'):
                st = f.stat()
                files.append({'name': f.name, 'size_mb': st.st_size / 1_048_576,
                              'modified': datetime.fromtimestamp(st.st_mtime)})
    return render_template('main/downloads.html', files=files, today=local_today(),
                           server_url=request.host_url.rstrip('/'))


@main.route('/downloads/<path:name>')
def download_file(name):
    # Android only offers to install an APK served with its own media type.
    mimetype = APK_TYPE if name.lower().endswith('.apk') else None
    return send_from_directory(current_app.config['DOWNLOADS_DIR'], name, as_attachment=True,
                               mimetype=mimetype)
