"""Integrated synthetic Pluto quote + verified EODHD minute chart."""
import copy,os,sys,threading
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import app,market_data
import test_market_data as fixtures
from playwright.sync_api import sync_playwright,expect
def main():
 case=fixtures.Quotes();case.setUp()
 payload={'source':'Synthetic','observed':datetime.now(timezone.utc).isoformat(),'kind':'portfolio','positions':[],'accounts':[],'pending_orders':[],'value':None,'errors':[],'complete':True,'orders_complete':True}
 portfolios=[{'id':'portfolios:root','name':'Synthetic root','kind':'portfolio','can_trade':True},{'id':'collections:child','name':'Synthetic child','kind':'collection','parent_external_id':'portfolios:root'}]
 calls=[];real_normalize=market_data.normalized;real_enrich=market_data.enrich_intraday;real_enrich=market_data.enrich_intraday
 class Feed:
  def intraday(self,symbol,**kwargs):
   calls.append((symbol,kwargs));now=datetime.now(timezone.utc).replace(microsecond=0)
   span=kwargs['end']-kwargs['start']; count=180 if kwargs['interval']=='5m' else 200 if kwargs['interval']=='1h' else 130 if span<2*86400 else 160; step={'1m':60,'5m':300,'1h':3600}[kwargs['interval']]
   return {'status':'OK','bars':[{'bar_open_at':datetime.fromtimestamp(kwargs['start']+(span-step)*i/(count-1),timezone.utc).isoformat(),'close':str(999+i/1000)} for i in range(count)]}
 class Extended(case.factory):
  def request(self,method,params):
   if params['name']=='get_asset' and params['arguments']['period'] in ('ONE_MONTH','ONE_YEAR'):
    case.calls.append(params);raw=copy.deepcopy(case.raw);raw['performance']['period']=params['arguments']['period'];return {'structuredContent':raw}
   return super().request(method,params)
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch.dict('os.environ',{'ESCAPE_EODHD_API_KEY':'synthetic','ESCAPE_HW_EODHD_REST_ENABLED':'1'}),patch('trade_service.MCP',Extended),patch('mcp_client.read_portfolios',return_value=portfolios),patch('portfolio_data.read',return_value=payload),patch('market_data.normalized',side_effect=lambda raw,aid,**kw:real_normalize(raw,aid,case.fixed,**kw)),patch('market_data.enrich_intraday',side_effect=lambda connect,uid,result,**kw:real_enrich(connect,uid,result,now=case.fixed,**kw)),patch('market_data.enrich_intraday',side_effect=lambda connect,uid,result,**kw:real_enrich(connect,uid,result,now=case.fixed,**kw)),patch('hotwatch_service.verified_existing_feed',return_value={'provider_symbol':'CHART.US'}),patch('hotwatch_adapters.EODHDAdapter.feeds',return_value=Feed()),sync_playwright() as p:
   browser=p.chromium.launch(**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':390,'height':900},has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('#refresh-status[data-kind=success]').wait_for()
   page.locator('#mobile-more').click();page.locator('nav [data-view=radar]').click();slot=page.locator('.market-slot').first;slot.locator('[data-market-load]').click()
   try: expect(slot.locator('.market-session')).to_contain_text('EODHD · minutbarer · 130 punkter',timeout=12000)
   except AssertionError:
    print('DIAGNOSTIC slot count',page.locator('.market-slot').count(),'body',page.locator('body').inner_text()[:5000],'calls',calls,'errors',errors)
    raise
   expect(slot.locator('.market-origin')).to_contain_text('Pluto · kurstid ukendt')
   expect(slot.locator('.market-price')).to_contain_text('18,636')
   assert slot.locator('.market-line').get_attribute('d').count('L')==129
   plot=slot.locator('.market-plot svg');plot.scroll_into_view_if_needed();box=plot.bounding_box();page.touchscreen.tap(box['x']+box['width']*.5,box['y']+box['height']*.5);expect(slot.locator('.market-hover')).to_be_visible();expect(slot.locator('.market-hover')).to_contain_text('minutbarens start');expect(slot.locator('.market-hover')).to_contain_text('999')
   for period,label,count in [('week','minutbarer',160),('month','5-minutsbarer',180),('year','timebarer',200)]:
    slot.locator('[data-market-period='+period+']').click();expect(slot.locator('.market-session')).to_contain_text('EODHD · '+label+' · '+str(count)+' punkter',timeout=30000)
    assert slot.locator('.market-line').get_attribute('d').count('L')==count-1
    expect(slot.locator('.market-price')).to_contain_text('18,636');expect(slot.locator('.market-origin')).to_contain_text('Pluto · kurstid ukendt')
    plot=slot.locator('.market-plot svg');plot.scroll_into_view_if_needed();box=plot.bounding_box();page.touchscreen.tap(box['x']+box['width']*.5,box['y']+box['height']*.5);expect(slot.locator('.market-hover')).to_be_visible();expect(slot.locator('.market-hover')).to_contain_text('barens start')
   assert calls and calls[0][0]=='CHART.US' and calls[0][1]['max_points'] is None
   page.evaluate("window.ESCAPE_DEMO=true")
   slot.locator('[data-market-refresh]').click();expect(slot.locator('.market-origin')).to_contain_text('Demo')
   page.evaluate("""() => {const n=document.querySelector('.market-slot').cloneNode(true);n.id='demo-quote-test';n.dataset.marketLayout='quote';n.style.cssText='position:fixed;top:0;left:0;width:250px;z-index:9999';document.body.append(n)}""")
   page.evaluate("window.MarketUI.refreshVisible()")
   expect(page.locator('#demo-quote-test .market-mini-title')).to_contain_text('Dagens kurs · Demo')
   assert not errors,errors;browser.close()
 finally:server.shutdown();server.server_close();case.tearDown()
 print('PASS: source-selected 130 minute bars and 82 separate Pluto points')
if __name__=='__main__':main()
