from pathlib import Path
import os,sys,tempfile,subprocess
root=Path(__file__).resolve().parents[1];skill=root/'.agents/skills/maya-audit-pro'
choices={'build':'build_data.py','validate':'validate_data.py','render':'render.py'}
if len(sys.argv)<2 or sys.argv[1]not in choices:raise SystemExit('Choose build, validate or render, then the skill arguments')
browsers=os.environ.get('PLAYWRIGHT_BROWSERS_PATH');driver=os.environ.get('PLAYWRIGHT_NODEJS_PATH')
with tempfile.TemporaryDirectory(prefix='maya-pro-offline-')as tmp:
 w=Path(tmp);(w/'home').mkdir();(w/'cache').mkdir();env={k:os.environ[k]for k in ['PATH','LANG','LC_ALL','SYSTEMROOT','WINDIR']if k in os.environ}
 env.update(HOME=str(w/'home'),TMPDIR=str(w),MAYA_AUDIT_HOME=str(w/'audit'),MAYA_AUDIT_ENV_FILE=str(w/'absent.env'),XDG_CACHE_HOME=str(w/'cache'),PYTHONPYCACHEPREFIX=str(w/'bytecode'))
 if browsers:env['PLAYWRIGHT_BROWSERS_PATH']=browsers
 elif sys.platform=='darwin':env['PLAYWRIGHT_BROWSERS_PATH']=str(Path.home()/'Library/Caches/ms-playwright')
 if driver:env['PLAYWRIGHT_NODEJS_PATH']=driver
 raise SystemExit(subprocess.run([sys.executable,str(skill/'scripts'/choices[sys.argv[1]]),*sys.argv[2:]],cwd=root,env=env).returncode)
