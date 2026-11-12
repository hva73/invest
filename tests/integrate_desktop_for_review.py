"""Compose the real desktop asset integration onto a temporary demo checkout.

The checkout is isolated in CI. The helper checks exact anchors so upstream
changes fail explicitly instead of silently producing an incomplete merge.
"""
from pathlib import Path

def replace_once(path, old, new):
    path = Path(path)
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f'{path}: expected exactly one integration anchor')
    path.write_text(text.replace(old, new, 1))

anchor = "        body=(ROOT/'static'/path).read_bytes()\n"
replace_once('app.py', anchor,
             anchor + "        if path=='style.css':body+=b'\\n'+(ROOT/'static/desktop-experience.css').read_bytes()\n")
replace_once('apply_update.py', "'static/style.css'",
             "'static/style.css','static/desktop-experience.css'")
anchor = "assert Path(eodhd_capacity.__file__).parent==Path(sys.argv[1])\nprint('INSTALLED_RELEASE_HEALTH_PASS')"
replacement = """assert Path(eodhd_capacity.__file__).parent==Path(sys.argv[1])
status.clear()
css=b''.join(passenger_wsgi.application({'PATH_INFO':'/style.css','REQUEST_METHOD':'GET','REMOTE_ADDR':'test','wsgi.input':io.BytesIO(b'')},lambda s,h:status.append(s)))
assert status==['200 OK'],status
assert (Path(sys.argv[1])/'static/desktop-experience.css').read_bytes() in css
print('INSTALLED_RELEASE_HEALTH_PASS')"""
replace_once('tests/test_updater.py', anchor, replacement)
print('Desktop asset integration applied to temporary demo checkout')
