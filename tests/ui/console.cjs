// Isolated browser test. API fixtures exercise UI controls; they do not validate real sources.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
(async () => {
 const browser = await chromium.launch({headless:true,...(process.env.TRACE_BROWSER_CHANNEL?{channel:process.env.TRACE_BROWSER_CHANNEL}:{})});
 const page = await browser.newPage({viewport:{width:1480,height:1120}});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 const a='00000000-0000-0000-0000-000000000001',b='00000000-0000-0000-0000-000000000002';
 const entity=id=>({id,entity_type:'ORGANIZATION',canonical_name:id===a?'Browser test organization A':'Browser test organization B',jurisdiction_code:'EU',status:'ACTIVE'});
 await page.route('http://trace.test/**',async route=>{
   const u=new URL(route.request().url());let body;
   if(u.pathname.startsWith('/ui/')){const f=u.pathname==='/ui/'?'index.html':u.pathname.split('/').at(-1);return route.fulfill({path:path.resolve('services/api/static',f),contentType:f.endsWith('.css')?'text/css':f.endsWith('.js')?'text/javascript':'text/html'});}
   if(u.pathname==='/api/v1/system/status')body={status:'ready',components:{postgres:{status:'ok'},evidence:{status:'ok'},neo4j:{status:'ok'},redis:{status:'ok'},opensearch:{status:'ok'}}};
   else if(u.pathname.endsWith('/reconciliation/summary'))body={source_mappings:2,relationship_observations:1,open_entity_candidates:0,open_relationship_conflicts:0};
   else if(u.pathname.includes('relationship-intelligence'))body={layer:'ownership',status:'SUCCEEDED',entity_ids:[a,b],relationship_ids:['edge1'],notes:[]};
   else if(u.pathname.endsWith('/entities/search'))body=[entity(a),entity(b)];
   else if(u.pathname.includes('/entities/'))body=entity(u.pathname.split('/').at(-1));
   else if(u.pathname.endsWith('/investigations'))body={source_entity:entity(a),target_entity:entity(b),paths:[{hops:1,nodes:[a,b],edges:[{id:'edge1',subject_entity_id:a,object_entity_id:b,relationship_type:'TEST_ONLY_PARENT'}]}],unknowns:[]};
   else if(u.pathname.endsWith('/why'))body={source_observations:[{source_code:'TEST_FIXTURE',source_external_id:'not-real-data',payload_hash:'00'.repeat(32)}]};
   else return route.fulfill({status:404,body:'{}'});
   return route.fulfill({json:body});
 });
 await page.goto('http://trace.test/ui/');
 await page.getByText('Готово',{exact:true}).waitFor();
 await page.locator('#gleif-form button').click();
 await page.getByText('ownership · SUCCEEDED',{exact:true}).waitFor();
 await page.locator('#search-results .entity-row').first().getByRole('button',{name:'Отсюда'}).click();
 await page.locator('#search-results .entity-row').last().getByRole('button',{name:'Сюда'}).click();
 await page.getByRole('button',{name:'Исследовать',exact:true}).click();
 await page.getByRole('button',{name:'Доказательства',exact:true}).click();
 await page.getByText('Происхождение связи',{exact:true}).waitFor();
 await page.locator('#search').fill('test');await page.locator('#search-form button').click();
 await page.locator('#search-results .entity-row').last().waitFor();
 if(errors.length)throw Error(errors.join('\n'));
 await page.setViewportSize({width:390,height:844});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile horizontal overflow');
 await page.setViewportSize({width:1480,height:1120});await page.evaluate(()=>scrollTo(0,0));
 fs.mkdirSync('logs',{recursive:true});await page.screenshot({path:'logs/console-browser-test.png',fullPage:true});
 console.log('PASS: desktop and mobile layout, import, selection, path, provenance and search (mock API).');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
