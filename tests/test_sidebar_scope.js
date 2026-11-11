// All sidebar rules, including mobile rules, must target only the page sidebar.
const fs=require('node:fs'),assert=require('node:assert/strict');
const css=fs.readFileSync(process.argv[2]||'static/style.css','utf8').replace(/\/\*[\s\S]*?\*\//g,'');
const selectors=[...css.matchAll(/([^{}]+)\{/g)].flatMap(m=>m[1].trim().split(','))
 .map(s=>s.trim()).filter(s=>/\baside\b/.test(s));
assert.ok(selectors.length>0,'Missing sidebar styles');
// These two mobile keyboard rules put the focus condition on body, while still
// targeting its direct sidebar child. Do not allow arbitrary :has() selectors.
const focusPrefixes=[
 'body:has(input:not([type=checkbox]):not([type=radio]):focus)',
 'body:has(textarea:focus)'
];
function scoped(selector){
 for(const prefix of focusPrefixes){
  if(selector.startsWith(prefix)) selector='body'+selector.slice(prefix.length);
 }
 return /^body\s*>\s*aside(?:$|[\s.:#\[])/.test(selector);
}
for(const selector of selectors)assert.ok(scoped(selector),
 'Sidebar rule also targets signal notices: '+selector);
for(const bad of ['aside','main aside','body aside','body:has(.other) aside','body:has(textarea:focus) aside'])
 assert.equal(scoped(bad),false,'Unscoped sidebar rule accepted: '+bad);
const html=fs.readFileSync('static/index.html','utf8');
assert.match(html,/<body>[\s\S]*?<aside><a class="brand"/);
console.log('PASS: '+selectors.length+' sidebar selectors are scoped to the page sidebar, including responsive rules');
