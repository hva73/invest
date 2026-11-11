"""Responsive navigation smoke test using the real HTML and stylesheet."""
from pathlib import Path
from playwright.sync_api import sync_playwright

html = Path('static/index.html').read_text()
aside = html[html.index('<aside>'):html.index('</aside>')+len('</aside>')]
css = str(Path('static/style.css').resolve())
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for width,height in [(320,700),(390,844),(844,390),(768,1024),(1280,800)]:
        page=browser.new_page(viewport={'width':width,'height':height})
        page.set_content('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'+aside+'<main><div style="height:1800px">Testindhold</div></main>')
        page.add_style_tag(path=css)
        page.emulate_media(reduced_motion='reduce')
        assert page.evaluate("parseFloat(getComputedStyle(document.querySelector('nav button')).transitionDuration)") <= 0.00001
        nav=page.locator('body > aside nav')
        position=nav.evaluate("n=>getComputedStyle(n).position")
        if width<=900:
            assert position=='fixed',(width,position)
            before=nav.bounding_box();page.evaluate('window.scrollTo(0,700)');after=nav.bounding_box()
            assert abs(before['y']-after['y'])<1,(width,before,after)
            assert before['x']>=0 and before['x']+before['width']<=width+1,(width,before)
            assert page.locator('#mobile-more').is_visible()
            assert not page.locator('#admin-nav').is_visible()
            assert not page.locator('#mobile-more-panel').is_visible()
            page.locator('#mobile-more-panel').evaluate("n=>n.classList.add('is-open')")
            assert page.locator('#mobile-more-panel').is_visible()
        else:
            assert position!='fixed',(width,position)
            assert not page.locator('#mobile-more').is_visible()
        page.close()
    browser.close()
print('PASS: mobile, tablet and desktop navigation layout (static fixture)')
