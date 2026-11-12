"""Run this file from an extracted ZIP under escape_app/opdatering.
Stop the application first. The motor starts when Passenger starts the app.
"""
import os,shutil,sqlite3,tempfile,fcntl,time,subprocess,sys,hashlib,json
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path

FILES=('BUILD_COMMIT','release_approval.py','web_push.py','strategy_center.py','strategy_lab.py','data/dk_postcodes.json','user_profile.py','sector_intelligence.py','ssga_holdings.py','ishares_holdings.py','tasks/pepe_test_signal.py','tasks/pluto_readonly_risk_probe.py','static/sector-ui.js','static/journal-ui.js','journal_projection.py','dashboard_projection.py','display_policy.py','static/dashboard-ui.js','candidate_lifecycle.py','static/candidate-ui.js','hotwatch_api.py','hotwatch_buy_plan.py','hotwatch_contract.py','hotwatch_engine.py','hotwatch_warmup.py','hotwatch_features.py','hotwatch_strategy.py','hotwatch_adapters.py','eodhd_capacity.py','eodhd_feeds.py','cxe_reference.py','eodhd_us_reference.py','instrument_resolver.py','hotwatch_service.py','hotwatch_supervisor.py','static/engine-ui.js','intel_workflows.py','intel_contract.py','static/intel-ui.js','app.py','static/overview-ui.js','market_data.py','static/market-ui.js','trade_service.py','pluto_trade_contract.json','static/trade-ui.js','report_ingest.py','report_v2.py','report_validation.py','position_reports.py','static/position-ui.js','mcp_reports.py','asset_quotes.py','pending_orders.py','portfolio_data.py','portfolios.py','mcp_client.py','pluto.py','oauth.py','jobs.py','news.py','worker.py','setup_runtime.py','requirements.txt','passenger_wsgi.py','static/app.js','static/report-ui.js','static/index.html','static/demo-data.js','static/style.css','static/desktop-experience.css','static/manifest.json','static/sw.js','static/icon.svg')

def _fsync_directory(path):
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)

def _hash_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def _backup_file(source,destination,database_identity):
    source_identity=source.stat()
    if (source_identity.st_dev,source_identity.st_ino)==database_identity:
        raise ValueError('Backupfil må ikke være hardlink til databasen')
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    shutil.copyfile(source,destination);os.chmod(destination,0o600)
    with destination.open('rb') as stream:os.fsync(stream.fileno())
    saved=_hash_file(destination)
    if _hash_file(source)!=saved:raise RuntimeError('Backupfil matcher ikke originalen')
    _fsync_directory(destination.parent)
    return saved

