// Real Chromium + production React components. API responses are deterministic stubs.
// Run with a Vite web server on WB_UI_URL and PLAYWRIGHT_MODULE pointing to playwright.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.WB_UI_URL || 'http://127.0.0.1:5185';
const categories = [{id:'worldview',name:'世界观',scope_type:'worldview',parent_id:null},
  {id:'characters',name:'角色',scope_type:'character',parent_id:null},
  {id:'unclassified',name:'未分类',scope_type:'other',parent_id:null}];
const detail = {id:'review',name:'返修验收书',enabled:true,schema_version:3,scope_mode:'selective',
  updated_at:1,categories,import_config:{revision:1,fixed_entry_uids:[],dependency_sources:[]},
  dependency_rules:{roots:[],rejected:[],edge_meta:{'a|b':{origin:'manual',locked:true}}},
  dependency_edges:[],related_edges:[{from_uid:'a',to_uid:'b'}],
  entries:[{uid:'a',name:'角色甲设定',content:'角色甲使用术式。',category_id:'unclassified',enabled:true,trigger_keys:[]},
    {uid:'b',name:'术式定义',content:'术式的基础规则。',category_id:'unclassified',enabled:true,trigger_keys:[]}]};
const job = {job_id:'saved-job',book_id:'review',stage:'failed',outcome:'partial',calls:2,
  resumable:true,pending_card_uids:1,pending_chunk_ids:2,pending_pairs:0,failed_batches:[],
  result:{model:'stub',records:[],accepted:[
    {from_uid:'a',to_uid:'b',relation:'requires',confidence:.9},
    {from_uid:'b',to_uid:'a',relation:'requires',confidence:.8}],configuration_roots:[
    {entry_uid:'a',activation:'roster_any',expansion:'requires_closure',character_ids:['A'],origin:'rule'},
    {entry_uid:'b',activation:'always',expansion:'requires_closure',character_ids:[],origin:'llm',model:'stub',prompt_version:'p',
    source_content_hash:'hash',evidence:'术式的基础规则',review_status:'proposed',job_id:'saved-job',reason:'AI'}],
    roots:[],issues:[],stats:{requires:0,related:0,unsure:0,none:0},expansion_probe:{}}};
