from pebble.timeutil import to_local, utc_now


def duration(seconds):
    if seconds is None:
        return '–'
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m' if hours else f'{minutes}m'


def localtime(dt_utc, fmt='%H:%M'):
    return to_local(dt_utc).strftime(fmt) if dt_utc else ''


def ago(dt_utc):
    if dt_utc is None:
        return 'never'
    minutes = int((utc_now() - dt_utc).total_seconds() // 60)
    if minutes < 1:
        return 'just now'
    if minutes < 60:
        return f'{minutes} min ago'
    if minutes < 48 * 60:
        return f'{minutes // 60} h ago'
    return f'{minutes // 1440} days ago'


def register_filters(app):
    app.jinja_env.filters.update(duration=duration, localtime=localtime, ago=ago)
