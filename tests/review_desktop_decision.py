"""Run PR #72's real synthetic decision journey at desktop and mobile widths.

This is a temporary cross-branch review: the checkout under test must be exactly
the pinned #72 commit. Its existing journey supplies the session/position mocks;
the desktop branch supplies only the separate, same-origin stylesheet.
"""
import os
import subprocess
import sys
from pathlib import Path

source = Path('tests/browser_signal_push_detail.py').read_text()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Expected exactly one review hook: {old[:80]!r}')
    return text.replace(old, new, 1)


handler = '''class DesktopReviewHandler(app.Handler):
 def _get(self):
  if self.path == '/desktop-experience.css':
   return self.send(200, Path('static/desktop-experience.css').read_bytes(), 'text/css')
  return super()._get()

'''
source = replace_once(source, 'def main():', handler + 'def main():')
source = replace_once(source, "app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)",
                      "app.ThreadingHTTPServer(('127.0.0.1',0),DesktopReviewHandler)")
source = replace_once(source,
    "page.goto(f'http://127.0.0.1:{server.server_port}');page.locator",
    "page.goto(f'http://127.0.0.1:{server.server_port}');page.evaluate(\"\"\"() => new Promise((ok,fail)=>{const l=document.createElement('link');l.rel='stylesheet';l.href='/desktop-experience.css';l.onload=ok;l.onerror=fail;document.head.append(l)})\"\"\");page.locator")

source = replace_once(source,
    "expect(d.locator('.signal-action-bar .signal-help')).to_have_count(0)",
    "expect(d.locator('.signal-action-bar .signal-help')).to_have_count(0)\n"
    "   expect(d.locator('h2')).to_be_focused()\n"
    "   page.keyboard.press('Tab')\n"
    "   assert page.evaluate(\"!!document.activeElement.closest('#engine-dialog')\")")

failures = []
generated = Path('tests/_desktop_decision_generated.py')
try:
    for width in (390, 1024, 1280, 1440, 1920):
        touch = width == 390
        test = replace_once(source, "viewport={'width':390,'height':700},is_mobile=True,has_touch=True",
                            f"viewport={{'width':{width},'height':900}},is_mobile={touch},has_touch={touch}")
        test = test.replace('signal-sell-390.png', f'decision-sell-{width}.png')
        test = test.replace('signal-buy-390.png', f'decision-buy-{width}.png')
        generated.write_text(test)
        print(f'Checking decision journey at {width}px', flush=True)
        result = subprocess.run([sys.executable, str(generated)], env=os.environ.copy())
        if result.returncode:
            failures.append(width)
finally:
    generated.unlink(missing_ok=True)
if failures:
    raise SystemExit('Decision journey failed at widths: ' + ', '.join(map(str, failures)))
print('PASS: #72 decision journey with desktop styles at 390/1024/1280/1440/1920')
