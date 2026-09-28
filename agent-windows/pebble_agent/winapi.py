"""Windows-only calls (ctypes + psutil). Imported only on Windows."""
import ctypes
import getpass
import logging
import os
import subprocess
from ctypes import wintypes
from functools import lru_cache

import psutil

from pebble_agent import eventlog, titles
from pebble_agent.tracker import Sample

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
version = ctypes.WinDLL('version', use_last_error=True)

CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
MONITOR_DEFAULTTONEAREST = 2


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumChildWindows.argtypes = [wintypes.HWND, EnumChildProc, wintypes.LPARAM]
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD
version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                        wintypes.LPVOID]
version.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                   ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.UINT)]


# ------------------------------------------------------------------ basics

def current_user():
    return getpass.getuser()


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def single_instance(name='Local\\PebbleAgent'):
    """Hold a per-logon-session mutex. Returns the handle, or None if already running."""
    handle = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def idle_seconds():
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # Both are 32-bit tick counts; unsigned subtraction handles the 49.7-day wrap.
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def session_is_active():
    """False when this user's session isn't the one on screen (fast user switching)."""
    sid = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
        return True
    active = kernel32.WTSGetActiveConsoleSessionId()
    return active == 0xFFFFFFFF or sid.value == active


def boot_time():
    return psutil.boot_time()


def session_start(user=None):
    """When the current user logged on (falls back to boot time)."""
    user = (user or current_user()).lower()
    starts = [u.started for u in psutil.users() if (u.name or '').lower() == user]
    return max(starts) if starts else psutil.boot_time()


# ------------------------------------------------------------------ windows

def _window_text(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _uwp_child_pid(hwnd, host_pid):
    """Store apps run inside ApplicationFrameHost; the real app owns a child window."""
    found = []

    def callback(child, _):
        pid = _pid(child)
        if pid != host_pid:
            found.append(pid)
            return False
        return True
    user32.EnumChildWindows(hwnd, EnumChildProc(callback), 0)
    return found[0] if found else host_pid


def _is_fullscreen(hwnd):
    if _class_name(hwnd) in ('Progman', 'WorkerW', 'Shell_TrayWnd'):
        return False
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    m = info.rcMonitor
    return (rect.left <= m.left and rect.top <= m.top
            and rect.right >= m.right and rect.bottom >= m.bottom)


@lru_cache(maxsize=512)
def file_description(path):
    """FileDescription from the exe's version resource, e.g. 'Microsoft Word'."""
    if not path:
        return None
    try:
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, data):
            return None
        ptr, length = wintypes.LPVOID(), wintypes.UINT()
        if not version.VerQueryValueW(data, r'\VarFileInfo\Translation', ctypes.byref(ptr),
                                      ctypes.byref(length)) or not length.value:
            return None
        lang, codepage = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
        key = rf'\StringFileInfo\{lang:04x}{codepage:04x}\FileDescription'
        if not version.VerQueryValueW(data, key, ctypes.byref(ptr), ctypes.byref(length)) \
                or not length.value:
            return None
        text = ctypes.wstring_at(ptr, length.value).rstrip('\x00').strip()
        return text or None
    except OSError:
        return None


class WindowsProbe:
    """Samples the foreground window. Use from one thread only (UI Automation is per-thread)."""

    def __init__(self, capture_urls=True):
        self._url_cache = {}
        self._browser = None
        if capture_urls:
            try:
                from pebble_agent.browser import BrowserUrls
                self._browser = BrowserUrls()
            except Exception:
                log.warning('Browser URL capture unavailable', exc_info=True)

    def idle_seconds(self):
        return idle_seconds()

    def sample(self):
        if not session_is_active():
            return None
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = _pid(hwnd)
        try:
            proc = psutil.Process(pid)
            exe_name = proc.name()
            if exe_name.lower() == 'applicationframehost.exe':
                pid = _uwp_child_pid(hwnd, pid)
                proc = psutil.Process(pid)
                exe_name = proc.name()
            try:
                path = proc.exe()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                path = None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

        title = _window_text(hwnd) or None
        url = None
        if exe_name.lower() in titles.BROWSERS:
            url = self._url(hwnd, exe_name, title)
            title = titles.strip_browser_suffix(title) or None
        return Sample(app_id=exe_name,
                      app_name=titles.friendly_name(exe_name, file_description(path)),
                      title=title, url=url, fullscreen=_is_fullscreen(hwnd))

    def _url(self, hwnd, exe_name, title):
        if not self._browser:
            return None
        key = (hwnd, title)
        if key not in self._url_cache:
            if len(self._url_cache) > 200:
                self._url_cache.clear()
            try:
                self._url_cache[key] = titles.normalize_url(self._browser.url(hwnd, exe_name))
            except Exception:
                log.debug('URL lookup failed', exc_info=True)
                self._url_cache[key] = None
        return self._url_cache[key]


# ------------------------------------------------------------------ event log

def read_os_events(max_events=200):
    try:
        out = subprocess.run(
            ['wevtutil', 'qe', 'System', f'/q:{eventlog.QUERY}', f'/c:{max_events}', '/rd:true',
             '/f:xml'],
            capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        log.warning('Could not read the event log', exc_info=True)
        return []
    return eventlog.parse(out)
