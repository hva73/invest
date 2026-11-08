import os,sys,threading,time,secrets
sys.path[:0]=[os.path.dirname(os.path.dirname(os.path.abspath(__file__))),os.path.dirname(os.path.abspath(__file__))]
import app,user_profile
from test_portfolio_value_chart import PortfolioValueChart
from playwright.sync_api import sync_playwright,expect
case=PortfolioValueChart();case.setUp()
with app.connect() as c:
 salt=secrets.token_hex(16);c.execute("INSERT INTO users(username,salt,hash,role,active) VALUES(?,?,?,'member',1)",('member',salt,app.password_hash('old-password-for-member',salt)))
 uid=c.execute("SELECT id FROM users WHERE username='member'").fetchone()['id']
 user_profile.save(c,uid,{'name':'Example','email':'example@example.org','street':'Testvej 1','postal_code':'7140','city':'Stouby','birth_date':'1980-02-29','contact_consent':False,'marketing_consent':False},app.now())
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);base=f'http://127.0.0.1:{server.server_port}'
  member=browser.new_context();m=member.new_page();m.goto(base);m.locator('#login-form [name=username]').fill('member');m.locator('#login-form [name=password]').fill('old-password-for-member');m.locator('#login-form button').click();expect(m.locator('#profile-open')).to_be_visible()
  assert m.evaluate("fetch('/api/admin/users').then(r=>r.status)")==403
  assert m.evaluate("fetch('/api/admin/reset-password',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({user_id:1,admin_password:'x',new_password:'long-password-enough'})}).then(r=>r.status)")==403
  admin=browser.new_page();admin.goto(base);admin.locator('#login-form [name=password]').fill('test-password-long-enough');admin.locator('#login-form button').click();expect(admin.locator('#profile-open')).to_be_visible()
  admin.locator('nav [data-view=settings]').click();admin.locator('[data-view=admin]').click();row=admin.locator('.admin-user').filter(has_text='member');row.locator('summary').first.click();expect(row).to_contain_text('example@example.org');row.locator('.admin-password summary').click()
  form=row.locator('form');form.locator('[name=new_password]').fill('new-password-for-member');form.locator('[name=repeat_password]').fill('new-password-for-member');form.locator('[name=admin_password]').fill('incorrect-password');form.locator('button[type=submit]').click();expect(form.locator('[role=status]')).to_contain_text('forkert')
  form.locator('[name=admin_password]').fill('test-password-long-enough');form.locator('button[type=submit]').click();expect(form.locator('[role=status]')).to_contain_text('ændret')
  assert m.evaluate("fetch('/api/session').then(r=>r.json()).then(x=>x.authenticated)") is False
  with app.connect() as c:
   record=c.execute('SELECT action FROM admin_actions WHERE target_id=?',(uid,)).fetchone();assert record['action']=='password_reset'
  browser.close();print('PASS: admin-only profile access, password verification, session revocation and audit')
finally:server.shutdown();server.server_close();case.tearDown()
