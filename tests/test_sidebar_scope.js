// All sidebar rules, including mobile rules, must target only the page sidebar.
const fs=require('node:fs'),assert=require('node:assert/strict');
const css=fs.readFileSync(process.argv[2]||'static/style.css','utf8').replace(/\/\*[\s\S]*?\*\//g,'');
const selectors=[...css.matchAll(/([^{}]+)\{/g)].flatMap(m=>m[1].trim().split(','))
 .map(s=>s.trim()).filter(s=>/\baside\b/.test(s));
assert.ok(selectors.length>0,'Missing sidebar styles');
for(const selector of selectors)assert.match(selector,/^body\s*>\s*aside(?:$|[\s.:#\[])/,
 'Sidebar rule also targets signal notices: '+selector);
const html=fs.readFileSync('static/index.html','utf8');
assert.match(html,/<body>[\s\S]*?<aside><a class="brand"/);
console.log('PASS: '+selectors.length+' sidebar selectors are scoped to the page sidebar, including responsive rules');
