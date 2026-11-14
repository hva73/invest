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
      const approximate=/[1-9]/.test(fraction.slice(12));
      return short ? `${approximate ? '≈ ' : ''}${sign}0,${short}` : `${sign}&lt;0,000000000001`;
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
    const unit = currency === 'DKK' ? 'kr.' : currency;
    const rows = (portfolio?.items || []).filter(item => item.currency === currency && number(item.gross) !== null && number(item.gross_percent) !== null);
    const wins = rows.filter(item => number(item.gross) > 0).length;
    const losses = rows.filter(item => number(item.gross) < 0).length;
    const flat = rows.length - wins - losses;
    const total = totalGross(rows);
    const gains = totalGross(rows.filter(item => number(item.gross) > 0));
    const lost = totalGross(rows.filter(item => number(item.gross) < 0));
    const rate = rows.length ? new Intl.NumberFormat('da-DK', {maximumFractionDigits:2}).format(wins * 100 / rows.length) : '—';
    const hasErrors = Array.isArray(data?.errors) && data.errors.length > 0;
    const diagnosticCodes = Array.isArray(data?.error_codes) ? data.error_codes.filter(code => ['IDENTITY','DIRECT_PERMISSION','DIRECT_REQUEST','DIRECT_PROJECTION','COLLECTION_PERMISSION','COLLECTION_REQUEST','COLLECTION_PROJECTION','PROVIDER_RATE_BUDGET',...['DIRECT_REQUEST','COLLECTION_REQUEST'].flatMap(stage=>['_LOCAL_GUARD','_DENIED','_HTTP','_TIMEOUT','_NETWORK','_RESPONSE'].map(suffix=>stage+suffix))].includes(code)) : [];
    const portfolioOptions = portfolios.map(p => `<option value="${esc(p.portfolio_id)}"${p === portfolio ? ' selected' : ''}>${esc(p.name || 'Depot')}</option>`).join('');
    const currencyOptions = currencies.map(c => `<option value="${esc(c)}"${c === currency ? ' selected' : ''}>${esc(c)}</option>`).join('');
    const options = portfolios.length ? `<div class="statistics-filters"><label>Depot<select data-statistics-portfolio>${portfolioOptions}</select></label>${currency ? `<label>Valuta<select data-statistics-currency>${currencyOptions}</select></label>` : ''}</div>` : '';
    const origin = v => ({signal:'ESCAPE-signal', escape_signal:'ESCAPE-signal', own:'Egen beslutning', manual:'Egen beslutning'}[v] || 'Ikke afklaret');
    const groups = {wins: rows.filter(item => number(item.gross) > 0), losses: rows.filter(item => number(item.gross) < 0), flat: rows.filter(item => number(item.gross) === 0)};
    const group = selected.group === 'wins' || selected.group === 'losses' || selected.group === 'flat' ? selected.group : null;
    const list = (group ? groups[group] : []).map(item => {
      const gross=number(item.gross), percent=number(item.gross_percent), cls=direction(gross);
      const time=item.sell_time && Number.isFinite(Date.parse(item.sell_time)) ? `<span>Udført ${esc(new Date(item.sell_time).toLocaleString('da-DK',{timeZone:'Europe/Copenhagen'}))}</span>` : '<span>Handelstid ikke oplyst</span>';
      // A FIFO sale may combine several purchase prices. Never infer total basis
      // from buy_price, which can represent only the first lot.
      const basis=number(item.cost_basis) !== null ? `${esc(item.cost_basis.replace('.',','))} ${esc(unit)}` : 'Ikke oplyst';
      const proceeds=number(item.sale_proceeds) !== null ? `${esc(item.sale_proceeds.replace('.',','))} ${esc(unit)}` : 'Ikke oplyst';
      const buyNumber=number(item.buy_price);
      const averageBuy=buyNumber !== null ? (buyNumber > 0 && buyNumber < 0.000001 ? `&lt;0,000001 ${esc(unit)}` : `${(item.buy_price.split('.')[1] || '').slice(6).replace(/0/g,'') ? '≈ ' : ''}${esc(new Intl.NumberFormat('da-DK',{minimumFractionDigits:2,maximumFractionDigits:6}).format(buyNumber))} ${esc(unit)}`) : 'Ikke oplyst';
      return `<div class="statistics-trade"><button type="button" class="statistics-trade-button" data-statistics-open aria-haspopup="dialog"><span class="statistics-ticker">${esc(item.ticker)}<small>${esc(item.name)}</small></span><span class="statistics-result ${cls}">${arrow(gross)} ${signed(item.gross)} ${esc(unit)}<small class="${direction(percent)}">${arrow(percent)} ${signed(item.gross_percent)} %</small></span><span aria-hidden="true">›</span></button><dialog class="statistics-dialog" aria-label="Detaljer for ${esc(item.name)}"><header><div><small>AFSLUTTET SALG</small><h3>${esc(item.name)}</h3></div><form method="dialog"><button type="submit" aria-label="Luk">×</button></form></header><div class="statistics-detail"><div class="statistics-calc"><div><span>Solgt mængde</span><strong>${esc(item.quantity)}</strong></div><div><span>Gns. købspris pr. stk.</span><strong>${averageBuy}</strong></div><div><span>Kostpris for solgte andele</span><strong>${basis}</strong></div><div><span>Salgspris pr. stk.</span><strong>${number(item.sell_price) !== null ? esc(item.sell_price.replace('.',','))+' '+esc(unit) : 'Ikke oplyst'}</strong></div><div><span>Salgsbeløb</span><strong>${proceeds}</strong></div><div class="statistics-calc-result"><span>Resultat</span><strong class="${cls}">${arrow(gross)} ${signed(item.gross)} ${esc(unit)} · ${arrow(percent)} ${signed(item.gross_percent)} %</strong></div></div><div class="statistics-detail-note"><span>Køb: ${origin(item.buy_origin)}</span><span>Salg: ${origin(item.sell_origin)}</span>${time}<span>${currency === 'DKK' ? 'Foreløbig kursforskel; købshistorik og omkostninger er ikke fuldt oplyst' : 'Foreløbig kursforskel; købshistorik, omkostninger og valutaveksling er ikke fuldt oplyst'}</span></div></div></dialog></div>`;
    }).join('');
    const note = portfolio?.omitted > 0 ? '<p class="statistics-warning" role="status">Nogle oplysninger mangler; overblikket kan være ufuldstændigt.</p>' : '';
    const value = (part, fallback) => part ? part.text : fallback;
    const result = rows.length && total ? `<div class="statistics-overview"><div class="statistics-summary"><div><small>SAMLET RESULTAT AF SALG</small><strong class="${direction(total.sign)}">${arrow(total.sign)} ${total.text} ${esc(unit)}</strong><span>Foreløbigt · ufuldstændig historik og før ikke-oplyste omkostninger</span></div><div class="statistics-breakdown"><button type="button" data-statistics-group="wins" aria-expanded="${group==='wins'}"><small>SAMLET GEVINST</small><strong class="${wins ? 'positive' : 'neutral'}">${wins ? '↑ ' : '→ '}${value(gains, '0,00')} ${esc(unit)} ⌄</strong></button><button type="button" data-statistics-group="losses" aria-expanded="${group==='losses'}"><small>SAMLET TAB</small><strong class="${losses ? 'negative' : 'neutral'}">${losses ? '↓ ' : '→ '}${value(lost, '0,00')} ${esc(unit)} ⌄</strong></button></div></div><div class="statistics-distribution"><div class="statistics-distribution-head"><div><small>GEVINSTANDEL</small><div class="statistics-win-rate">${rate} %</div></div><span>${rows.length} afsluttede salg</span></div><div class="statistics-distribution-bar" role="img" aria-label="${wins} med gevinst, ${losses} med tab${flat ? ', '+flat+' uden gevinst eller tab' : ''}"><span class="positive" data-statistics-segment="${wins}"></span><span class="negative" data-statistics-segment="${losses}"></span><span class="neutral" data-statistics-segment="${flat}"></span></div><div class="statistics-distribution-legend"><span class="${wins ? 'positive' : 'neutral'}">${wins ? '↑ ' : '→ '}${wins} med gevinst</span><span class="${losses ? 'negative' : 'neutral'}">${losses ? '↓ ' : '→ '}${losses} med tab</span>${flat ? `<button type="button" class="statistics-flat neutral" data-statistics-group="flat" aria-expanded="${group==='flat'}">→ ${flat} uændret ⌄</button>` : ''}</div></div></div>${note}${group ? `<section class="statistics-list"><div class="statistics-list-heading"><h3>${group==='wins'?'Handler med gevinst':group==='losses'?'Handler med tab':'Handler uden gevinst eller tab'}</h3></div>${list || '<p>Ingen handler i denne kategori.</p>'}</section>` : ''}` : '<p class="statistics-empty">Ingen handler med tilstrækkelige oplysninger i dette depot endnu.</p>' + note;
    return `<section class="statistics-view" aria-labelledby="statistics-title"><header class="statistics-heading"><div><small>AFSLUTTEDE HANDLER</small><h2 id="statistics-title">Hvordan står det til<span>?</span></h2><p>Et overblik over de andele, du har solgt.</p></div><button type="button" data-statistics-reload>Opdatér ↻</button></header>${options}${hasErrors ? '<p class="statistics-warning" role="status">Nogle depoter kunne ikke læses. Oversigten er ufuldstændig.'+(diagnosticCodes.length?' ('+diagnosticCodes.join(', ')+')':'')+'</p>' : ''}${result}</section>`;
  }
  function mount(container, load) {
    if (!container || typeof load !== 'function') throw new TypeError('statistics mount requires a container and loader');
    let data = null, selected = {};
    const draw = () => { container.innerHTML = render(data, selected); container.querySelectorAll('[data-statistics-segment]').forEach(el => { el.style.flexGrow = el.dataset.statisticsSegment; }); };
    const refresh = async () => {
      container.innerHTML = '<p role="status">Henter handelshistorik…</p>';
      try { data = await load(); }
      catch (error) {
        const allowed=['DATABASE','CONNECTION','BROKER_CATALOG','CATALOG_BUDGET','CATALOG_DATABASE','CATALOG_DENIED','CATALOG_RATE_LIMIT','CATALOG_HTTP','CATALOG_TIMEOUT','CATALOG_NETWORK','CATALOG_RESPONSE','UNEXPECTED'];
        const category=allowed.includes(error?.details?.diagnostic)?error.details.diagnostic:'REQUEST';
        container.innerHTML = '<p role="alert">Handelshistorikken kunne ikke hentes. Prøv igen. ('+category+')</p><button type="button" data-statistics-reload>Prøv igen</button>';
        return;
      }
      try { draw(); }
      catch (_) { container.innerHTML = '<p role="alert">Handelshistorikken kunne ikke vises. Prøv igen. (DISPLAY)</p><button type="button" data-statistics-reload>Prøv igen</button>'; }
    };
    container.addEventListener('change', event => {
      if (event.target.matches('[data-statistics-portfolio]')) { selected={portfolio:event.target.value}; draw(); }
      if (event.target.matches('[data-statistics-currency]')) { selected.currency=event.target.value; draw(); }
    });
    container.addEventListener('click', event => { const button=event.target.closest('[data-statistics-group]'), open=event.target.closest('[data-statistics-open]'); if (button) { const which=button.dataset.statisticsGroup; selected.group=selected.group===which?null:which; draw(); container.querySelector('[data-statistics-group="'+which+'"]')?.focus(); } else if (open) { const dialog=open.parentElement.querySelector('dialog'); if (dialog && !dialog.open) dialog.showModal(); } else if (event.target.closest('[data-statistics-reload]')) refresh(); });
    return refresh();
  }
  root.StatisticsUI = {render, mount};
  if (typeof module !== 'undefined') module.exports = root.StatisticsUI;
})(typeof window === 'undefined' ? globalThis : window);
