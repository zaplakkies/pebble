"""Read the address bar of Chrome/Edge/Firefox/Brave through UI Automation.

Best effort: address bars differ between browsers, versions and languages, so
failures just mean no URL (the window title is still recorded).
"""
import uiautomation as auto

CHROMIUM = {'chrome.exe', 'msedge.exe', 'brave.exe', 'opera.exe', 'vivaldi.exe'}
ADDRESS_WORDS = ('address', 'adres', 'url', 'search or enter', 'adresse', 'direcci')


class BrowserUrls:
    def __init__(self):
        # COM must be initialised on the thread that uses UI Automation.
        self._com = auto.UIAutomationInitializerInThread()
        auto.SetGlobalSearchTimeout(1)

    def url(self, hwnd, exe_name):
        window = auto.ControlFromHandle(hwnd)
        if window is None:
            return None
        exe = exe_name.lower()
        if exe == 'firefox.exe':
            edit = window.EditControl(searchDepth=15, AutomationId='urlbar-input')
            return self._value(edit)
        if exe in CHROMIUM:
            # Prefer the edit whose name mentions the address bar; otherwise the first edit
            # in the toolbar (the address bar is the only one there).
            candidate = None
            for control, _depth in auto.WalkControl(window, maxDepth=12):
                if control.ControlTypeName != 'EditControl':
                    continue
                name = (control.Name or '').lower()
                if any(word in name for word in ADDRESS_WORDS):
                    return self._value(control)
                candidate = candidate or control
            return self._value(candidate)
        return None

    @staticmethod
    def _value(control):
        if control is None or not control.Exists(0, 0):
            return None
        try:
            return control.GetValuePattern().Value or None
        except Exception:
            return None
