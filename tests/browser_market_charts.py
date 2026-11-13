"""Synthetic Pluto series rendered in candidate cards; no external data or trades."""
import copy,os,sys,threading
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
import app,market_data
import test_market_data as fixtures
from playwright.sync_api import sync_playwright

def main():
 case=fixtures.Quotes();case.setUp();payload={'source':'Synthetic','observed':datetime.now(timezone.utc).isoformat(),'kind':'portfolio','positions':[],'accounts':[],'pending_orders':[],'value':None,'errors':[],'complete':True,'orders_complete':True}
 items=[{'id':'portfolios:root','name':'Synthetic root','kind':'portfolio','can_trade':True},{'id':'collections:child','name':'Synthetic child','kind':'collection','parent_external_id':'portfolios:root'}]
 real_normalize=market_data.normalized
 class Extended(case.factory):
  def request(self,method,params):
   if params['name']=='get_asset' and params['arguments']['period'] in ('ONE_MONTH','ONE_YEAR'):
    case.calls.append(params);raw=copy.deepcopy(case.raw);raw['performance']['period']=params['arguments']['period'];return {'structuredContent':raw}
   return super().request(method,params)
 server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('trade_service.MCP',Extended),patch('mcp_client.read_portfolios',return_value=items),patch('portfolio_data.read',return_value=payload),patch('market_data.normalized',side_effect=lambda raw,aid,**kw:real_normalize(raw,aid,case.fixed,**kw)),sync_playwright() as p:
   browser=p.chromium.launch(**({} if os.environ.get('ESCAPE_PLAYWRIGHT_MANAGED') else {'executable_path':'/usr/bin/chromium'}),headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000},has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#login-form [name=password]').fill('test-password-long-enough');page.locator('#login-form button').click();page.locator('#refresh-status[data-kind=success]').wait_for()
   page.locator('nav [data-view=radar]').click();slot=page.locator('.market-slot').first;slot.locator('.market-price').wait_for();assert '18,636' in slot.inner_text();assert '+1,22' in slot.inner_text();assert 'Førmarked' in slot.inner_text();assert 'kurstid ukendt' in slot.inner_text();assert slot.locator('[data-market-period=day]').get_attribute('aria-pressed')=='true'
   assert slot.locator('.market-line').get_attribute('d').count('L')==1;assert slot.locator('.market-change.market-positive').count()==1
   assert slot.locator('.market-plot.market-negative').count()==1;assert '2 punkter' in slot.inner_text();assert 'Skala' in slot.inner_text()
   coords=slot.locator('.market-line').get_attribute('d').replace('M','').replace('L','').split();ys=[float(v.split(',')[1]) for v in coords];assert 0<abs(ys[1]-ys[0])<10
   slot.locator('svg').hover(position={'x':10,'y':20});assert abs(float(slot.locator('.market-focus').get_attribute('cy'))-ys[0])<.01
   assert page.locator('.desk-candidate').first.get_attribute('data-attention')=='yellow'
   slot.locator('[data-market-period=week]').click();assert slot.locator('.market-line').get_attribute('d').count('L')==81;assert 'Uge' in slot.locator('.market-period-title').inner_text();assert '-5,69' in slot.inner_text();assert slot.locator('.market-plot.market-negative').count()==1;assert slot.locator('.market-change.market-positive').count()==1
   slot.locator('[data-market-period=month]').click();slot.locator('.market-period-title').filter(has_text='Måned').wait_for();slot.locator('.market-line').wait_for()
   slot.locator('[data-market-period=year]').click();slot.locator('.market-period-title').filter(has_text='År').wait_for();slot.locator('.market-line').wait_for()
   slot.locator('[data-market-period=day]').click();slot.locator('.market-about summary').click();assert 'Dagsændring er Plutos oplyste tal' in slot.inner_text();assert 'Ikke oplyst af Pluto' in slot.inner_text();slot.locator('.market-about summary').click()
   slot.locator('.market-about summary').click();slot.locator('[data-market-choose]').click();slot.locator('[data-market-asset]').wait_for();slot.locator('[data-market-asset]').select_option('synthetic-chart-asset');slot.locator('[data-market-select]').click();slot.locator('.market-price').wait_for()
   # Current readings in full report cards retain the same daily/weekly distinction.
   slot=page.locator('.desk-candidate .market-slot').first;slot.locator('.market-price').wait_for()
   for width in [320,390,430,768,1024,1440,1920]:
    page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
    for selector in ['.desk-candidate','.market-slot']:
     assert page.locator(selector).first.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1'),(width,selector)
    slot.locator('.market-about summary').click();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('about',width);slot.locator('.market-about summary').click()
    if width==390:
     plot=slot.locator('.market-plot svg');plot.scroll_into_view_if_needed();box=plot.bounding_box();page.touchscreen.tap(box['x']+box['width']*.5,box['y']+box['height']*.5)
     assert slot.locator('.market-hover').is_visible()
     assert slot.locator('.market-hover').inner_text().count(':')>=1
    if width in [390,1440]:page.locator('.desk-candidate').first.scroll_into_view_if_needed();page.screenshot(path=f'/tmp/escape-market-{width}.png')
   # Rolling day includes the previous evening: 25 hourly observations give 24 points.
   end=datetime(2026,11,2,10,tzinfo=timezone.utc)
   case.raw['performance']['series']=[{'timestamp':(end-timedelta(hours=24-i)).isoformat(),'close':18+i*.01} for i in range(25)]
   with app.connect() as c:c.execute('UPDATE market_asset_cache SET attempted=0')
   slot.locator('[data-market-refresh]').click();slot.locator('.market-session').filter(has_text='24 punkter').wait_for()
   assert slot.locator('.market-line').get_attribute('d').count('L')==23
   assert slot.locator('.market-plot.market-positive').count()==1
   assert 'Døgn' in slot.inner_text() or 'døgn' in slot.inner_text()
   # Source signs control return colors; report signal remains unchanged.
   case.raw['price'].update(dailyChange='-0.225',dailyChangePercent='-1.222')
   with app.connect() as c:c.execute('UPDATE market_asset_cache SET attempted=0')
   slot.locator('[data-market-refresh]').click();slot.locator('.market-change.market-negative').wait_for();assert page.locator('.desk-candidate').first.get_attribute('data-attention')=='yellow'
   assert all(c['name'] in ['search_assets','get_asset'] for c in case.calls)
   assert not errors,errors;browser.close()
  print('PASS: actual-shape hourly series, day defaults to 2 points, optional week has 82 points, rolling 24h crosses midnight with 24 samples; sparse decline stays small/red while daily remains green; yellow AFVENT unchanged, premarket and unknown quote time, full report/Radar and 320–1920px')
 finally:server.shutdown();server.server_close();case.tearDown()
if __name__=='__main__':main()
