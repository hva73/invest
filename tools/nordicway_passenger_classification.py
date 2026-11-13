"""Redacted read-only classification of processes blocking app drain.

Does not stop services, signal processes, read credentials, or change files.
Results are meaningful for a drain failure only if collected while the
existing selector confirms that the app is stopped.
"""
import os
import signal
from pathlib import Path


def classify(app, proc=Path('/proc'), *, uid=None, self_pid=None):
    app=Path(app)
    if app.is_symlink() or not app.is_dir(): raise ValueError('unsafe_app')
    app=app.resolve(strict=True)
    uid=os.getuid() if uid is None else uid
    self_pid=os.getpid() if self_pid is None else self_pid
    counts={'passenger_active':0,'wsgi_argument_exact':0,'passenger_title':0,
            'cwd_matches':0,'executable_lswsgi':0,'parent_is_one':0,
            'all_orphan_criteria':0,'inspection_incomplete':False}
    for process in Path(proc).iterdir():
        if not process.name.isdigit() or int(process.name)==self_pid: continue
        matched=False
        try:
            if process.stat().st_uid!=uid: continue
            raw=(process/'cmdline').read_bytes(); flat=raw.replace(b'\0',b' ')
            is_wsgi=b'passenger_wsgi.py' in flat
            title=b'Passenger' in flat and b'escape_app' in flat
            if not (is_wsgi or title): continue
            matched=True
            counts['passenger_active']+=1
            exact=os.fsencode(str(app/'passenger_wsgi.py')) in raw.split(b'\0')
            counts['wsgi_argument_exact']+=int(exact)
            counts['passenger_title']+=int(title)
            cwd=(process/'cwd').resolve(strict=True)==app
            exe=(process/'exe').resolve(strict=True).name=='lswsgi'
            rawstat=(process/'stat').read_text(); fields=rawstat[rawstat.rfind(')')+2:].split()
            if len(fields)<20: raise ValueError('incomplete_stat')
            parent=fields[1]=='1'
            counts['cwd_matches']+=int(cwd);counts['executable_lswsgi']+=int(exe)
            counts['parent_is_one']+=int(parent)
            counts['all_orphan_criteria']+=int(exact and cwd and exe and parent)
        except FileNotFoundError:
            if matched or process.exists(): counts['inspection_incomplete']=True
        except (OSError,ValueError): counts['inspection_incomplete']=True
    counts['pidfd_open_available']=hasattr(os,'pidfd_open')
    counts['pidfd_signal_available']=hasattr(signal,'pidfd_send_signal')
    return counts
