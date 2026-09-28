"""pebble-agent command line.

    pebble-agent run                 track and sync (started by the scheduled task)
    pebble-agent install --server URL --token TOKEN [--users emma,sam]
    pebble-agent status              show config, queue and today's time
    pebble-agent uninstall [--keep-data]
"""
import argparse
import atexit
import logging
import logging.handlers
import sys
import threading
import time

from pebble_agent import __version__, config as cfg
from pebble_agent.config import Config
from pebble_agent.lifecycle import record_os_events, record_start, record_stop
from pebble_agent.store import Store
from pebble_agent.sync import SyncError, Syncer, fmt_duration, http_json, today_status
from pebble_agent.tracker import Tracker

log = logging.getLogger('pebble_agent')


def setup_logging(to_file):
    handler = logging.StreamHandler()
    if to_file:
        path = cfg.log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3,
                                                       encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def attach_console():
    """The packaged exe has no console window; reuse the terminal it was started from."""
    if not (cfg.IS_WINDOWS and getattr(sys, 'frozen', False)):
        return
    import ctypes
    if ctypes.windll.kernel32.AttachConsole(-1):
        sys.stdout = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
        sys.stderr = sys.stdout
        print()


def cmd_run(args):
    setup_logging(to_file=cfg.IS_WINDOWS)
    if not cfg.IS_WINDOWS:
        raise SystemExit('The agent only runs on Windows (tests and tools/ run anywhere).')
    from pebble_agent import winapi

    mutex = winapi.single_instance()
    if mutex is None:
        return  # already running in this logon session (the task retries every 5 min)
    config = Config.load()
    user = winapi.current_user()
    if not config.tracks(user):
        log.info('Not tracking user %s', user)
        return

    store = Store(cfg.data_dir() / 'queue.db')
    record_start(store, config, user, now=time.time(), boot_time=winapi.boot_time(),
                 session_start=winapi.session_start(user), os_events=winapi.read_os_events())
    log.info('Pebble agent %s started for %s', __version__, user)

    stop = threading.Event()
    probe_ready = threading.Event()
    tracker_box = {}

    def track():
        # The probe uses UI Automation, which must stay on this thread.
        tracker = Tracker(store, winapi.WindowsProbe(), config, user=user)
        tracker_box['tracker'] = tracker
        probe_ready.set()
        while not stop.is_set():
            tracker.tick()
            stop.wait(config.sample_interval_s)
        tracker.close()

    last_events_check = [0.0]

    def before_sync():
        if time.time() - last_events_check[0] > 300:
            last_events_check[0] = time.time()
            record_os_events(store, winapi.read_os_events())

    syncer = Syncer(config, store, before_sync=before_sync)
    threads = [threading.Thread(target=track, name='tracker', daemon=True),
               threading.Thread(target=syncer.run, args=(stop,), name='sync', daemon=True)]
    for t in threads:
        t.start()
    probe_ready.wait(10)

    stopped = []

    def shutdown(reason='exit'):
        if stopped:
            return
        stopped.append(reason)
        stop.set()
        syncer.wake.set()
        threads[0].join(5)
        record_stop(store, user, time.time(), reason)
        log.info('Pebble agent stopped (%s)', reason)
    atexit.register(shutdown)

    if args.no_tray:
        try:
            while not stop.is_set():
                stop.wait(1)
        except KeyboardInterrupt:
            shutdown('ctrl-c')
        return
    try:
        from pebble_agent.tray import Tray
        Tray(config, store, tracker_box.get('tracker'), syncer, stop).run()
    except Exception:
        log.exception('Tray icon failed; continuing without it')
        while not stop.is_set():
            stop.wait(1)


def cmd_status(args):
    attach_console()
    config = Config.load()
    store = Store(cfg.data_dir() / 'queue.db')
    print(f'Pebble agent {__version__}')
    print(f'  Server:        {config.base_url}')
    print(f'  Users tracked: {", ".join(config.track_users) or "everyone"}')
    print(f'  Queued:        {store.pending_count()} records')
    s = today_status(store)
    limit = fmt_duration(s['limit_s']) if s['limit_s'] is not None else 'none/unknown'
    print(f'  Today:         {fmt_duration(s["used_s"])} (limit {limit}, {s["status"]})'
          f'{" (estimate)" if s["estimate"] else ""}')
    try:
        today = http_json('GET', f'{config.base_url}/api/v1/status', config.token,
                          store.install_id)['today']
        print(f'  Server says:   {fmt_duration(today["used_s"])} today — connection OK')
    except SyncError as e:
        print(f'  Server:        {e}')


def cmd_install(args):
    attach_console()
    from pebble_agent.install import install
    users = [u.strip() for u in (args.users or '').split(',') if u.strip()]
    install(args.server, args.token, users, start=not args.no_start)


def cmd_uninstall(args):
    attach_console()
    from pebble_agent.install import uninstall
    uninstall(keep_data=args.keep_data)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='pebble-agent', description='Pebble screen-time agent')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command')
    p = sub.add_parser('run', help='track and sync (default)')
    p.add_argument('--no-tray', action='store_true', help='no tray icon (for debugging)')
    p.set_defaults(func=cmd_run)
    p = sub.add_parser('install', help='install for all users (administrator)')
    p.add_argument('--server', required=True, help='e.g. http://192.168.3.10')
    p.add_argument('--token', required=True, help='device token from the management page')
    p.add_argument('--users', help='comma-separated Windows accounts to track (default: all)')
    p.add_argument('--no-start', action='store_true')
    p.set_defaults(func=cmd_install)
    p = sub.add_parser('uninstall', help='remove the agent (administrator)')
    p.add_argument('--keep-data', action='store_true')
    p.set_defaults(func=cmd_uninstall)
    p = sub.add_parser('status', help="show today's time and connection")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    if not args.command:
        args = parser.parse_args(['run'] + (argv or sys.argv[1:]))
    args.func(args)


if __name__ == '__main__':
    main()
