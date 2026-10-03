'use strict';
const d = id => document.getElementById(id);
fetch('/openapi.json').then(r=>r.json()).then(schema=>{
  for(const [path,operations] of Object.entries(schema.paths)) for(const [method,operation] of Object.entries(operations)) {
    if(!operation.responses)continue;
    const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
    summary.textContent=method.toUpperCase()+' '+path+' · '+(operation.summary||'');
    pre.textContent=JSON.stringify(operation,null,2);details.append(summary,pre);d('docs-paths').append(details);
  }
  d('docs-schemas').textContent=JSON.stringify(schema.components.schemas,null,2);
}).catch(e=>{d('docs-output').textContent=e.message;});
d('docs-request').addEventListener('submit',async e=>{
  e.preventDefault();
  try {
    const url=d('docs-url').value;if(!url.startsWith('/api/')||url.startsWith('//'))throw Error('Use a local /api/ path');
    const method=d('docs-method').value,headers={'Content-Type':'application/json'};
    if(d('docs-key').value)headers.Authorization='Bearer '+d('docs-key').value;
    const response=await fetch(url,{method,headers,...(method==='POST'?{body:JSON.stringify(JSON.parse(d('docs-body').value))}:{})});
    d('docs-output').textContent=response.status+'\n'+JSON.stringify(await response.json(),null,2);
  } catch(error) {d('docs-output').textContent=error.message;}
});
