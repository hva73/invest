"""Synthetic missing-cost sale must remain visible and openable at both sizes."""
from pathlib import Path  # Resolve the checked-out UI under test.
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width in (390, 1440):
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.set_content('<main id="statistics"></main>')
        page.add_script_tag(path=str(Path('static/statistics-ui.js').resolve()))
        page.evaluate('''() => StatisticsUI.mount(document.querySelector('#statistics'), async () => ({
          portfolios:[{portfolio_id:1,name:'Fiktivt depot',items:[],omitted:1,
            unresolved_sales:[{ticker:'TEST',name:'Fiktiv aktie',currency:'USD',quantity:'2',sell_price:'12',sale_proceeds:'24'}]}],errors:[]
        }))''')
        assert page.get_by_text('1 salg uden fuldt DKK-resultat').is_visible()
        assert page.locator('[data-statistics-currency]').count()==0
        assert '—' in page.locator('.st-total').inner_text()
        page.locator('.st-coverage').click()
        page.locator('dialog:modal [data-statistics-trade]').click()
        dialog=page.get_by_role('dialog',name='Detaljer for Fiktiv aktie')
        assert dialog.is_visible() and dialog.get_by_text('Resultat ikke afklaret').is_visible()
        assert dialog.get_by_text('Kostpris, solgte andele').is_visible()
        assert dialog.get_by_text('+24,00 USD',exact=True).is_visible()
        dialog.get_by_role('button',name='Luk').click()
        assert not dialog.is_visible()
        page.close()
    browser.close()
print('Missing cost browser PASS: 390, 1440')
