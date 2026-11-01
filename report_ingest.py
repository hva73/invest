"""Isolated, authenticated report inbox. Reports never execute broker actions."""
import hashlib,hmac,json,os,re
from datetime import datetime,timezone

def init(c):
    c.execute('CREATE TABLE IF NOT EXISTS ingested_reports(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),report_id TEXT NOT NULL,received TEXT NOT NULL,payload TEXT NOT NULL,digest TEXT NOT NULL,UNIQUE(user_id,report_id))')

def recipient(connect,authorization):
    key=os.environ.get('ESCAPE_REPORT_INGEST_KEY','');username=os.environ.get('ESCAPE_REPORT_INGEST_USER','')
    if len(key)<32 or not username:return None,503
    expected=('Bearer '+key).encode()
    if not hmac.compare_digest(str(authorization or '').encode(),expected):return None,401
    with connect() as c:row=c.execute('SELECT id FROM users WHERE username=? COLLATE NOCASE AND active=1',(username,)).fetchone()
    return (row['id'],200) if row else (None,503)

def fields(obj,required):
    if not isinstance(obj,dict) or set(obj)!=set(required):raise ValueError('Felter matcher ikke rapportformat v1')

def text(value,limit=2000):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('Ugyldigt tekstfelt')

def validate(data):
    fields(data,['schema_version','report_id','generated_at','source','is_test','portfolio_values','candidates','assessments','orders'])
    if type(data['schema_version']) is not int or data['schema_version']!=1 or type(data['is_test']) is not bool:raise ValueError('Ugyldig version eller testmarkering')
    if not isinstance(data['report_id'],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',data['report_id']):raise ValueError('Ugyldigt report_id')
    text(data['source'],100);text(data['generated_at'],50)
    stamp=datetime.fromisoformat(data['generated_at'].replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('generated_at skal indeholde tidszone')
    for key,keys in [('portfolio_values',['name','amount','currency','includes_collections']),('candidates',['symbol','market','reason']),('assessments',['subject','assessment']),('orders',['reference','status','note'])]:
        if not isinstance(data[key],list) or len(data[key])>30:raise ValueError('Højst 30 poster pr. liste')
        for row in data[key]:
            fields(row,keys)
            for name in keys:
                if name=='includes_collections':
                    if type(row[name]) is not bool:raise ValueError('Ugyldig Collection-markering')
                elif name=='amount':
                    if not isinstance(row[name],str) or not re.fullmatch(r'-?\d{1,18}(\.\d{1,10})?',row[name]):raise ValueError('Beløb skal være en decimalstreng')
                else:text(row[name],2000 if name in ['reason','assessment','note'] else 100)
            if key=='portfolio_values' and not re.fullmatch('[A-Z]{3}',row['currency']):raise ValueError('Valuta skal have tre store bogstaver')
    return data

def save(connect,user_id,data):
    validate(data)
    payload=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'));digest=hashlib.sha256(payload.encode()).hexdigest()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT id,digest FROM ingested_reports WHERE user_id=? AND report_id=?',(user_id,data['report_id'])).fetchone()
        if old:
            if old['digest']!=digest:return 409,{'error':'report_id findes allerede med andet indhold'}
            return 200,{'ok':True,'id':old['id'],'duplicate':True}
        cur=c.execute('INSERT INTO ingested_reports(user_id,report_id,received,payload,digest) VALUES(?,?,?,?,?)',(user_id,data['report_id'],datetime.now(timezone.utc).isoformat(),payload,digest))
        return 201,{'ok':True,'id':cur.lastrowid,'duplicate':False}

def latest(connect,user_id):
    with connect() as c:row=c.execute('SELECT id,received,payload FROM ingested_reports WHERE user_id=? ORDER BY id DESC LIMIT 1',(user_id,)).fetchone()
    return {'report':{'id':row['id'],'received':row['received'],'data':json.loads(row['payload'])} if row else None}