@contextmanager
def quiesce_hotwatch(target,timeout=30):
    """Stop the detached supervisor and refuse to replace code under a worker."""
    var=target/'var';disabled=var/'hotwatch-autostart.disabled';created=False;locks=[]
    try:
        if disabled.is_symlink():raise ValueError('Uventet HOT WATCH-statusfil')
        try:
            fd=os.open(disabled,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            os.close(fd);created=True
        except FileExistsError:pass
        deadline=time.monotonic()+timeout
        for name in ('supervisor','worker'):
            fd=os.open(var/('hotwatch-'+name+'.lock'),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
            locks.append(fd)
            while True:
                try:
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=deadline:raise RuntimeError('HOT WATCH-motoren standsede ikke; ingen kodefiler er ændret')
                    time.sleep(.2)
        yield
    finally:
        for fd in reversed(locks):os.close(fd)
        if created:disabled.unlink(missing_ok=True)

@contextmanager
def locked_database_snapshot(database, destination):
    """Keep SQLite writers blocked across snapshot and code replacement.

    Copy in a child process: closing another descriptor for the same SQLite
    file in this process can release POSIX advisory locks unexpectedly.
    """
    if database.parent.is_symlink() or database.is_symlink():raise ValueError('Uventet databasesti')
    if any(Path(str(database)+suffix).exists() or Path(str(database)+suffix).is_symlink() for suffix in ('-wal','-journal','-shm')):
        raise RuntimeError('Databasen er ikke klar til en låst backup')
    original=None;copy=None
    try:
        original=sqlite3.connect(str(database),timeout=3,isolation_level=None)
        original.execute('BEGIN EXCLUSIVE')
        if original.execute('PRAGMA journal_mode').fetchone()!=('delete',):
            raise RuntimeError('Uunderstøttet databasejournal; ingen kodefiler er ændret')
        if any(Path(str(database)+suffix).exists() or Path(str(database)+suffix).is_symlink() for suffix in ('-wal','-journal','-shm')):
            raise RuntimeError('Databasen er ikke klar til en låst backup')
        identity=database.stat()
        if identity.st_nlink!=1:raise RuntimeError('Databasen har uventede hardlinks')
        copy_script=("import os,shutil,sys\n"
                     "fd=os.open(sys.argv[2],os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)\n"
                     "with open(sys.argv[1],'rb') as source,os.fdopen(fd,'wb') as target:\n"
                     " shutil.copyfileobj(source,target,1024*1024);target.flush();os.fsync(target.fileno())\n")
        subprocess.run([sys.executable,'-I','-S','-c',copy_script,str(database),str(destination)],
                       check=True,timeout=300,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        current=database.stat()
        if database.is_symlink() or (identity.st_dev,identity.st_ino)!=(current.st_dev,current.st_ino):
            raise RuntimeError('Databasestien blev ændret under backup')
        os.chmod(destination,0o600)
        directory_fd=os.open(destination.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
        copy=sqlite3.connect(f'file:{destination}?mode=ro',uri=True)
        if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Databasebackup kunne ikke valideres')
        copy.close();copy=None
        yield
    finally:
        if copy is not None:copy.close()
        if original is not None:
            if original.in_transaction:original.rollback()
            original.close()

def apply(source,target,*,verify_backup=None):
    source=Path(source).resolve();target=Path(target).resolve()
    if source==target or target not in source.parents or 'opdatering' not in source.relative_to(target).parts:
        raise ValueError('Udpak ZIP under escape_app/opdatering først')
    database=target/'var/escape.db'
    if database.parent.is_symlink() or not database.is_file() or database.is_symlink():raise ValueError('Eksisterende database blev ikke fundet. Ingen filer er ændret.')
    for name in FILES:
        file=source/name
        if not file.is_file() or file.is_symlink() or source not in file.resolve().parents:raise ValueError('Opdateringen mangler en forventet kodefil')
        destination=target/name
        if destination.is_symlink() or target not in destination.resolve().parents:raise ValueError('Uventet destination')
    # Keep both motor locks across snapshot and code replacement. The caller
    # must separately stop and verify Passenger before calling this function.
    with quiesce_hotwatch(target):
        backup_root=target.parent/'.escape_backups'
        if backup_root.is_symlink():raise ValueError('Uventet backupsti')
        backup_root.mkdir(mode=0o700,exist_ok=True)
        if backup_root.stat().st_uid!=os.getuid():raise ValueError('Uventet backupejer')
        os.chmod(backup_root,0o700)
        backup=Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-'),dir=backup_root));os.chmod(backup,0o700)
        _fsync_directory(backup_root)
        with locked_database_snapshot(database, backup/'escape.db'):
            db_stat=database.stat();database_identity=(db_stat.st_dev,db_stat.st_ino)
            inventory={'format':1,'database_sha256':_hash_file(backup/'escape.db'),'files':{},'keys':{}}
            key=target/'var/keys/token.key'
            if key.parent.is_symlink():raise ValueError('Uventet nøglesti')
            if key.is_symlink():raise ValueError('Uventet nøglesti')
            if key.exists():
                inventory['keys']['token.key']=_backup_file(key,backup/'token.key',database_identity)
            else:inventory['keys']['token.key']=None
            push_key=target/'var/keys/push_vapid.pem'
            if push_key.is_symlink():raise ValueError('Uventet notifikationsnøgle')
            if push_key.exists():
                inventory['keys']['push_vapid.pem']=_backup_file(push_key,backup/'push_vapid.pem',database_identity)
            else:inventory['keys']['push_vapid.pem']=None
            existed=[]
            for name in FILES:
                destination=target/name
                if destination.exists():
                    saved=backup/'code'/name;inventory['files'][name]=_backup_file(destination,saved,database_identity);existed.append(name)
                else:inventory['files'][name]=None
            manifest_fd=os.open(backup/'manifest.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(manifest_fd,'w',encoding='utf-8') as stream:
                json.dump(inventory,stream,sort_keys=True,separators=(',',':'));stream.write('\n');stream.flush();os.fsync(stream.fileno())
            _fsync_directory(backup)
            if verify_backup is not None and verify_backup(backup) is not True:
                raise RuntimeError('Backup kunne ikke verificeres; ingen kodefiler er ændret')
            # Stage everything before replacing the first code file.
            with tempfile.TemporaryDirectory(prefix='.update-stage-',dir=target) as stage:
                stage=Path(stage)
                for name in FILES:
                    original_file=source/name;original_stat=original_file.stat()
                    if (original_stat.st_dev,original_stat.st_ino)==database_identity:raise ValueError('Kildefil må ikke være hardlink til databasen')
                    file=stage/name;file.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original_file,file);os.chmod(file,0o644)
                replaced=[]
                try:
                    for name in FILES:
                        destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True);os.replace(stage/name,destination);replaced.append(name)
                except Exception:
                    for name in reversed(replaced):
                        if name in existed:shutil.copy2(backup/'code'/name,target/name)
                        else:(target/name).unlink(missing_ok=True)
                    raise
    disabled=target/'var/hotwatch-autostart.disabled'
    enabled=target/'var/hotwatch-autostart.enabled'
    if not disabled.exists():
        fd=os.open(enabled,os.O_WRONLY|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        os.close(fd)
    return backup

if __name__=='__main__':
    source=Path(__file__).resolve().parent
    target=next((parent for parent in source.parents if (parent/'var/escape.db').is_file()),None)
    if target is None:raise RuntimeError('Kunne ikke finde den eksisterende escape_app-database. Ingen ændringer udført.')
    backup=apply(source,target)
    print('Kodefiler opdateret. Database bevaret. Privat backup: '+str(backup))
    print('Næste trin: installér requirements.txt via Run Pip Install og kør setup_runtime.py. Start derefter appen.')
