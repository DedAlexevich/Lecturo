const { chromium } = require('playwright');
(async () => {
 const browser = await chromium.launch({headless:true});
 for (const width of [390, 1280]) {
  const context = await browser.newContext({viewport:{width,height:900}});
  let status=422, posts=0;
  await context.route('**/api/v1/**', async route=>{
    const p=new URL(route.request().url()).pathname;
    if(p==='/api/v1/me') return route.fulfill({json:{id:'test-user',display_name:'Тест',identities:[],ai_transfer_accepted_at:'2026-01-01'}});
    if(p==='/api/v1/local-results'){posts++; return status===201 ? route.fulfill({status:201,json:{id:'saved-id'}}):route.fulfill({status,json:{detail:'error'}})}
    if(p==='/api/v1/legal' || p==='/api/v1/lectures' || p==='/api/v1/courses') return route.fulfill({json:[]});
    return route.fulfill({status:404,json:{detail:'not found'}});
  });
  const page=await context.newPage(); await page.goto(`${process.env.LOCAL_TEST_URL || 'http://127.0.0.1:5177'}/local`,{waitUntil:'domcontentloaded'});
  await page.evaluate(async () => {
   localStorage.setItem('lecturo.token','test-token');
   await new Promise((resolve,reject)=>{const req=indexedDB.open('lecturo-local',1); req.onsuccess=()=>{const tx=req.result.transaction('lectures','readwrite'); tx.objectStore('lectures').put({id:'fixture',title:'Проверочная лекция',createdAt:Date.now(),durationSec:10,language:'ru',model:'tiny',segments:[{start:0,end:10,text:'Тестовая запись'}],chapters:[],summaryMd:null}); tx.oncomplete=resolve;tx.onerror=reject}; req.onerror=reject});
  }); await page.reload({waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Открыть',exact:true}).click();
  await page.getByRole('button',{name:'Сохранить в аккаунт'}).click();
  await page.getByRole('alert').filter({hasText:'Сервер не смог принять'}).waitFor();
  status=429; await page.getByRole('button',{name:'Сохранить в аккаунт'}).click();
  await page.getByRole('alert').filter({hasText:'Достигнут лимит'}).waitFor();
  if(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth)) throw Error('horizontal overflow');
  status=201; await page.getByRole('button',{name:'Сохранить в аккаунт'}).click();
  await page.waitForURL('**/lectures/saved-id');
  await page.goto(`${process.env.LOCAL_TEST_URL || 'http://127.0.0.1:5177'}/local`,{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Открыть',exact:true}).click();
  await page.getByRole('link',{name:'Открыть лекцию в аккаунте'}).waitFor();
  if(posts!==3) throw Error('unexpected posts '+posts);
  console.log(`width ${width}: 422, 429, 201, navigation, persistence, no overflow passed`);
  await context.close();
 }
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
