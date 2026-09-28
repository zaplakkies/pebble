"""Interpreting window titles and exe names. Pure functions, no Windows APIs."""
import fnmatch
import re
from urllib.parse import urlsplit

BROWSERS = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe', 'vivaldi.exe'}

# Windows that aren't "using the computer": lock screen, sign-in, screen savers.
NOT_USAGE = {'lockapp.exe', 'logonui.exe', 'scrnsave.scr'}

# Title suffixes of document editors -> the part before is the document name.
DOCUMENT_SUFFIXES = [
    ' - Word', ' - Excel', ' - PowerPoint', ' - OneNote', ' - Notepad', ' - Paint',
    ' - WordPad', ' - LibreOffice Writer', ' - LibreOffice Calc', ' - LibreOffice Impress',
    ' - Google Docs', ' - Google Sheets', ' - Google Slides',
]
_BROWSER_SUFFIX = re.compile(
    r' [-—–] (Google Chrome|Microsoft​? Edge|Mozilla Firefox|Brave|Opera|Vivaldi)$')
_DOC_EXTENSION = re.compile(r'\.(docx?|xlsx?|pptx?|odt|ods|odp|txt|rtf|pdf|md|py|js|html?|css|'
                            r'java|cs|cpp|c|json|sb3|psd|kra|blend)$', re.I)

# Things people watch without touching the keyboard or mouse.
VIDEO_TITLE = re.compile(
    r'youtube|netflix|disney\+|prime video|twitch|showmax|vlc media player|media player|'
    r'movies & tv|plex|kodi|tiktok', re.I)
VIDEO_APPS = {'vlc.exe', 'wmplayer.exe', 'microsoft.media.player.exe', 'video.ui.exe',
              'plex.exe', 'kodi.exe', 'mpc-hc64.exe', 'mpc-hc.exe', 'potplayermini64.exe'}

FRIENDLY_NAMES = {
    'chrome.exe': 'Google Chrome', 'msedge.exe': 'Microsoft Edge', 'firefox.exe': 'Firefox',
    'winword.exe': 'Microsoft Word', 'excel.exe': 'Microsoft Excel',
    'powerpnt.exe': 'Microsoft PowerPoint', 'explorer.exe': 'File Explorer',
    'javaw.exe': 'Java (Minecraft?)', 'minecraft.windows.exe': 'Minecraft',
    'robloxplayerbeta.exe': 'Roblox', 'discord.exe': 'Discord', 'steam.exe': 'Steam',
    'applicationframehost.exe': 'Windows app',
}


def strip_browser_suffix(title):
    return _BROWSER_SUFFIX.sub('', title or '')


def document_name(app_id, title):
    """Document being edited, from the window title, or None."""
    if not title:
        return None
    for suffix in DOCUMENT_SUFFIXES:
        if title.endswith(suffix):
            name = title[:-len(suffix)].strip()
            # Word shows e.g. "Essay.docx - Compatibility Mode - Word" or "Essay - Saved - Word"
            name = re.sub(r' [-•] (Compatibility Mode|Saved|Saving\.\.\.|AutoRecovered|'
                          r'Read-Only|Protected View)$', '', name, flags=re.I)
            return name.lstrip('*').strip() or None
    if (app_id or '').lower() in BROWSERS:
        return None
    # Other editors that put "file.ext - App" in the title (e.g. VS Code, Acrobat)
    first = title.split(' - ')[0].lstrip('●*').strip()
    return first if _DOC_EXTENSION.search(first) else None


def friendly_name(app_id, description=None):
    if description:
        return description
    key = (app_id or '').lower()
    if key in FRIENDLY_NAMES:
        return FRIENDLY_NAMES[key]
    base = re.sub(r'\.exe$', '', app_id or '', flags=re.I)
    return base[:1].upper() + base[1:] if base else 'Unknown'


def looks_like_video(app_id, title):
    return (app_id or '').lower() in VIDEO_APPS or bool(VIDEO_TITLE.search(title or ''))


def normalize_url(raw):
    """Browser address bars often omit the scheme ("youtube.com/watch?v=1")."""
    if not raw:
        return None
    raw = raw.strip()
    if ' ' in raw or '.' not in raw.split('/')[0] and '://' not in raw:
        return None  # search text being typed, not a URL
    if '://' not in raw:
        raw = 'https://' + raw
    return raw if urlsplit(raw).hostname else None


def domain_of(url):
    host = urlsplit(url).hostname if url else None
    return host[4:] if host and host.startswith('www.') else host


def excluded(rules, app_id, title, url):
    """Same matching as the server (docs/api.md), for the offline estimate."""
    domain = (domain_of(url) or '').lower()
    for rule in rules or []:
        if not any(rule.get(k) for k in ('app_id', 'domain', 'title_pattern')):
            continue
        if rule.get('app_id') and rule['app_id'].lower() != (app_id or '').lower():
            continue
        if rule.get('domain'):
            d = rule['domain'].lower()
            if not (domain == d or domain.endswith('.' + d)):
                continue
        if rule.get('title_pattern') and not fnmatch.fnmatch((title or '').lower(),
                                                             rule['title_pattern'].lower()):
            continue
        return True
    return False
