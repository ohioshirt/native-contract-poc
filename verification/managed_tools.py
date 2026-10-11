"""Small shared process recorder; all command failures remain explicit evidence."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import zipfile


def capture(argv, out, name, *, cwd, timeout=180, stdin=None, env=None):
    out = Path(out); out.mkdir(parents=True,exist_ok=True)
    start = datetime.now(timezone.utc).isoformat(); mono = time.monotonic()
    code, timed_out, error = None, False, None
    stdout, stderr = b'', b''
    try:
        process = subprocess.Popen([str(a) for a in argv],cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,start_new_session=True)
        try: stdout,stderr = process.communicate(stdin,timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid,signal.SIGKILL)
            stdout,stderr = process.communicate()
        code = process.returncode
    except OSError as exc: error = str(exc); stderr = str(exc).encode()
    record = {'argv':[str(a) for a in argv],'cwd':str(cwd),'startUtc':start,'endUtc':datetime.now(timezone.utc).isoformat(),'seconds':time.monotonic()-mono,'exitCode':code,'timedOut':timed_out,'error':error}
    (out/f'{name}.stdout.log').write_bytes(stdout); (out/f'{name}.stderr.log').write_bytes(stderr)
    (out/f'{name}.command.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def runner(root, platform):
    root = Path(root)
    if platform == 'swift':
        executable = root/'ios/.build/debug/ManagedHistoryRunner'
        return [str(executable)] if executable.is_file() and os.access(executable,os.X_OK) else None
    libs = root/'android/async-library/build/install/async-library/lib'
    jars = list(libs.glob('*.jar'))
    try:
        present = False
        for jar in jars:
            with zipfile.ZipFile(jar) as archive:
                present = present or 'nativecontract/async/ManagedHistoryRunnerKt.class' in archive.namelist()
    except (OSError,zipfile.BadZipFile): return None
    return ['java','-cp',str(libs/'*'),'nativecontract.async.ManagedHistoryRunnerKt'] if present else None


def write_report(out, filename, report):
    Path(out).mkdir(parents=True,exist_ok=True)
    (Path(out)/filename).write_text(json.dumps(report,indent=2)+'\n')
    return report
