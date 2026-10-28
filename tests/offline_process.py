"""Credential-free child processes with the same loopback boundary as pytest."""
from pathlib import Path
import os
import tempfile


_GUARD = '''import socket, ipaddress
_connect, _resolve = socket.socket.connect, socket.getaddrinfo
def local(host):
    try: return ipaddress.ip_address(str(host).strip('[]')).is_loopback
    except ValueError: return str(host) == 'localhost' or str(host).endswith('.localhost')
def connect(sock, address):
    if isinstance(address, tuple) and not local(address[0]):
        raise RuntimeError('offline test child prohibits external connections')
    return _connect(sock, address)
def resolve(host, *args, **kwargs):
    if not local(host):
        raise socket.gaierror('offline test child prohibits external DNS')
    return _resolve(host, *args, **kwargs)
socket.socket.connect, socket.getaddrinfo = connect, resolve
'''


def environment():
    root = Path(__file__).resolve().parents[1]
    work = Path(tempfile.mkdtemp(prefix='maya-offline-child-'))
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_CTYPE', 'USER', 'PYTHONPYCACHEPREFIX',
            'PLAYWRIGHT_NODEJS_PATH', 'PLAYWRIGHT_BROWSERS_PATH') if k in os.environ}
    for key, name in (('HOME', 'home'), ('MAYA_AUDIT_HOME', 'audit'), ('TMPDIR', 'tmp'),
                      ('XDG_CACHE_HOME', 'cache'), ('XDG_CONFIG_HOME', 'config')):
        folder = work / name
        folder.mkdir()
        env[key] = str(folder)
    if os.name == 'nt':
        # Windows cannot start asyncio/Winsock without SYSTEMROOT; the browser cache lives under LOCALAPPDATA.
        env.update({k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT') if k in os.environ})
        if 'PLAYWRIGHT_BROWSERS_PATH' not in env and 'LOCALAPPDATA' in os.environ:
            env['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(os.environ['LOCALAPPDATA']) / 'ms-playwright')
        env.update(USERPROFILE=env['HOME'], TEMP=env['TMPDIR'], TMP=env['TMPDIR'])
    guard = work / 'guards'
    guard.mkdir()
    (guard / 'sitecustomize.py').write_text(_GUARD)
    env.update(PYTHONPATH=str(root) + os.pathsep + str(guard),
               MAYA_AUDIT_ENV_FILE=str(work / 'absent.env'), MAYA_AUDIT_FIRECRAWL='off')
    return env
