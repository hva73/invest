"""Exercise the actual app with synthetic data and a separately loaded desktop CSS."""
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import app
from playwright.sync_api import expect, sync_playwright
from desktop_fixture import seed
from test_portfolio_value_chart import PortfolioValueChart

case = PortfolioValueChart()
case.setUp()
seed(case)
server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
screens = Path(os.environ.get('ESCAPE_SCREENSHOTS', '/tmp/escape-desktop-screens'))
screens.mkdir(parents=True, exist_ok=True)

try:
    with patch('mcp_client.MCP.request', side_effect=AssertionError('No broker calls')), sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for width in (320, 390, 768, 1024, 1280, 1440, 1920):
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('#login-form [name=password]').fill('test-password-long-enough')
            page.locator('#login-form button').click()
            expect(page.locator('.dashboard-v1')).to_be_visible()
            expect(page.locator('.dash-holdings')).to_contain_text('ALFA')
            expect(page.locator('.dash-holdings')).to_contain_text('DELTA')
            page.locator('[data-dashboard-range=week]').click()
            expect(page.locator('.dash-chart-point')).to_have_count(5)
            before = page.evaluate('''() => {
              const a = document.querySelector('body > aside').getBoundingClientRect();
              const m = document.querySelector('main').getBoundingClientRect();
              return {aside: a.width, main: m.x, nav: getComputedStyle(document.querySelector('nav')).position};
            }''')
            if width in (1280, 1920):
                page.screenshot(path=str(screens / f'overview-before-{width}.png'), full_page=True)
            page.add_style_tag(path=str(Path('static/desktop-experience.css').resolve()))
            if width <= 900:
                after = page.evaluate('''() => {
                  const a = document.querySelector('body > aside').getBoundingClientRect();
                  const m = document.querySelector('main').getBoundingClientRect();
                  return {aside: a.width, main: m.x, nav: getComputedStyle(document.querySelector('nav')).position};
                }''')
                assert before == after, (width, before, after)
                page.locator('nav > [data-view=portfolios]').click()
                expect(page.locator('.portfolio-catalog-heading')).to_be_visible()
                page.locator('nav > [data-view=overview]').click()
                expect(page.locator('.dashboard-v1')).to_be_visible()
            else:
                assert page.locator('body > aside').evaluate('e => e.getBoundingClientRect().width') == 224
                assert page.locator('main').evaluate('e => e.getBoundingClientRect().left') >= 224
                assert page.locator('nav [data-view=overview]').evaluate('e => e.getBoundingClientRect().height') >= 44
                for view, target in [('portfolios', '.portfolio-catalog-heading'), ('hot-watch', '.engine-overview'), ('sectors', '.sector-shell'), ('trade', '.broker-trade'), ('overview', '.dashboard-v1')]:
                    page.locator(f'nav [data-view="{view}"]').click()
                    expect(page.locator(target)).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (width, view)
                    if width == 1440 and view in ('portfolios', 'hot-watch', 'sectors'):
                        page.screenshot(path=str(screens / f'{view}-{width}.png'), full_page=True)
                page.locator('nav [data-view=overview]').focus()
                page.keyboard.press('Tab')
                assert page.evaluate('document.activeElement.matches(":focus-visible")')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width
            if width in (320, 390, 768, 1280, 1920):
                page.screenshot(path=str(screens / f'overview-after-{width}.png'), full_page=True)
            assert not errors, (width, errors)
            page.close()
        browser.close()
    print('PASS: synthetic desktop layouts, navigation and mobile CSS isolation')
finally:
    server.shutdown()
    server.server_close()
    case.tearDown()
