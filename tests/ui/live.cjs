// Real running application and PostgreSQL; no mocked routes and no automatic external imports.
const {chromium}=require('playwright');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.TRACE_BROWSER_CHANNEL?{channel:process.env.TRACE_BROWSER_CHANNEL}:{})});
  const page=await browser.newPage({viewport:{width:1480,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base=process.env.TRACE_API_URL||'http://127.0.0.1:8000';
  await page.goto(base+'/ui/');
  await page.locator('#api-key').fill(process.env.TRACE_API_TOKEN||'trace-dev-analyst-only');
  await page.locator('#login-form').getByRole('button',{name:'Войти',exact:true}).click();
  await page.getByText('Готово',{exact:true}).waitFor();
  const auth={Authorization:'Bearer '+(process.env.TRACE_API_TOKEN||'trace-dev-analyst-only')};
  const temporal=await (await page.request.get(base+'/api/internal/temporal/status',{headers:auth})).json();
  if(!temporal.history_available_from||temporal.system_time!=='postgresql_transaction_commit')throw Error('Temporal baseline unavailable');
  const cutoff=new Date(temporal.known_at);const localCutoff=new Date(cutoff-cutoff.getTimezoneOffset()*60000).toISOString().slice(0,19);
  await page.locator('#known-at').fill(localCutoff);
  const historicalRequest=page.waitForRequest(r=>r.url().includes('/api/internal/cases?known_at='));
  await page.getByRole('button',{name:'Показать дела и сигналы',exact:true}).click();
  await historicalRequest;await page.locator('#pia-result').getByText('cases',{exact:false}).waitFor();
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
  await page.goto(base+'/docs');await page.locator('#docs-paths details').first().waitFor();
  await page.goto(base+'/public/');await page.locator('#releases').waitFor();
  await page.waitForFunction(()=>!document.querySelector('#releases').textContent.includes('Загрузка'));
  if(errors.length)throw Error(errors.join('\n'));
  await page.goto(base+'/ui/');
  if(await page.locator('#api-key').inputValue())throw Error('Credential survived page reload');
  await browser.close();console.log('PASS: real API login, case listing, public portal, API docs, mobile layout and credential lifetime');
})().catch(e=>{console.error(e);process.exit(1)});
