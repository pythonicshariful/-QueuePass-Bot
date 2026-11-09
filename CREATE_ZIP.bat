@echo off
setlocal
title QueuePass Bot — Create Delivery ZIP
cd /d "%~dp0"

python -c "import os, zipfile; from pathlib import Path; p=Path('.'); z=Path('..')/'queue-pass-bot.zip'; ex={'__pycache__','.venv','.pytest_cache'}; exd={'last_pass.txt','results.json'}; zf=zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED); [zf.write(Path(r)/f, str(Path('queue-pass-bot')/Path(r).relative_to(p)/f).replace('\\','/')) for r,ds,fs in os.walk(p) if not ds.__setitem__(slice(None),[d for d in ds if d not in ex]) for f in fs if not f.endswith(('.pyc','.pyo','.zip')) and not (Path(r).name=='data' and f in exd)]; zf.close(); print('Created:', z.resolve())"
pause

