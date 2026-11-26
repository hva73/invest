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

class DesktopTestHandler(app.Handler):
    """Serve only the unintegrated stylesheet in addition to the real app routes."""
    def _get(self):
        if self.path == '/desktop-experience.css':
            return self.send(200, Path('static/desktop-experience.css').read_bytes(), 'text/css')
        return super()._get()


def desktop_geometry(page):
    return page.evaluate("""() => {
        const aside = document.querySelector('body > aside').getBoundingClientRect();
        const main = document.querySelector('main').getBoundingClientRect();
        const nav = document.querySelector('nav [data-view=overview]').getBoundingClientRect();
        return [aside.width, main.left, main.width, nav.width, nav.height];
    }""")


def review_release_status(page):
    """Run with --release-status after integrating the #263 gen2 frontend."""
    status_path = '**/escape-release/status.json'
    overlay = page.locator('#release-overlay')
    expect(overlay).to_be_attached()
    before = desktop_geometry(page)
    state = 'maintenance'
    status = 404
    sent = []

    def public_status(route):
        route.fulfill(status=status, json={'state': state}, headers={'Cache-Control': 'no-store'})

    def reject_trade(route):
        sent.append(route.request.method)
        route.abort()

    page.route(status_path, public_status)
    page.route('**/api/trade/send', reject_trade)
    for status in (404, 503):
        message = f'Fixture HTTP {status}'
        page.route('**/api/state', lambda route: route.fulfill(status=status, json={'error': message}))
        try:
            assert page.evaluate("""async () => {
                try { await api('state'); }
                catch (error) { return [error.status, error.message]; }
            }""") == [status, message]
            # A failed status response must not turn the API error into maintenance.
            page.evaluate('() => checkReleaseStatus()')
            expect(overlay).to_be_hidden()
        finally:
            page.unroute('**/api/state')

    status = 200
    # The first send must discover maintenance in preflight, and the second is stale.
    for _ in range(2):
        assert page.evaluate("""async () => {
            try { await api('trade/send', {}); }
            catch (error) { return error.message; }
        }""") == 'ESCAPE er midlertidigt utilgængelig.'
        assert not sent, sent
    expect(overlay).to_be_visible()
    expect(overlay.locator('#release-title')).to_have_text('Vi opdaterer ESCAPE')
    expect(overlay.locator('#release-reconnect')).to_have_text('Forbindelsen genoprettes automatisk.')
    page.keyboard.press('Escape')
    expect(overlay).to_be_visible()
    assert page.locator('nav [data-view=portfolios]').evaluate(
        'button => !button.dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true}))'
    )
    expect(page.locator('.dashboard-v1')).to_be_visible()
    assert desktop_geometry(page) == before

    # Publishing normal must let the scheduled probe reload the authenticated page.
    with page.expect_event('framenavigated', predicate=lambda frame: frame == page.main_frame,
                           timeout=20000):
        state = 'normal'
    expect(overlay).to_be_hidden()
    expect(page.locator('.dashboard-v1')).to_be_visible()
    expect(page.locator('.dash-holdings')).to_contain_text('ALFA')
    assert desktop_geometry(page) == before
    assert not sent, sent
    print('PASS: #263 desktop maintenance, HTTP errors, stale action and automatic recovery')


