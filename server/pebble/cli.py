"""Command-line management until the hidden management page exists (phase 3).

    flask kid add Emma --weekday 120 --weekend 180
    flask device add Emma "Emma laptop" --platform windows
"""
import click
from flask.cli import AppGroup

from pebble import db
from pebble.models import Alert, Device, Kid, hash_token
from pebble.services import record_audit
from pebble.timeutil import to_local

kid_cli = AppGroup('kid', help='Manage kids.')
device_cli = AppGroup('device', help='Manage devices.')


def _get_kid(name):
    kid = Kid.query.filter(Kid.name.ilike(name)).first()
    if kid is None:
        raise click.ClickException(f'No kid called {name!r}. Add one with: flask kid add {name}')
    return kid


@kid_cli.command('add')
@click.argument('name')
@click.option('--weekday', type=int, help='Daily limit in minutes, Mon–Fri.')
@click.option('--weekend', type=int, help='Daily limit in minutes, Sat–Sun.')
def kid_add(name, weekday, weekend):
    if Kid.query.filter(Kid.name.ilike(name)).first():
        raise click.ClickException(f'{name} already exists.')
    kid = Kid(name=name, weekday_limit_min=weekday, weekend_limit_min=weekend)
    db.session.add(kid)
    db.session.flush()
    record_audit('create', 'kid', kid.id, new={'name': name, 'weekday_limit_min': weekday,
                                               'weekend_limit_min': weekend})
    db.session.commit()
    click.echo(f'Added {name} (weekday {weekday or "no"} min, weekend {weekend or "no"} min limit).')


@kid_cli.command('list')
def kid_list():
    for kid in Kid.query.order_by(Kid.name):
        click.echo(f'{kid.id:>3}  {kid.name:<20} weekday={kid.weekday_limit_min}  '
                   f'weekend={kid.weekend_limit_min}  devices={len(kid.devices)}')


@device_cli.command('add')
@click.argument('kid_name')
@click.argument('device_name')
@click.option('--platform', type=click.Choice(['windows', 'android']), required=True)
def device_add(kid_name, device_name, platform):
    kid = _get_kid(kid_name)
    token = Device.new_token()
    device = Device(kid=kid, name=device_name, platform=platform, token_hash=hash_token(token))
    db.session.add(device)
    db.session.flush()
    record_audit('create', 'device', device.id,
                 new={'kid': kid.name, 'name': device_name, 'platform': platform})
    db.session.commit()
    click.echo(f'Added device {device.id} "{device_name}" for {kid.name}.')
    click.echo(f'Token (shown once, put it in the agent config):\n\n    {token}\n')


@device_cli.command('list')
def device_list():
    for d in Device.query.order_by(Device.id):
        seen = to_local(d.last_seen).strftime('%Y-%m-%d %H:%M') if d.last_seen else 'never'
        state = '' if d.active else '  [revoked]'
        click.echo(f'{d.id:>3}  {d.kid.name:<12} {d.name:<24} {d.platform:<8} '
                   f'last seen {seen}  seq={d.last_seq}{state}')


@device_cli.command('revoke')
@click.argument('device_id', type=int)
def device_revoke(device_id):
    device = db.session.get(Device, device_id)
    if device is None:
        raise click.ClickException(f'No device {device_id}.')
    device.active = False
    record_audit('update', 'device', device.id, old={'active': True}, new={'active': False})
    db.session.commit()
    click.echo(f'Revoked device {device.id} "{device.name}"; its token no longer works.')


@click.command('alerts')
@click.option('--all', 'show_all', is_flag=True, help='Include acknowledged alerts.')
def alerts(show_all):
    """Show tamper alerts."""
    query = Alert.query if show_all else Alert.query.filter_by(acknowledged=False)
    for a in query.order_by(Alert.created_at.desc()).limit(100):
        when = to_local(a.created_at).strftime('%Y-%m-%d %H:%M')
        where = a.device.name if a.device else '-'
        click.echo(f'{when}  {where:<20} {a.kind:<18} {a.detail}')


def register_cli(app):
    app.cli.add_command(kid_cli)
    app.cli.add_command(device_cli)
    app.cli.add_command(alerts)
