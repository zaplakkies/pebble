"""Install / uninstall on Windows (run from an administrator prompt)."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from pebble_agent import config as cfg
from pebble_agent.config import Config
from pebble_agent.store import Store
from pebble_agent.sync import SyncError, Unauthorized, http_json, pair

TASK_NAME = 'Pebble Agent'
EXE_NAME = 'pebble-agent.exe'
CREATE_NO_WINDOW = 0x08000000
# Well-known SIDs, so this works on non-English Windows too.
SYSTEM, ADMINS, USERS = '*S-1-5-18', '*S-1-5-32-544', '*S-1-5-32-545'

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Pebble screen-time agent. Records which apps are used and reports to the family Pebble server.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
    <TimeTrigger>
      <Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>2025-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Users">
      <GroupId>S-1-5-32-545</GroupId>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Users">
    <Exec>
      <Command>"{exe}"</Command>
      <Arguments>run</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _run(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if check and result.returncode != 0:
        raise SystemExit(f'{args[0]} failed: {(result.stderr or result.stdout).strip()}')
    return result


def _stop_agents(exe_path):
    """Stop running agents started from exe_path (not this installer process)."""
    me = os.getpid()
    for proc in psutil.process_iter(['pid', 'exe']):
        try:
            if proc.info['pid'] != me and proc.info['exe'] and \
                    Path(proc.info['exe']).resolve() == exe_path.resolve():
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    time.sleep(1)


def install(server, token, users, start=True, code=None):
    from pebble_agent import winapi
    if not winapi.is_admin():
        raise SystemExit('Run this from an administrator PowerShell or Command Prompt.')
    if not getattr(sys, 'frozen', False):
        raise SystemExit('Install from the packaged pebble-agent.exe (see build.ps1).')

    server = server.rstrip('/')
    if code:
        print(f'Pairing with {server} ...')
        token = pair(server, code)
    conf = Config(server=server, token=token, track_users=users)
    home = cfg.home()
    store = Store(cfg.data_dir() / 'queue.db')
    print(f'Checking {conf.base_url} ...')
    try:
        today = http_json('GET', f'{conf.base_url}/api/v1/status', token, store.install_id)['today']
    except Unauthorized:
        raise SystemExit('The server does not recognise that token. Copy it again from the '
                         'management page (or issue a new one).')
    except SyncError as e:
        raise SystemExit(f'Could not reach the server: {e}')
    print(f"  OK: today so far {today['used_s'] // 60} min")

    # A different token = a fresh device on the server: start a fresh record chain.
    try:
        old = Config.load()
    except SystemExit:
        old = None
    store.close()
    if old is None or old.token != token:
        for f in cfg.data_dir().glob('queue.db*'):
            f.unlink()

    target = cfg.INSTALL_DIR / EXE_NAME
    _run(['schtasks', '/End', '/TN', TASK_NAME], check=False)
    _stop_agents(target)
    cfg.INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    if Path(sys.executable).resolve() != target.resolve():
        shutil.copy2(sys.executable, target)
    print(f'Installed {target}')

    conf.save()
    cfg.data_dir().mkdir(parents=True, exist_ok=True)
    # Admins change the config, users only read it; the queue must be writable by the agent.
    _run(['icacls', str(home), '/inheritance:r', '/grant:r', f'{SYSTEM}:(OI)(CI)F',
          f'{ADMINS}:(OI)(CI)F', f'{USERS}:(OI)(CI)RX'])
    _run(['icacls', str(cfg.data_dir()), '/grant:r', f'{USERS}:(OI)(CI)M'])
    print(f'Config written to {cfg.config_path()}')

    with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False, encoding='utf-16') as f:
        f.write(TASK_XML.format(exe=target))
    try:
        _run(['schtasks', '/Create', '/TN', TASK_NAME, '/XML', f.name, '/F'])
    finally:
        os.unlink(f.name)
    print(f'Scheduled task "{TASK_NAME}" starts the agent at every logon '
          f'({"users: " + ", ".join(users) if users else "all users"}).')

    if start:
        started = _run(['schtasks', '/Run', '/TN', TASK_NAME], check=False).returncode == 0
        print('Agent started.' if started else
              'Could not start the agent now; it starts at the next logon.')
    print('\nDone. Kids should use standard (not administrator) Windows accounts.')


def uninstall(keep_data=False):
    from pebble_agent import winapi
    if not winapi.is_admin():
        raise SystemExit('Run this from an administrator prompt.')
    _run(['schtasks', '/End', '/TN', TASK_NAME], check=False)
    _run(['schtasks', '/Delete', '/TN', TASK_NAME, '/F'], check=False)
    _stop_agents(cfg.INSTALL_DIR / EXE_NAME)
    if Path(sys.executable).resolve().parent != cfg.INSTALL_DIR.resolve():
        shutil.rmtree(cfg.INSTALL_DIR, ignore_errors=True)
    else:
        print(f'Delete {cfg.INSTALL_DIR} manually (this program is running from it).')
    if not keep_data:
        shutil.rmtree(cfg.home(), ignore_errors=True)
    print('Pebble agent removed.')
