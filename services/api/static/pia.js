'use strict';
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); accessToken = $('api-key').value; $('api-key').value = '';
  try { const me = await api('/api/internal/me'); $('identity').textContent = me.subject+' · '+me.role; await refresh(); }
  catch(error) { accessToken = ''; $('identity').textContent = error.message; }
});
$('logout').addEventListener('click', () => { accessToken=''; $('identity').textContent='Вы вышли'; for(const id of ['pia-result','search-results','path-result','source-result','evidence-result'])$(id).replaceChildren(); for(const id of ['case-json','case-action-json','case-id','source-id','target-id','pia-file','wealth-file'])$(id).value=''; });
async function fileRequest(input, endpoint) {
  const file = $(input).files[0];
  if (!file || file.size > 5*1024*1024) throw new Error('Требуется JSON размером до 5 МБ');
  return api(endpoint, JSON.parse(await file.text()));
}
async function display(action) {
  try { $('pia-result').textContent=JSON.stringify(await action(),null,2); }
  catch(error) { $('pia-result').textContent=error.message; }
}
$('pia-import').addEventListener('submit', e => {e.preventDefault();display(()=>fileRequest('pia-file','/api/internal/imports'));});
$('wealth-form').addEventListener('submit', e => {e.preventDefault();display(()=>fileRequest('wealth-file','/api/internal/wealth/reconcile'));});
$('scan-conflicts').addEventListener('click',()=>display(()=>api(withKnownAt('/api/internal/conflicts/scan'),{})));
$('case-create').addEventListener('submit',e=>{e.preventDefault();display(()=>api('/api/internal/cases',JSON.parse($('case-json').value)));});
$('case-action').addEventListener('submit',e=>{e.preventDefault();display(()=>api('/api/internal/cases/'+encodeURIComponent($('case-id').value.trim())+'/actions',JSON.parse($('case-action-json').value)));});
$('cases-refresh').addEventListener('click',()=>display(async()=>({cases:await api(withKnownAt('/api/internal/cases')),signals:await api(withKnownAt('/api/internal/conflicts'))})));
$('live-fetch').addEventListener('submit',e=>{e.preventDefault();display(()=>api('/api/internal/connectors/fetch',{source:$('live-source').value,limit:3,license:$('source-license').value,legal_basis:$('source-purpose').value}));});