(async()=>{
  const browser = await chromium.launch({headless:true,channel:process.env.WB_BROWSER || 'chrome'});
  const page = await browser.newPage({viewport:{width:1400,height:1000}});
  const errors = []; page.on('pageerror',e=>{errors.push(e.message); console.error('PAGE',e.message)});
  let previews=0, jobGets=0, starts=0, writes=[], oldWrites=0;
  await page.route('**/api/**',async route=>{
    const req=route.request(), url=new URL(req.url()), p=url.pathname;
    let data={}; let status=200;
    if(p==='/api/worldbook') data={books:[detail,{...detail,id:'second',name:'第二本书'}]};
    else if(p==='/api/characters') data=[{id:'A',name:'角色甲'}];
    else if(p.endsWith('/auto-classify')) {
      if(req.postDataJSON().apply) oldWrites++;
      data={matched:1,total:2,unmatched:[],unmatched_count:0,character_links:0,conflicts:[],signals:{},categories,
        draft_patch:{categories,entry_moves:{b:'worldview'},entry_updates:{}}};
    }
    else if(/\/entries\/|\/taxonomy$/.test(p)) {oldWrites++;}
    else if(p.endsWith('/avatar')) {await route.fulfill({status:404,body:''});return;}
    else if(p.endsWith('/scope-preview')) {previews++;data={entry_count:0,full_entry_count:2,scope:{resolved_entry_uids:[]},
      full_estimated_tokens:20,resolved_estimated_tokens:0,saved_estimated_tokens:20,saved_percent:100,
      active_roots:[],resolved_edges:[],selection_reasons:{},display_tree:[],issues:[],warnings:[],breakdown:{}};}
    else if(p.endsWith('/dependency-proposals/saved-job')) {jobGets++;data={job};}
    else if(p.endsWith('/dependency-proposals')) {if(req.method()==='POST') starts++;data={jobs:[job],latest_job_id:job.job_id};}
    else if(p.endsWith('/configuration')) {writes.push(req.postDataJSON());status=409;data={error:'配置已变更，请重新加载后再保存'};}
    else if(p==='/api/worldbook/review') data=detail;
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.route('**/review-harness',route=>route.fulfill({contentType:'text/html',body:`
    <html><head><link rel="stylesheet" href="/src/style.css"></head><body><div id="root"></div>
    <script type="module">import RefreshRuntime from '/@react-refresh';
    RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>(type)=>type;
    window.__vite_plugin_react_preamble_installed__=true;
    const React=await import('/node_modules/.vite/deps/react.js');
    const DOM=await import('/node_modules/.vite/deps/react-dom_client.js');
    const {default:Page}=await import('/src/components/WorldBookDependencyPage.tsx');
    DOM.default.createRoot(document.getElementById('root')).render(React.default.createElement(Page));</script></body></html>`}));
  await page.goto(base+'/review-harness');
  const apply=page.getByRole('button',{name:/应用构建结果/});
  try { await apply.waitFor({timeout:10000}); }
  catch(e) {console.error(await page.locator('body').innerText());await browser.close();throw e;}
  assert.ok(await page.getByRole('button',{name:/继续未完成部分/}).isVisible(),
    'orphan resumable job without failed_batches must expose continuation');
  await page.waitForTimeout(700); const idle=previews;
  await page.waitForTimeout(1200); assert.equal(previews,idle,'idle preview must stop');
  assert.equal(await page.getByText('计算中…',{exact:true}).count(),0);
  await page.getByRole('button',{name:'条目与角色',exact:true}).click();
  await page.getByRole('button',{name:'配置概览',exact:true}).click();
  await apply.waitFor(); await page.waitForTimeout(400);
  assert.ok(jobGets>=2,'completed job must reload on return'); assert.equal(starts,0);
  await apply.click();
  assert.ok(await page.getByText(/与人工锁定关系相反/).isVisible(),
    'opposite AI relation must remain review-only');
  await page.getByRole('button',{name:'改为只含自身',exact:true}).click();
  await page.getByRole('button',{name:'保存',exact:true}).click();
  await page.getByText(/保存被拒绝/).waitFor();
  assert.equal(writes.length,1);assert.equal(writes[0].roots[0].character_ids[0],'A');
  const editedRoot=writes[0].roots.find(root=>root.entry_uid==='b');
  assert.equal(editedRoot.activation,'always');
  assert.equal(editedRoot.expansion,'none');
  assert.equal(editedRoot.origin,'manual');
  for(const field of ['model','prompt_version','source_content_hash','evidence','review_status','job_id','reason'])
    assert.equal(field in editedRoot,false,'AI-only metadata leaked after manual edit: '+field);
  assert.equal(writes[0].proposal.materialized,true);
  assert.deepEqual(writes[0].proposal.materialized_root_uids,['a','b']);
  assert.deepEqual(writes[0].proposal.accepted_pairs,[['b','a']]);
  assert.deepEqual(writes[0].related_edges,[{from_uid:'a',to_uid:'b'}]);
  await page.getByRole('button',{name:'高级图谱',exact:true}).click();
  await page.getByRole('button',{name:'配置概览',exact:true}).click();
  assert.ok(await page.getByText(/保存被拒绝/).isVisible(),'conflict preserves draft across views');
  await page.getByLabel('依赖图世界书').selectOption('second');
  const dialog=page.getByRole('dialog',{name:'切换世界书'});
  await dialog.waitFor();
  for(const name of ['保存并切换','放弃并切换','取消']) assert.ok(await dialog.getByRole('button',{name,exact:true}).isVisible());
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  assert.equal(await page.getByLabel('依赖图世界书').inputValue(),'review');
  await page.getByRole('button',{name:'撤销',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'保存',exact:true}).isEnabled(),false);
  await page.getByRole('button',{name:'高级图谱',exact:true}).click();
  await page.getByRole('button',{name:'分类结构',exact:true}).click();
  await page.getByRole('button',{name:'自动分类',exact:true}).click();
  await page.getByRole('button',{name:/应用分类/}).click();
  await page.getByTitle('角色甲设定 · a',{exact:true}).click();
  await page.getByLabel(/归属分类/).selectOption('characters');
  await page.getByPlaceholder('角色目录名',{exact:true}).fill('A');
  await page.getByRole('button',{name:'保存归属',exact:true}).click();
  assert.equal(oldWrites,0,'advanced actions must not call old write routes');
  await page.getByRole('button',{name:'保存',exact:true}).click();
  await page.getByText(/保存被拒绝/).waitFor();
  assert.equal(writes[1].entry_updates.a.character_id,'A');
  assert.equal(writes[1].entry_moves.b,'worldview');
  await page.getByRole('button',{name:'撤销',exact:true}).click();
  assert.deepEqual(errors,[]);
  if(process.env.WB_UI_SCREENSHOT) await page.screenshot({path:process.env.WB_UI_SCREENSHOT,fullPage:true});
  console.log(JSON.stringify({idlePreviews:idle,restoredJobRequests:jobGets,duplicateStarts:starts,
    configurationWrites:writes.length,oldWrites,resumableWithoutFailedBatches:true,rootOnlyApply:true,
    conflictDraftPreserved:true,threeWayBookSwitch:true,errors}));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
