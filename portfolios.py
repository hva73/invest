"""User-owned stable portfolio IDs. Broker contracts are never guessed."""
import time

def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS portfolios(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,source TEXT NOT NULL,external_id TEXT,active INTEGER NOT NULL DEFAULT 1,updated REAL NOT NULL,UNIQUE(user_id,source,external_id))")
    for name,definition in [('kind',"TEXT NOT NULL DEFAULT 'portfolio'"),('parent_external_id','TEXT'),('can_trade','INTEGER')]:
        if name not in {r['name'] for r in c.execute('PRAGMA table_info(portfolios)')}:c.execute(f'ALTER TABLE portfolios ADD COLUMN {name} {definition}')
    if 'portfolio_id' not in {r['name'] for r in c.execute('PRAGMA table_info(proposals)')}:
        c.execute('ALTER TABLE proposals ADD COLUMN portfolio_id INTEGER REFERENCES portfolios(id)')
    # Preserve historical names as local records, never claim they came from Pluto.
    legacy=c.execute('SELECT DISTINCT user_id,portfolio FROM proposals WHERE portfolio_id IS NULL').fetchall()
    for row in legacy:
        existing=c.execute("SELECT id FROM portfolios WHERE user_id=? AND name=? AND source='local'",(row['user_id'],row['portfolio'])).fetchone()
        if not existing:
            cur=c.execute("INSERT INTO portfolios(user_id,name,source,updated) VALUES(?,?,'local',?)",(row['user_id'],row['portfolio'],time.time()));pid=cur.lastrowid
        else:pid=existing['id']
        c.execute('UPDATE proposals SET portfolio_id=? WHERE user_id=? AND portfolio=? AND portfolio_id IS NULL',(pid,row['user_id'],row['portfolio']))

def list_owned(c,user_id):
    return [dict(r) for r in c.execute('SELECT id,name,source,external_id,active,updated,kind,parent_external_id,can_trade FROM portfolios WHERE user_id=? ORDER BY active DESC,name,id',(user_id,))]

def create(c,user_id,name):
    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('Ugyldigt porteføljenavn')
    return c.execute("INSERT INTO portfolios(user_id,name,source,updated) VALUES(?,?,'local',?)",(user_id,name.strip(),time.time())).lastrowid

def rename(c,user_id,pid,name):
    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('Ugyldigt porteføljenavn')
    if c.execute("UPDATE portfolios SET name=?,updated=? WHERE id=? AND user_id=? AND source='local'",(name.strip(),time.time(),pid,user_id)).rowcount!=1:raise ValueError('Ukendt lokal portefølje')

def replace_pluto(c,user_id,items):
    """For a future verified adapter: atomically reconcile a complete remote listing."""
    seen=set()
    for item in items:
        if not isinstance(item.get('id'),str) or not item['id'] or item['id'] in seen:raise ValueError('Ugyldig eller gentaget Pluto-identitet')
        if not isinstance(item.get('name'),str) or not item['name'].strip():raise ValueError('Manglende Pluto-navn')
        seen.add(item['id'])
    c.execute("UPDATE portfolios SET active=0 WHERE user_id=? AND source='pluto'",(user_id,))
    for item in items:
        c.execute("INSERT INTO portfolios(user_id,name,source,external_id,active,updated,kind,parent_external_id,can_trade) VALUES(?,?,'pluto',?,1,?,?,?,?) ON CONFLICT(user_id,source,external_id) DO UPDATE SET name=excluded.name,active=1,updated=excluded.updated,kind=excluded.kind,parent_external_id=excluded.parent_external_id,can_trade=excluded.can_trade",(user_id,item['name'],item['id'],time.time(),item.get('kind','portfolio'),item.get('parent_external_id'),item.get('can_trade')))
