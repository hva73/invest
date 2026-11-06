"""Synthetic provisional quote remains clearly labelled at desktop and mobile sizes."""
import json, sys, tempfile, threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app, hotwatch_engine as engine, report_ingest
from test_hotwatch_engine import request, tick
from test_intel_workflows import merc_report
from playwright.sync_api import sync_playwright, expect


def main():
    previous = app.DB
    with tempfile.TemporaryDirectory() as directory:
        app.DB = directory + '/db'
        app.init()
        app.create_user('synthetic-browser-password')
        now = engine.utc().replace(microsecond=0)
        report_ingest.save(app.connect, 1, merc_report(True))
        req = request()
        engine.create(app.connect, 1, req, now)
        with app.connect() as con:
            row = con.execute('SELECT id,request FROM hw_sessions').fetchone()
            req = json.loads(row['request'])
            req.update(provider='eodhd', provider_symbol='MERC.US')
            con.execute('UPDATE hw_sessions SET request=? WHERE id=?', (json.dumps(req), row['id']))
            evidence = {'pluto_venue':'NASDAQ','eodhd_venue':'US','currency':'USD','basis':'issuer_ticker_currency_venue'}
            con.execute('INSERT INTO hw_provisional_feed_links VALUES(?,?,?,?)', (row['id'],'MERC.US',json.dumps(evidence),now.isoformat()))
        sample = tick(now)
        sample.update(source='eodhd',market_status='UNKNOWN',session_key='synthetic:UNKNOWN',feed_type='synthetic EODHD quote',bid=None,ask=None)
        engine.ingest(app.connect, 1, req['watch_id'], True, sample, now)
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width':1440,'height':900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator('#login-form [name=password]').fill('synthetic-browser-password')
                page.locator('#login-form button').click()
                page.locator('nav [data-view=hot-watch]').click()
                page.locator('#watch-mode').select_option('true')
                card = page.locator('.engine-list-row')
                expect(card).to_contain_text('INSTRUMENT IKKE BEKRÆFTET')
                expect(card).to_contain_text('100 USD')
                expect(card).to_contain_text('NASDAQ')
                for width in (390,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    card.locator('.dash-action-badge').click()
                    dialog = page.locator('#engine-dialog')
                    expect(dialog).to_contain_text('Identiteten er ikke bekræftet')
                    expect(dialog).to_contain_text('kurserne bruges ikke til signaler')
                    assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
                    page.keyboard.press('Escape')
                    dialog.wait_for(state='hidden')
                assert not errors, errors
                browser.close()
            print('PASS: provisional quote labelled and signals blocked on mobile and desktop')
        finally:
            server.shutdown()
            server.server_close()
            app.DB = previous


if __name__ == '__main__':
    main()
