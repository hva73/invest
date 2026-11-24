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
    return [...new Set([...(portfolio?.items || []), ...(portfolio?.unresolved_sales || [])].map(item => item.currency).filter(value => typeof value === 'string' && /^[A-Z]{3}$/.test(value)))].sort();
  }
  function render(data, selected = {}) {
    const portfolios=Array.isArray(data?.portfolios)?data.portfolios:[];
    const chosen=portfolios.find(p=>String(p.portfolio_id)===String(selected.portfolio));
    const all=(chosen?[chosen]:portfolios).flatMap(p=>[...(p.items||[]),...(p.unresolved_sales||[])].map(r=>({...r,portfolio_name:p.name})));
    const dkk=r=>number(r.display_gross_dkk??(r.currency==='DKK'?r.gross:null));
    const resolved=all.filter(r=>number(r.gross)!==null),priced=resolved.filter(r=>dkk(r)!==null);
    const wins=resolved.filter(r=>number(r.gross)>0),losses=resolved.filter(r=>number(r.gross)<0),flat=resolved.filter(r=>number(r.gross)===0);
    const unknown=all.filter(r=>number(r.gross)===null||dkk(r)===null);
    const sum=rows=>{const valid=rows.filter(r=>dkk(r)!==null);return valid.length?totalGross(valid.map(r=>({gross:r.display_gross_dkk??r.gross}))):null;};
    const money=n=>n?`${n.text} kr.`:'—';
    const total=sum(priced),gain=wins.length?sum(wins):{sign:0,text:'0,00'},loss=losses.length?sum(losses):{sign:0,text:'0,00'};
    const pct=n=>new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(n)+' %';
    const rate=resolved.length?wins.length/resolved.length*100:null;
    const origin=v=>({signal:'ESCAPE-signal',escape_signal:'ESCAPE-signal',probable_signal:'Sandsynligt signal',own:'Egen beslutning',manual:'Egen beslutning',agent:'AI-agent'}[v]||'Ikke afklaret');
    const source=r=>['signal','escape_signal'].includes(r.sell_origin)?'signal':['own','manual'].includes(r.sell_origin)?'own':'unknown';
    const groups={all,wins,losses,flat,unresolved:unknown,signal:all.filter(r=>source(r)==='signal'),own:all.filter(r=>source(r)==='own'),unknown:all.filter(r=>source(r)==='unknown')};
    const names={all:'Afsluttede salg',wins:'Handler med gevinst',losses:'Handler med tab',flat:'Uændrede handler',unresolved:'Salg uden fuldt DKK-resultat',signal:'ESCAPE-signal',own:'Egne beslutninger',unknown:'Ikke afklaret'};
    const native=(v,c)=>number(v)===null?'Ikke oplyst':`${signed(v)} ${esc(c)}`;
    const displayResult=r=>dkk(r)!==null?money(sum([r])):number(r.gross)!==null?`${signed(r.gross)} ${esc(r.currency)}`:'Ikke afklaret';
    const row=(r)=>`<button type="button" class="st-sale" data-statistics-trade="${all.indexOf(r)}"><span><strong>${esc(r.ticker)}</strong><small>${esc(r.name)}</small><small>Salg · ${origin(r.sell_origin)}</small></span><span class="${direction(dkk(r))}"><strong>${displayResult(r)}</strong><small>${number(r.gross_percent)===null?'':signed(r.gross_percent)+' %'}</small></span><span aria-hidden="true">›</span></button>`;
    const head=(title,kicker='AFSLUTTEDE HANDLER')=>`<header><div><small>${kicker}</small><h3>${esc(title)}</h3></div><form method="dialog"><button type="submit" aria-label="Luk">×</button></form></header>`;
    const dialog=(r,i)=>{const fx=r.display_fx;return `<dialog class="statistics-dialog" data-statistics-detail="${i}" aria-label="Detaljer for ${esc(r.name)}">${head(r.name,'AFSLUTTET SALG')}<div class="statistics-detail"><div class="st-detail-hero ${direction(dkk(r))}">${displayResult(r)}<small>${number(r.gross_percent)===null?'Resultat ikke afklaret':signed(r.gross_percent)+' %'}</small></div><div class="statistics-calc"><div><span>Depot</span><strong>${esc(r.portfolio_name)}</strong></div><div><span>Solgt mængde</span><strong>${esc(r.quantity)}</strong></div><div><span>Gns. købspris</span><strong>${native(r.buy_price,r.currency)}</strong></div><div><span>Salgspris</span><strong>${native(r.sell_price,r.currency)}</strong></div><div><span>Kostpris, solgte andele</span><strong>${native(r.cost_basis,r.currency)}</strong></div><div><span>Salgsbeløb</span><strong>${native(r.sale_proceeds,r.currency)}</strong></div><div><span>Resultat i handelsvaluta</span><strong>${native(r.gross,r.currency)}</strong></div><div><span>Køb</span><strong>${origin(r.buy_origin)}</strong></div><div><span>Salg</span><strong>${origin(r.sell_origin)}</strong></div></div><div class="statistics-detail-note">${r.buy_origin_evidence?`<span>Køb · ${esc(r.buy_origin_evidence)}</span>`:''}${r.sell_origin_evidence?`<span>Salg · ${esc(r.sell_origin_evidence)}</span>`:''}<span>${fx&&r.currency!=='DKK'?`DKK-estimat: 1 ${esc(r.currency)} = ${esc(fx.rate)} kr. · ${esc(fx.source)} · ${esc(fx.as_of)}. Omregnet med referencekurs, ikke historisk afregningskurs.`:r.currency==='DKK'?'Handlet i DKK.':'DKK-omregning mangler en gyldig valutakurs.'}</span><span>Foreløbigt før ikke-oplyste omkostninger. Kun solgte andele.</span>${r.sell_time?`<span>Udført ${esc(new Date(r.sell_time).toLocaleString('da-DK',{timeZone:'Europe/Copenhagen'}))}</span>`:'<span>Præcist udførelsestidspunkt er ikke oplyst.</span>'}</div></div></dialog>`;};
    const lists=Object.entries(groups).map(([key,rows])=>`<dialog class="statistics-dialog st-list-dialog" data-statistics-list="${key}" aria-label="${names[key]}">${head(names[key])}<div class="st-list-caption">${rows.length} salg · ${money(sum(rows))}</div>${rows.map(row).join('')||'<p>Ingen salg i denne gruppe.</p>'}</dialog>`).join('');
    const sources=[['signal','ESCAPE-signal'],['own','Egne beslutninger'],['unknown','Ikke afklaret']].map(([key,label])=>{const rows=groups[key],s=sum(rows);return `<button type="button" class="st-source" data-statistics-show-group="${key}"><span>${label}<small>${rows.length} salg</small></span><strong class="${direction(s?.sign)}">${money(s)}</strong><span aria-hidden="true">›</span></button>`;}).join('');
    const filters=portfolios.length>1?`<label class="st-depot">Depot<select data-statistics-portfolio><option value="all">Alle depoter</option>${portfolios.map(p=>`<option value="${esc(p.portfolio_id)}"${p===chosen?' selected':''}>${esc(p.name)}</option>`).join('')}</select></label>`:'';
    const coverage=unknown.length?`<button class="st-coverage" data-statistics-show-group="unresolved">${unknown.length} salg uden fuldt DKK-resultat <span>›</span></button>`:'';
    const chart=resolved.length?`<svg viewBox="0 0 120 120" class="st-ring" role="img" aria-label="${wins.length} med gevinst, ${losses.length} med tab, ${flat.length} uændrede"><circle class="st-ring-base" cx="60" cy="60" r="49"/><circle class="st-ring-win" cx="60" cy="60" r="49" pathLength="100" stroke-dasharray="${wins.length/resolved.length*100} 100"/><circle class="st-ring-loss" cx="60" cy="60" r="49" pathLength="100" stroke-dasharray="${losses.length/resolved.length*100} 100" stroke-dashoffset="${-wins.length/resolved.length*100}"/><text x="60" y="60" text-anchor="middle" dominant-baseline="central">${pct(rate)}</text><text class="st-ring-label" x="60" y="78" text-anchor="middle" dominant-baseline="central">med gevinst</text></svg>`:'<span class="st-no-result">—</span>';
    return `<section class="statistics-view st-compact" aria-labelledby="statistics-title"><header class="statistics-heading"><div><small>AFSLUTTEDE HANDLER</small><h2 id="statistics-title">Hvordan står det til<span>?</span></h2><p>Kun de andele, du har solgt.</p></div><button type="button" data-statistics-reload aria-label="Opdatér handelshistorik">↻</button></header>${filters}<div class="st-overview"><section class="st-panel st-result"><small>SAMLET RESULTAT</small><button type="button" class="st-total ${direction(total?.sign)}" data-statistics-show-group="all">${money(total)} <span>↗</span></button><span class="st-subtitle">${priced.length} af ${all.length} salg · omregnet til DKK</span><div class="st-gains"><button type="button" data-statistics-show-group="wins"><span>Gevinster</span><strong class="positive">${money(gain)}</strong><small>${wins.length} salg <b>›</b></small></button><button type="button" data-statistics-show-group="losses"><span>Tab</span><strong class="negative">${money(loss)}</strong><small>${losses.length} salg <b>›</b></small></button></div></section><button type="button" class="st-panel st-distribution" data-statistics-show-group="all">${chart}<span class="st-legend"><span><i class="st-dot win"></i>${wins.length} med gevinst</span><span><i class="st-dot loss"></i>${losses.length} med tab</span>${flat.length?`<span>${flat.length} uændrede</span>`:''}</span></button></div>${coverage}${data?.errors?.length?'<p class="statistics-warning">Nogle depoter kunne ikke hentes. Oversigten er ufuldstændig.</p>':''}<section class="st-panel st-sources"><div class="st-section-title"><h3>Algoritmen og dig</h3><button type="button" data-statistics-info aria-label="Om resultat og herkomst">ⓘ</button></div>${sources}</section><button class="st-all-sales" data-statistics-show-group="all">Se alle ${all.length} salg <span>→</span></button>${lists}${all.map(dialog).join('')}<dialog class="statistics-dialog" data-statistics-about aria-label="Om resultat og herkomst">${head('Om tallene')}<div class="statistics-detail"><p>Resultaterne er foreløbige kursforskelle for solgte andele, før ukendte omkostninger. Referencekurser fra samme valutagrundlag som Sector Intelligence bruges til DKK-visningen. Det er et omregnet overblik, ikke historisk nettoafregning i DKK.</p><p>Gevinstandelen omfatter ${resolved.length} salg med kendt resultat i handelsvaluta. DKK-totalen omfatter ${priced.length} af ${all.length} salg. Manglende købshistorik eller valutakurs tæller ikke som nul.</p><p>Køb og salg verificeres hver for sig. Ukendt ophav indgår hverken som ESCAPE-signal eller egen beslutning. AI-agent-mærket alene dokumenterer ikke et algoritmesignal.</p></div></dialog></section>`;
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
    container.addEventListener('click', event => {
      const group=event.target.closest('[data-statistics-show-group]'), trade=event.target.closest('[data-statistics-trade]');
      if(group){container.querySelector('[data-statistics-list="'+group.dataset.statisticsShowGroup+'"]')?.showModal();}
      else if(trade){container.querySelector('[data-statistics-detail="'+trade.dataset.statisticsTrade+'"]')?.showModal();}
      else if(event.target.closest('[data-statistics-info]'))container.querySelector('[data-statistics-about]')?.showModal();
      else if(event.target.closest('[data-statistics-reload]'))refresh();
    });
    return refresh();
  }
  root.StatisticsUI = {render, mount};
  if (typeof module !== 'undefined') module.exports = root.StatisticsUI;
})(typeof window === 'undefined' ? globalThis : window);
