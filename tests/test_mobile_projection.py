"""Exercise real dashboard projection through the mobile renderer with synthetic events."""
import copy,json,subprocess,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import app,dashboard_projection as dashboard
from test_design_v1_acceptance import DesignAcceptance

class MobileProjection(unittest.TestCase):
 def test_current_signal_requires_matching_event_and_fresh_market_evidence(self):
  fixture=DesignAcceptance();fixture.setUp();self.addCleanup(fixture.tearDown)
  now=datetime.now(timezone.utc);port=fixture.root['id'];candidate='synthetic-mobile';asset='mobile-asset'
  request={'asset_id':asset,'candidate_id':candidate,'portfolio_ids':[port]}
  with app.connect() as c:
   c.execute("INSERT INTO hw_sessions(user_id,watch_id,is_test,candidate_id,purpose,status,request,digest,strategy,state,created,updated,next_due) VALUES(1,?,0,?,'exit','ACTIVE',?,'d','{}','{}',?,?,0)",(candidate,candidate,json.dumps(request),now.isoformat(),now.isoformat()))
   base={'watch_id':candidate,'status':'ACTIVE','last_data_at':now.isoformat(),'last_calculation_at':now.isoformat(),'signal':'SELL','display_status':'SÆLGSSIGNAL','data_stale':False,'data_status':{'price_status':'FRESH','market_status':'OPEN'},'last_action_signal':{'event_id':'event','event_type':'SELL_SIGNAL','state':'ACTIVE'}}
   cases=[]
   for name,change,expected in [
    ('valid_sell',{},'SÆLGSSIGNAL'),('missing_event',{'last_action_signal':None},'Se status'),
    ('wrong_event',{'last_action_signal':{'event_type':'BUY_SIGNAL','state':'ACTIVE'}},'Se status'),
    ('withdrawn',{'last_action_signal':{'event_type':'SELL_SIGNAL','state':'WITHDRAWN'}},'Se status'),
    ('unknown_quote',{'data_status':{'price_status':'UNKNOWN','market_status':'OPEN'}},'Afventer data'),
    ('unknown_market',{'data_status':{'price_status':'FRESH','market_status':'UNKNOWN'}},'Afventer data'),
    ('closed',{'data_status':{'price_status':'FRESH','market_status':'CLOSED'}},'Marked lukket'),
    ('stale',{'last_data_at':(now-timedelta(minutes=5)).isoformat(),'data_stale':True},'Afventer data'),
    ('future',{'last_data_at':(now+timedelta(minutes=2)).isoformat()},'Afventer data'),
    ('buy',{'signal':'BUY','display_status':'KØBSSIGNAL','last_action_signal':{'event_type':'BUY_SIGNAL','state':'ACTIVE'}},'KØBSSIGNAL')]:
    view=copy.deepcopy(base);view.update(change)
    with patch('hotwatch_engine.view',return_value=view):
     result=dashboard.position_hotwatch(c,1,port,asset,{'candidate_id':candidate})
    cases.append({'name':name,'session':result['session'],'expected':expected})
  js="""const vm=require('vm'),fs=require('fs'),assert=require('assert');const cases=JSON.parse(fs.readFileSync(0,'utf8'));const ctx={window:{},document:{getElementById:()=>null},Intl,Date,Number,String,console};vm.runInNewContext(fs.readFileSync('static/dashboard-ui.js','utf8'),ctx);const ui=ctx.window.DashboardUI;ui.setup({api:()=>{},escape:String,formatTime:String,formatQuantity:String,state:()=>({})});for(const c of cases){let row={key:'k',ticker:'TSM',name:'TSM',portfolio_name:'test',portfolio_id:1,verification:'broker_snapshot',conflicts:[],hot_watch:{session:c.session}};let html=ui.render({dashboard:{positions:[row],accounts:[],totals:[],warnings:[],orders:[],critical_sessions:[]}});let found=html.match(/class=\"mobile-holding-status [^\"]+\">([^<]+)/);assert(found,c.name);assert.strictEqual(found[1],c.expected,c.name)}"""
  subprocess.run(['node','-e',js],input=json.dumps(cases),text=True,check=True)
if __name__=='__main__':unittest.main()
