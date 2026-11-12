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
                if width >= 1280:
                    hero_height = page.locator('.dash-hero').evaluate('e => e.getBoundingClientRect().height')
                    assert hero_height < 450, (width, hero_height)
                    expect(page.locator('.dash-holdings')).to_be_visible()
                    expect(page.locator('.dash-holdings thead')).to_contain_text('I dag')
                    expect(page.locator('.dash-holdings thead')).to_contain_text('Siden køb')
                    alfa=page.locator('.dash-holdings .dash-row').filter(has_text='ALFA')
                    expect(alfa.locator('.dash-desktop-entry')).to_contain_text('Gns. køb')
                    expect(alfa.locator('.dash-day-desktop')).to_contain_text('estimat')
                    expect(alfa.locator('.dash-pnl')).to_contain_text('%')
                    intro = page.locator('.dash-hero-intro').bounding_box()
                    chart = page.locator('.dash-hero-top #dashboard-value-chart').bounding_box()
                    metrics = page.locator('.dash-hero-metrics').bounding_box()
                    assert intro['x'] + intro['width'] <= metrics['x'] + 1, (width, intro, metrics)
                    assert chart['y'] >= max(intro['y'] + intro['height'], metrics['y'] + metrics['height']) - 1, (width, intro, metrics, chart)
                    assert chart['width'] > metrics['width'], (width, chart, metrics)
                    empty_alert = page.locator('.dash-attention')
                    expect(empty_alert).to_contain_text('Ingen aktuelle')
                    assert empty_alert.evaluate('e => e.getBoundingClientRect().height') < 120, width
                    expect(empty_alert.locator('[data-view="hot-watch"]')).to_be_visible()
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
                    if view == 'portfolios' and width >= 1280:
                        assert page.locator('.portfolio-catalog-heading').evaluate('e => e.getBoundingClientRect().height') < 180, width
                    if view == 'sectors':
                        expect(page.locator('.si-hero-chart #dashboard-value-chart')).to_be_visible()
                        expect(page.locator('.sector-layout')).to_be_visible()
                        result_chart = page.locator('.si-results .si-bars')
                        if result_chart.count():
                            assert result_chart.evaluate('e => e.getBoundingClientRect().height') <= 220, width
                            zero_y = page.locator('.si-results .si-zero-line').bounding_box()['y']
                            up_bar = page.locator('.si-results .si-bar.up').first
                            if up_bar.count():
                                rect = up_bar.bounding_box()
                                assert abs((rect['y'] + rect['height']) - zero_y) <= 2, (width, rect, zero_y)
                            down_bar = page.locator('.si-results .si-bar.down').first
                            if down_bar.count():
                                assert abs(down_bar.bounding_box()['y'] - zero_y) <= 2, width
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
                        buy_row = page.locator('.engine-list-row[data-engine-category="BUY"]')
                        sell_row = page.locator('.engine-list-row[data-engine-category="SELL"]')
                        expect(buy_row.locator('.dash-action-badge')).to_be_visible()
                        expect(sell_row.locator('.dash-action-badge')).to_be_visible()
                        assert buy_row.evaluate('e => getComputedStyle(e).borderLeftWidth') == '3px'
                        assert sell_row.evaluate('e => getComputedStyle(e).borderLeftWidth') == '3px'
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
            assert not errors, (width, errors)
            page.close()
        browser.close()
    print('PASS: synthetic desktop layouts, navigation and mobile CSS isolation')
finally:
    server.shutdown()
    server.server_close()
    case.tearDown()

