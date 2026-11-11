import ast,types,sys,json,datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from decimal import Decimal
from contextlib import contextmanager
from datetime import datetime as DT,timedelta,time as day_time,timezone
base=DT(2026,11,10,15,27,35,tzinfo=timezone.utc)
stamp=lambda s:DT.fromisoformat(s)
now=base+timedelta(seconds=119.5)
env={'utc':lambda:now,'stamp':stamp,'json':json,'datetime':DT,'timedelta':timedelta,'day_time':day_time,'ZoneInfo':ZoneInfo,'ZoneInfoNotFoundError':ZoneInfoNotFoundError,'number':lambda x:Decimal(str(x)) if x is not None else None}
for file,name in [(str(ROOT / 'hotwatch_adapters.py'),'market_status'),(str(ROOT / 'hotwatch_features.py'),'verified_bar_samples')]:
 tree=ast.parse(open(file).read()); node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),file,'exec'),env)
sys.modules['report_validation']=types.SimpleNamespace(stamp=stamp)
calendar={'open':'09:30:00','close':'16:00:00','working_days':['Mon','Tue','Wed','Thu','Fri'],'excluded_dates':[]}
row={'received':base.isoformat(),'calendar_received':base.isoformat(),'is_open':1,'timezone':'America/New_York','calendar':json.dumps(calendar)}
class C:
 def execute(self,*a):return self
 def fetchone(self):return row
@contextmanager
def connect():yield C()
class Client:
 def market_status(self,e):raise AssertionError('unexpected refresh')
schedule=env['market_status'](types.SimpleNamespace(connect=connect),Client(),'US',120)
bar=base.replace(second=0)+timedelta(seconds=60)
trade=bar+timedelta(seconds=70)
sample={'source':'eodhd','price_time_kind':'trade','market_status':'REGULAR','event_time':trade.isoformat(),'bar_history':[{'bar_open_at':bar.isoformat(),'open':1,'high':1,'low':1,'close':1,'volume':1}],'bar_evidence':{'exchange_open':True,'feed':'eodhd_realtime_history','provider_symbol':'MSFT.US','market':'us','exchange':'US','timezone':'America/New_York','session_date':'2026-11-10','open':'09:30:00','close':'16:00:00','working_days':calendar['working_days'],'excluded_dates':[],'schedule_received_at':schedule['received_at']}}
request={'provider_symbol':'MSFT.US','risk':{'max_quote_age_s':120}}
verify=env['verified_bar_samples']
assert verify(sample,request,base+timedelta(seconds=119.5)) is not None
assert verify(sample,request,base+timedelta(seconds=120.5)) is None
print('PASS: faktisk cache- og valideringsfunktion: kalender 119,5 s accepteres; samme evidens ved 120,5 s afvises.')
