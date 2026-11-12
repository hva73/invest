"""Run the demo branch's anonymous journey with desktop CSS loaded locally."""
import subprocess
import sys
from pathlib import Path

source = Path('tests/browser_anonymous_demo.py').read_text()
def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Expected exactly one demo review hook: {old[:80]!r}')
    return text.replace(old, new, 1)

handler = '''class DesktopReviewHandler(app.Handler):
 def _get(self):
  if self.path == '/desktop-experience.css':
   return self.send(200, Path('static/desktop-experience.css').read_bytes(), 'text/css')
  return super()._get()

'''
source = replace_once(source, 'import os,re,sys,threading', 'import os,re,sys,threading\nfrom pathlib import Path')
source = replace_once(source, "server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)", handler + "server=app.ThreadingHTTPServer(('127.0.0.1',0),DesktopReviewHandler)")
source = replace_once(source, 'for width in (320,390,768,1280):', 'for width in (320,390,768,1024,1280,1440,1920):')
source = replace_once(source,
    "page.goto(f'http://127.0.0.1:{server.server_port}/');expect(page.locator('#login')).to_be_visible();expect(page.locator('aside nav')).to_be_hidden()",
    "page.goto(f'http://127.0.0.1:{server.server_port}/');page.evaluate(\"\"\"() => new Promise((ok,fail)=>{const l=document.createElement('link');l.rel='stylesheet';l.href='/desktop-experience.css';l.onload=ok;l.onerror=fail;document.head.append(l)})\"\"\");expect(page.locator('#login')).to_be_visible();expect(page.locator('aside nav')).to_be_hidden()")
generated = Path('tests/_desktop_demo_generated.py')
try:
    generated.write_text(source)
    subprocess.run([sys.executable, str(generated)], check=True)
finally:
    generated.unlink(missing_ok=True)
print('PASS: anonymous demo with desktop CSS at 320/390/768/1024/1280/1440/1920')
