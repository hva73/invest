"""Exercise shared signal journey across mobile and desktop widths."""
import os, subprocess, sys
from pathlib import Path

source = Path('tests/browser_signal_push_detail.py').read_text()
def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Expected exactly one integration hook: {old[:80]!r}')
    return text.replace(old, new, 1)

source = replace_once(source,
    "expect(d.locator('.signal-action-bar .signal-help')).to_have_count(0)",
    "expect(d.locator('.signal-action-bar .signal-help')).to_have_count(0)\n"
    "   expect(d.locator('h2')).to_be_focused()\n"
    "   page.keyboard.press('Tab')\n"
    "   assert page.evaluate(\"!!document.activeElement.closest('#engine-dialog')\")")
generated = Path('tests/_integrated_decision_generated.py')
failures = []
try:
    for width in (390, 1024, 1280, 1440, 1920):
        touch = width == 390
        height = 844 if touch else 900
        test = replace_once(source, "viewport={'width':390,'height':700},is_mobile=True,has_touch=True",
                            f"viewport={{'width':{width},'height':{height}}},is_mobile={touch},has_touch={touch}")
        test = test.replace('signal-sell-390.png', f'integrated-sell-{width}.png')
        test = test.replace('signal-buy-390.png', f'integrated-buy-{width}.png')
        generated.write_text(test)
        print(f'Checking integrated signal journey at {width}px', flush=True)
        if subprocess.run([sys.executable, str(generated)], env=os.environ.copy()).returncode:
            failures.append(width)
finally:
    generated.unlink(missing_ok=True)
if failures:
    raise SystemExit('Integrated decision failed at widths: ' + ', '.join(map(str, failures)))
print('PASS: integrated signal journey at 390/1024/1280/1440/1920')
