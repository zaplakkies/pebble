"""Tray icon showing today's screen time. Deliberately has no "Quit" item."""
import logging
import threading
import time
import webbrowser
from datetime import datetime

import pystray
from PIL import Image, ImageDraw

from pebble_agent.sync import fmt_duration, today_status

log = logging.getLogger(__name__)
COLORS = {'under': (63, 157, 109), 'near': (217, 154, 43), 'over': (200, 85, 61),
          'unknown': (130, 134, 140)}


def make_icon(status):
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=COLORS.get(status, COLORS['unknown']) + (255,))
    draw.ellipse((22, 22, size - 22, size - 22), fill=(255, 255, 255, 235))
    return img


def status_line(s):
    used = fmt_duration(s['used_s'])
    if s['limit_s'] is None:
        text = f'Today: {used}' if s['status'] != 'unknown' else f'Today: {used} so far'
    elif s['status'] == 'over':
        text = f'Today: {used} — limit of {fmt_duration(s["limit_s"])} reached'
    else:
        left = fmt_duration(s['limit_s'] - s['used_s'])
        text = f'Today: {used} of {fmt_duration(s["limit_s"])} ({left} left)'
    return text + (' (estimate)' if s['estimate'] else '')


def sync_line(s, error):
    if error:
        return f'Not synced: {error}'
    if not s['last_sync']:
        return 'Not synced yet'
    return f'Last synced {datetime.fromtimestamp(s["last_sync"]):%H:%M}'


class Tray:
    def __init__(self, config, store, tracker, syncer, stop):
        self.config, self.store, self.tracker, self.syncer, self.stop = \
            config, store, tracker, syncer, stop
        self._status = today_status(store, tracker)
        self._icon_status = None
        self.icon = pystray.Icon('pebble', make_icon('unknown'), 'Pebble', menu=pystray.Menu(
            pystray.MenuItem(lambda _: status_line(self._status), None, enabled=False),
            pystray.MenuItem(lambda _: sync_line(self._status, self.syncer.last_error), None,
                             enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Open Pebble dashboard', self._open),
            pystray.MenuItem('Sync now', self._sync_now),
        ))

    def run(self):
        """Blocks until stop is set (must be called from the main thread)."""
        threading.Thread(target=self._refresh_loop, name='tray-refresh', daemon=True).start()
        self.icon.run()

    def _refresh_loop(self):
        while not self.stop.is_set():
            try:
                self._status = today_status(self.store, self.tracker)
                self.icon.title = 'Pebble · ' + status_line(self._status)[:100]
                if self._status['status'] != self._icon_status:
                    self._icon_status = self._status['status']
                    self.icon.icon = make_icon(self._icon_status)
                self.icon.update_menu()
            except Exception:
                log.exception('Tray refresh failed')
            self.stop.wait(20)
        self.icon.stop()

    def _open(self, *_):
        webbrowser.open(self.config.base_url + '/')

    def _sync_now(self, *_):
        self.syncer.wake.set()
        time.sleep(0.5)
