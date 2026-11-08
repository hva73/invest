"""Selection of qualified strategy versions for newly created watches."""
from hotwatch_contract import EngineError

DEFAULT_ID='escape_momentum'
DEFAULT_VERSION='1.0.0'


def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS hw_strategy_preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id),mode TEXT NOT NULL,strategy_id TEXT,version TEXT,updated TEXT NOT NULL)")


def resolve(connect,uid,scope='entry'):
    """Existing watches carry their own snapshot; no live session is modified."""
    if scope=='exit':
        return {'strategy_id':DEFAULT_ID,'version':DEFAULT_VERSION,'reason':'Beholdningen bruger den kvalificerede standardstrategi','mode':'auto'}
    with connect() as c:
        pref=c.execute('SELECT * FROM hw_strategy_preferences WHERE user_id=?',(uid,)).fetchone()
        if pref and pref['mode']=='manual':
            row=c.execute("SELECT * FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1",(uid,pref['strategy_id'],pref['version'])).fetchone()
            if row and row['validation_status']=='baseline_tested':
                return {'strategy_id':row['strategy_id'],'version':row['version'],'reason':'Valgt i dine strategiindstillinger','mode':'manual'}
            return {'strategy_id':DEFAULT_ID,'version':DEFAULT_VERSION,'reason':'Valgt strategi er ikke længere tilgængelig; standardstrategien anvendes','mode':'fallback'}
    return {'strategy_id':DEFAULT_ID,'version':DEFAULT_VERSION,'reason':'Automatisk standardvalg: Momentum','mode':'auto'}


def preferences(connect,uid):
    import hotwatch_engine
    with connect() as c:
        row=c.execute('SELECT mode,strategy_id,version FROM hw_strategy_preferences WHERE user_id=?',(uid,)).fetchone()
    return {'preference':dict(row) if row else {'mode':'auto','strategy_id':None,'version':None},'selection':resolve(connect,uid),**hotwatch_engine.strategies(connect,uid)}


def save(connect,uid,data,now):
    mode=data.get('mode')
    if mode not in ('auto','manual'):raise ValueError('Vælg automatisk eller manuel strategi.')
    sid=data.get('strategy_id');version=data.get('version')
    if mode=='manual':
        if not isinstance(sid,str) or not isinstance(version,str):raise ValueError('Vælg en tilgængelig strategi.')
        with connect() as c:
            row=c.execute("SELECT validation_status FROM hw_strategies WHERE owner_id IN (0,?) AND strategy_id=? AND version=? ORDER BY owner_id DESC LIMIT 1",(uid,sid,version)).fetchone()
        if not row or row['validation_status']!='baseline_tested':raise ValueError('Strategien er endnu ikke kvalificeret til drift.')
    else:sid=version=None
    with connect() as c:
        c.execute('INSERT INTO hw_strategy_preferences VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode,strategy_id=excluded.strategy_id,version=excluded.version,updated=excluded.updated',(uid,mode,sid,version,now))
    return preferences(connect,uid)
