"""Run this file from an extracted ZIP under escape_app/opdatering.
Stop the application first. The motor starts when Passenger starts the app.
"""
import os,shutil,sqlite3,tempfile
from datetime import datetime,timezone
from pathlib import Path

FILES=('static/journal-ui.js','journal_projection.py','dashboard_projection.py','display_policy.py','static/dashboard-ui.js','candidate_lifecycle.py','static/candidate-ui.js','hotwatch_api.py','hotwatch_contract.py','hotwatch_engine.py','hotwatch_features.py','hotwatch_strategy.py','hotwatch_adapters.py','eodhd_feeds.py','hotwatch_service.py','hotwatch_supervisor.py','static/engine-ui.js','intel_workflows.py','intel_contract.py','static/intel-ui.js','app.py','static/overview-ui.js','market_data.py','static/market-ui.js','trade_service.py','pluto_trade_contract.json','static/trade-ui.js','report_ingest.py','report_v2.py','report_validation.py','position_reports.py','static/position-ui.js','mcp_reports.py','asset_quotes.py','pending_orders.py','portfolio_data.py','portfolios.py','mcp_client.py','pluto.py','oauth.py','jobs.py','news.py','worker.py','setup_runtime.py','requirements.txt','passenger_wsgi.py','static/app.js','static/report-ui.js','static/index.html','static/style.css','static/manifest.json','static/sw.js','static/icon.svg')

def apply(source,target):
    source=Path(source).resolve();target=Path(target).resolve()
    if source==target or target not in source.parents or 'opdatering' not in source.relative_to(target).parts:
        raise ValueError('Udpak ZIP under escape_app/opdatering først')
    database=target/'var/escape.db'
    if not database.is_file() or database.is_symlink():raise ValueError('Eksisterende database blev ikke fundet. Ingen filer er ændret.')
    for name in FILES:
        file=source/name
        if not file.is_file() or file.is_symlink() or source not in file.resolve().parents:raise ValueError('Opdateringen mangler en forventet kodefil')
        destination=target/name
        if destination.is_symlink() or target not in destination.resolve().parents:raise ValueError('Uventet destination')
    backup_root=target.parent/'.escape_backups';backup_root.mkdir(mode=0o700,exist_ok=True);os.chmod(backup_root,0o700)
    backup=Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-'),dir=backup_root));os.chmod(backup,0o700)
    with sqlite3.connect(f'file:{database}?mode=ro',uri=True) as original,sqlite3.connect(backup/'escape.db') as copy:
        original.backup(copy)
        if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Databasebackup kunne ikke valideres')
    os.chmod(backup/'escape.db',0o600)
    key=target/'var/keys/token.key'
    if key.exists():
        if key.is_symlink():raise ValueError('Uventet nøglesti')
        shutil.copyfile(key,backup/'token.key');os.chmod(backup/'token.key',0o600)
    existed=[]
    for name in FILES:
        destination=target/name
        if destination.exists():
            saved=backup/'code'/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,saved);existed.append(name)
    # Stage everything before replacing the first code file.
    with tempfile.TemporaryDirectory(prefix='.update-stage-',dir=target) as stage:
        stage=Path(stage)
        for name in FILES:
            file=stage/name;file.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,file);os.chmod(file,0o644)
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
