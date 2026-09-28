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


def auditval(value):
    if value is None or value == '':
        return '—'
    if value is True:
        return 'yes'
    if value is False:
        return 'no'
    if isinstance(value, list):
        return ', '.join(str(v) for v in value)
    return value


def browser(user_agent):
    """Short 'Browser on OS' label so you can tell which device made a change."""
    if not user_agent:
        return ''
    ua = user_agent.lower()
    os_name = next((name for key, name in (('android', 'Android'), ('iphone', 'iPhone'),
                                           ('ipad', 'iPad'), ('windows', 'Windows'),
                                           ('mac os', 'Mac'), ('cros', 'Chromebook'),
                                           ('linux', 'Linux')) if key in ua), '')
    name = next((name for key, name in (('edg/', 'Edge'), ('opr/', 'Opera'),
                                        ('firefox', 'Firefox'), ('chrome', 'Chrome'),
                                        ('safari', 'Safari'), ('curl', 'curl')) if key in ua),
                'Browser')
    return f'{name} on {os_name}' if os_name else name


def register_filters(app):
    app.jinja_env.filters.update(duration=duration, localtime=localtime, ago=ago,
                                 auditval=auditval, browser=browser)