external_review = os.environ.get('ESCAPE_DESKTOP_EXTERNAL_REVIEW') == '1'
case = PortfolioValueChart()
case.setUp()
seed(case)
server = app.ThreadingHTTPServer(('127.0.0.1', 0), DesktopTestHandler)
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
            if page.locator('[data-dashboard-range=week]').is_visible():
                page.locator('[data-dashboard-range=week]').click()
                assert page.locator('.dash-chart-point').count() >= (2 if width < 700 else 70)
            else:
                expect(page.locator('.mobile-holdings')).to_be_visible()
            before = page.evaluate('''() => {
              const a = document.querySelector('body > aside').getBoundingClientRect();
              const m = document.querySelector('main').getBoundingClientRect();
              return {aside: a.width, main: m.x, nav: getComputedStyle(document.querySelector('nav')).position};
            }''')
            if external_review:
                if width in (1280, 1920):
                    page.screenshot(path=str(screens / f'overview-before-{width}.png'), full_page=True)
                page.evaluate('''() => new Promise((resolve, reject) => {
                  const link = document.createElement('link');
                  link.rel = 'stylesheet'; link.href = '/desktop-experience.css';
                  link.onload = resolve; link.onerror = () => reject(new Error('Desktop stylesheet failed to load'));
                  document.head.append(link);
                })''')
            else:
                response = page.request.get(f'http://127.0.0.1:{server.server_port}/style.css')
                assert response.ok and Path('static/desktop-experience.css').read_text() in response.text()
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
                # Explicit fixture responses make the screenshot exercise actual
                # rendered signal rows; no engine or broker operation is made.
                def sessions_route(route):
                    rows = [] if 'view=history' in route.request.url else [
                        {'watch_id': 'fixture-buy', 'watch_kind': 'candidate', 'status': 'ACTIVE',
                         'signal': 'BUY', 'display_status': 'KØBSSIGNAL',
                         'request': {'ticker': 'ALFA', 'exchange': 'TEST', 'provider': 'synthetic', 'quote_currency': 'DKK'},
                         'last_calculation_at': case.now.isoformat(), 'data_status': {'price': '1000', 'price_status': 'FRESH'},
                         'latest_calculation': {'signal': 'BUY', 'reason_codes': ['SYNTHETIC'] }},
                        {'watch_id': 'fixture-sell', 'watch_kind': 'candidate', 'status': 'ACTIVE',
                         'signal': 'SELL', 'display_status': 'SÆLGSSIGNAL',
                         'request': {'ticker': 'BETA', 'exchange': 'TEST', 'provider': 'synthetic', 'quote_currency': 'DKK'},
                         'last_calculation_at': case.now.isoformat(), 'data_status': {'price': '500', 'price_status': 'FRESH'},
                         'latest_calculation': {'signal': 'SELL', 'reason_codes': ['SYNTHETIC'] }}]
                    route.fulfill(json={'sessions': rows, 'kill_switch': {'killed': False}, 'worker': None,
                                        'discovery_attempts': [], 'truncated': False})
                page.route('**/api/v1/hotwatch/sessions?*', sessions_route)
                for view, target in [('portfolios', '.portfolio-catalog-heading'), ('hot-watch', '.engine-overview'), ('sectors', '.sector-shell'), ('trade', '.broker-trade'), ('overview', '.dashboard-v1')]:
                    page.locator(f'nav [data-view="{view}"]').click()
                    expect(page.locator(target)).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (width, view)
                    if view == 'portfolios' and width >= 1100:
                        card = page.locator('.portfolio-card-root').first
                        name = card.locator(':scope > h2').bounding_box()
                        preview = card.locator(':scope > .portfolio-preview').bounding_box()
                        badge = card.locator(':scope > .badge').bounding_box()
                        assert name['x'] + name['width'] <= preview['x'] + 1, (width, name, preview)
                        assert badge['height'] < 60, (width, badge)
                        assert card.locator('[data-open-portfolio]').first.is_visible()
                    if view == 'hot-watch':
                        expect(page.locator('.engine-list-row')).to_have_count(2)
                        expect(page.locator('.engine-list-row').first).to_contain_text('KØBSSIGNAL')
                        expect(page.locator('.engine-list-row').last).to_contain_text('SÆLGSSIGNAL')
                        page.locator('[data-engine-filter=BUY]').click()
                        expect(page.locator('.engine-list-row:visible')).to_have_count(1)
                        page.locator('[data-engine-filter=all]').click()
                        expect(page.locator('.engine-list-row:visible')).to_have_count(2)
                    if width in (1024, 1280, 1440, 1920) and view in ('portfolios', 'hot-watch', 'sectors'):
                        page.screenshot(path=str(screens / f'{view}-{width}.png'), full_page=True)
                page.locator('nav [data-view=overview]').focus()
                page.keyboard.press('Tab')
                assert page.evaluate('document.activeElement.matches(":focus-visible")')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width
            if width in (320, 390, 768, 1024, 1280, 1440, 1920):
                page.screenshot(path=str(screens / f'overview-after-{width}.png'), full_page=True)
            if width == 1440 and '--release-status' in sys.argv:
                review_release_status(page)
            assert not errors, (width, errors)
            page.close()
        browser.close()
    print('PASS: synthetic desktop layouts, navigation and mobile CSS isolation')
finally:
    server.shutdown()
    server.server_close()
    case.tearDown()

