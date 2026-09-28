"""Parsing Windows System event log entries about power state (no Windows APIs)."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from pebble_agent.lifecycle import OsEvent

# Kernel-General 12/13: OS started/shut down. Kernel-Power 42: going to sleep.
# Power-Troubleshooter 1: resumed. EventLog 6008: previous shutdown was unexpected.
QUERY = ("*[System[(Provider[@Name='Microsoft-Windows-Kernel-General'] and (EventID=12 or EventID=13))"
         " or (Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=42)"
         " or (Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1)"
         " or (Provider[@Name='EventLog'] and EventID=6008)]]")
_TYPES = {('Microsoft-Windows-Kernel-General', '12'): 'os_boot',
          ('Microsoft-Windows-Kernel-General', '13'): 'os_shutdown',
          ('Microsoft-Windows-Kernel-Power', '42'): 'os_sleep',
          ('Microsoft-Windows-Power-Troubleshooter', '1'): 'os_resume',
          ('EventLog', '6008'): 'os_shutdown'}
_NS = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event'}


def parse(xml_text):
    events = []
    for chunk in re.findall(r'<Event .*?</Event>', xml_text, flags=re.S):
        try:
            root = ET.fromstring(chunk)
        except ET.ParseError:
            continue
        system = root.find('e:System', _NS)
        provider = system.find('e:Provider', _NS).get('Name')
        event_id = system.findtext('e:EventID', namespaces=_NS)
        kind = _TYPES.get((provider, event_id))
        created = system.find('e:TimeCreated', _NS).get('SystemTime')
        if not kind or not created:
            continue
        at = datetime.fromisoformat(re.sub(r'(\.\d{6})\d*', r'\1', created.replace('Z', '+00:00')))
        details = {'unexpected': True} if event_id == '6008' else {}
        events.append(OsEvent(at=at.timestamp(), type=kind, details=details))
    return sorted(events)
