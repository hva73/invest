/* Trading statistics UI. Only displays the read-only, explicitly incomplete
   projection provided by /api/realized-statistics. */
(function (root) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => {
    if (typeof value !== 'string' || !/^-?\d+(?:\.\d+)?$/.test(value)) return null;
    const n = Number(value);
    return Number.isFinite(n) && Math.abs(n) < 1e15 ? n : null;
  };
  function signed(value) {
    const n=number(value), sign=n>0?'+':n<0?'−':'';
    if (n !== 0 && Math.abs(n) < 0.01) {
      const fraction=value.replace(/^-/, '').split('.')[1] || '';
      const short=fraction.slice(0,12).replace(/0+$/, '');
      return short ? `${sign}0,${short}` : `${sign}&lt;0,000000000001`;
    }
    return sign+new Intl.NumberFormat('da-DK', {minimumFractionDigits:2, maximumFractionDigits:2}).format(Math.abs(n));
  }
  function totalGross(rows) {
    const parts = rows.map(item => {
      const value = item.gross, negative = value.startsWith('-');
      const [whole, fraction = ''] = (negative ? value.slice(1) : value).split('.');
      return {negative, whole, fraction};
    });
    const scale = Math.max(2, ...parts.map(part => part.fraction.length));
    // Quantities and prices can each have up to 90 leading fractional zeros;
    // their product can therefore need roughly twice as many decimal places.
    if (scale > 220) return null;
    const total = parts.reduce((sum, part) => {
      const magnitude = BigInt(part.whole + part.fraction.padEnd(scale, '0'));
      return sum + (part.negative ? -magnitude : magnitude);
    }, 0n);
    const magnitude = total < 0n ? -total : total;
    const digits=magnitude.toString().padStart(scale+1,'0');
    const raw=(total<0n?'-':'')+digits.slice(0,-scale)+'.'+digits.slice(-scale);
    const sign=total>0n?1:total<0n?-1:0;
    if (magnitude < 10n ** BigInt(scale-2)) return {sign, text:signed(raw)};
    const unit=10n ** BigInt(scale-2), cents=(magnitude+unit/2n)/unit;
    const whole=new Intl.NumberFormat('da-DK').format(cents/100n), fraction=(cents%100n).toString().padStart(2,'0');
    return {sign,text:`${sign>0?'+':sign<0?'−':''}${whole},${fraction}`};
  }
  const direction = n => n > 0 ? 'positive' : n < 0 ? 'negative' : 'neutral';
  const arrow = n => n > 0 ? '↑' : n < 0 ? '↓' : '→';
  function currencyList(portfolio) {
    return [...new Set((portfolio?.items || []).map(item => item.currency).filter(value => typeof value === 'string' && /^[A-Z]{3}$/.test(value)))].sort();
  }
  function render(data, selected = {}) {
    const portfolios = Array.isArray(data?.portfolios) ? data.portfolios : [];
    const portfolio = portfolios.find(p => String(p.portfolio_id) === String(selected.portfolio)) || portfolios[0];
    const currencies = currencyList(portfolio);
    const currency = currencies.includes(selected.currency) ? selected.currency : currencies[0];
    const rows = (portfolio?.items || []).filter(item => item.currency === currency && number(item.gross) !== null && number(item.gross_percent) !== null);
    const wins = rows.filter(item => number(item.gross) > 0).length;
    const losses = rows.filter(item => number(item.gross) < 0).length;
    const total = totalGross(rows);
    const hasErrors = Array.isArray(data?.errors) && data.errors.length > 0;
    const portfolioOptions = portfolios.map(p => `<option value="${esc(p.portfolio_id)}"${p === portfolio ? ' selected' : ''}>${esc(p.name || 'Depot')}</option>`).join('');
    const currencyOptions = currencies.map(c => `<option value="${esc(c)}"${c === currency ? ' selected' : ''}>${esc(c)}</option>`).join('');
    const groups = {wins: rows.filter(item => number(item.gross) > 0), losses: rows.filter(item => number(item.gross) < 0)};
    const group = selected.group === 'wins' || selected.group === 'losses' ? selected.group : null;
    const origin = value => value === 'signal' ? 'ESCAPE-signal' : value === 'manual' ? 'Egen beslutning' : 'Ikke afklaret';
    const list = (group ? groups[group] : []).map(item => {
      const gross=number(item.gross), percent=number(item.gross_percent), cls=direction(gross);
      const time=item.sell_time ? `<span>Udført ${esc(new Date(item.sell_time).toLocaleString('da-DK'))}</span>` : '<span>Fyldtid ikke oplyst</span>';
      // A FIFO sale may combine several purchase prices. Never infer total basis
      // from buy_price, which can represent only the first lot.
      const basis=number(item.basis) !== null ? `${esc(item.basis)} ${esc(currency)}` : 'Ikke oplyst';
      const proceeds=number(item.proceeds) !== null ? `${esc(item.proceeds)} ${esc(currency)}` : 'Ikke oplyst';
      return `<div class="statistics-trade"><button type="button" class="statistics-trade-button" data-statistics-open aria-haspopup="dialog"><span class="statistics-ticker">${esc(item.ticker)}<small>${esc(item.name)}</small></span><span class="statistics-result ${cls}">${arrow(gross)} ${signed(item.gross)} ${esc(currency)}<small class="${direction(percent)}">${arrow(percent)} ${signed(item.gross_percent)} %</small></span><span aria-hidden="true">›</span></button><dialog class="statistics-dialog" aria-label="Detaljer for ${esc(item.name)}"><header><div><small>AFSLUTTET SALG</small><h3>${esc(item.name)}</h3></div><form method="dialog"><button type="submit" aria-label="Luk">×</button></form></header><div class="statistics-detail"><span>Solgt mængde ${esc(item.quantity)}</span><span>Kostpris for solgte andele ${basis}</span><span>Salgspris pr. stk. ${esc(item.sell_price)} ${esc(currency)}</span><span>Salgsbeløb ${proceeds}</span><span class="${cls}">Resultat ${arrow(gross)} ${signed(item.gross)} ${esc(currency)} · ${arrow(percent)} ${signed(item.gross_percent)} %</span><span>Køb: ${origin(item.buy_origin)}</span><span>Salg: ${origin(item.sell_origin)}</span>${time}<span>${esc(item.note)}</span></div></dialog></div>`;
    }).join('');
    const options = portfolios.length ? `<div class="statistics-filters"><label>Depot<select data-statistics-portfolio>${portfolioOptions}</select></label>${currency ? `<label>Valuta<select data-statistics-currency>${currencyOptions}</select></label>` : ''}</div>` : '';
    const winTotal=totalGross(groups.wins), lossTotal=totalGross(groups.losses);
    const winRate=rows.length ? (100*wins/rows.length) : 0;
    const result = rows.length && total ? `<div class="statistics-summary"><div><small>RESULTAT AF AFSLUTTEDE SALG</small><strong class="${direction(total.sign)}">${arrow(total.sign)} ${total.text} ${esc(currency)}</strong><span>Foreløbigt · før manglende omkostninger · ${rows.length} observerede salg</span></div><div class="statistics-totals"><button type="button" data-statistics-group="wins" aria-expanded="${group==='wins'}"><span>Samlede gevinster</span><strong class="positive">↑ ${winTotal.text} ${esc(currency)} ⌄</strong></button><button type="button" data-statistics-group="losses" aria-expanded="${group==='losses'}"><span>Samlede tab</span><strong class="negative">↓ ${lossTotal.text} ${esc(currency)} ⌄</strong></button></div></div><div class="statistics-distribution"><div><strong>Sådan fordeler det sig</strong><span>${new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(winRate)} % med gevinst</span></div><div class="statistics-bar" aria-label="${wins} med gevinst, ${losses} med tab"><i style="flex:${wins}"></i><b style="flex:${losses}"></b></div><div class="statistics-counts"><span class="positive">↑ ${wins} med gevinst</span><span class="negative">↓ ${losses} med tab</span></div></div>${group ? `<div class="statistics-list"><h3>${group==='wins'?'Handler med gevinst':'Handler med tab'}</h3>${list || '<p>Ingen handler i denne kategori.</p>'}</div>` : ''}` : '<p class="statistics-empty">Ingen handler med tilstrækkelige oplysninger i dette depot endnu.</p>';
    return `<section class="statistics-view" aria-labelledby="statistics-title"><header class="statistics-heading"><div><small>DIT HANDELSOVERBLIK</small><h2 id="statistics-title">Hvordan står det til<span>?</span></h2><p>Se de handler, der kan sammenlignes ud fra Plutos oplysninger.</p></div><button type="button" data-statistics-reload>Opdatér ↻</button></header>${options}${hasErrors ? '<p class="statistics-warning" role="status">Nogle depoter kunne ikke læses. Oversigten er ufuldstændig.</p>' : ''}${result}</section>`;
  }
  function mount(container, load) {
    if (!container || typeof load !== 'function') throw new TypeError('statistics mount requires a container and loader');
    let data = null, selected = {};
    const draw = () => { container.innerHTML = render(data, selected); };
    const refresh = async () => {
      container.innerHTML = '<p role="status">Henter handelshistorik…</p>';
      try { data = await load(); draw(); }
      catch (_) { container.innerHTML = '<p role="alert">Handelshistorikken kunne ikke hentes. Prøv igen.</p><button type="button" data-statistics-reload>Prøv igen</button>'; }
    };
    container.addEventListener('change', event => {
      if (event.target.matches('[data-statistics-portfolio]')) { selected={portfolio:event.target.value}; draw(); }
      if (event.target.matches('[data-statistics-currency]')) { selected.currency=event.target.value; draw(); }
    });
    container.addEventListener('click', event => { const button=event.target.closest('[data-statistics-group]'); const open=event.target.closest('[data-statistics-open]'); if (button) { selected.group = selected.group === button.dataset.statisticsGroup ? null : button.dataset.statisticsGroup; draw(); } else if (open) { const dialog=open.parentElement.querySelector('dialog'); if (dialog && !dialog.open) dialog.showModal(); } else if (event.target.closest('[data-statistics-reload]')) refresh(); });
    return refresh();
  }
  root.StatisticsUI = {render, mount};
  if (typeof module !== 'undefined') module.exports = root.StatisticsUI;
})(typeof window === 'undefined' ? globalThis : window);
