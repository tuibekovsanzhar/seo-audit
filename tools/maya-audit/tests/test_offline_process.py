"""The audit subprocess cannot fall through pytest's in-process network guard."""
import json
import subprocess
import sys
from pathlib import Path
from offline_process import environment


def test_offline_child_removes_unknown_credentials_and_blocks_external_dns(monkeypatch):
    monkeypatch.setenv('SYNTHETIC_PROVIDER_SECRET', 'not-a-real-credential')
    env = environment()
    assert 'SYNTHETIC_PROVIDER_SECRET' not in env
    assert not Path(env['MAYA_AUDIT_ENV_FILE']).exists()
    code = '''import socket, os, json
blocked = False
try: socket.getaddrinfo('unassessed-synthetic.invalid', 443)
except socket.gaierror: blocked = True
print(json.dumps({'blocked': blocked, 'local': bool(socket.getaddrinfo('127.0.0.1', 80)), 'secret': 'SYNTHETIC_PROVIDER_SECRET' in os.environ}))
'''
    run = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=10, check=True)
    assert json.loads(run.stdout) == {'blocked': True, 'local': True, 'secret': False}
