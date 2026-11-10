const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('static/app.js','utf8');
const context={setInterval(){},Intl,Number,Date};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('let diagnosticsData=null')),context);
class Node {
 constructor(name,attrs={},children=[]){this.nodeName=name;this.tagName=name;this.nodeType=name==='#text'?3:1;this.nodeValue=null;this.attrs={...attrs};this.childNodes=children;this.parent=null;for(const c of children)c.parent=this}
 get attributes(){return Object.entries(this.attrs).map(([name,value])=>({name,value}))}
 hasAttribute(k){return Object.hasOwn(this.attrs,k)} getAttribute(k){return this.attrs[k]??null} setAttribute(k,v){this.attrs[k]=v} removeAttribute(k){delete this.attrs[k]}
 cloneNode(deep){const n=new Node(this.nodeName,this.attrs,deep?this.childNodes.map(c=>c.cloneNode(true)):[]);n.nodeValue=this.nodeValue;return n}
 appendChild(n){n.parent=this;this.childNodes.push(n)} get lastChild(){return this.childNodes.at(-1)}
 remove(){this.parent.childNodes.splice(this.parent.childNodes.indexOf(this),1)}
 replaceWith(n){const p=this.parent;p.childNodes[p.childNodes.indexOf(this)]=n;n.parent=p}
}
const text=v=>{let n=new Node('#text');n.nodeValue=v;return n};
const val=text('2 sek.');const details=new Node('DETAILS',{open:''},[new Node('SUMMARY',{},[text('Målinger')]),new Node('SPAN',{class:'diag-within'},[val])]);
const root=new Node('DIV',{id:'diagnostics-content'},[details]);
const next=new Node('DIV',{id:'diagnostics-content'},[new Node('DETAILS',{},[new Node('SUMMARY',{},[text('Målinger')]),new Node('SPAN',{class:'diag-over'},[text('8 sek.')])])]);
context.current=root;context.next=next;vm.runInContext('patchDiagnostics(current,next)',context);
assert.strictEqual(root.childNodes[0],details);assert(details.hasAttribute('open'));assert.strictEqual(details.childNodes[1].childNodes[0],val);assert.equal(val.nodeValue,'8 sek.');assert.equal(details.childNodes[1].attrs.class,'diag-over');assert.equal(root.attrs.id,'diagnostics-content');
details.removeAttribute('open');next.childNodes[0].setAttribute('open','');vm.runInContext('patchDiagnostics(current,next)',context);assert(!details.hasAttribute('open'));
console.log('PASS live values update in place and preserve open sections');
