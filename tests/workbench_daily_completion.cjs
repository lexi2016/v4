const assert=require('node:assert/strict'),fs=require('node:fs');
if(!process.argv.includes('--async-ready-only'))(async()=>{
 const raw=fs.readFileSync('research/stock_panel_collab_20261030/mac-host/completion-action.mjs','utf8');
 const {completionAction}=await import('data:text/javascript;base64,'+Buffer.from(raw).toString('base64'));
 const ref={path:'/accepted/manifest.json',sha256:'a'.repeat(64)};
 const e={schema_version:'v4.a_share.daily_completion.v1',data_date:'20261030',status:'PARTIAL_WITH_ROWS',source_generation:'b'.repeat(64),input_sha256:'c'.repeat(64),event_id:'d'.repeat(64),manifest:ref,artifact:ref,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
 const context={source_date:'2026-10-29',generation:e.source_generation,input_sha256:e.input_sha256};
 assert.equal(completionAction(context,e),'catalog');assert.equal(completionAction(null,e),'catalog');
 assert.equal(completionAction({...context,source_date:'2026-10-30'},e),'refresh');
 assert.equal(completionAction({...context,source_date:'2026-10-30',generation:'e'.repeat(64)},e),'source_changed');
 assert.equal(completionAction(context,{...e,status:'FAILED'}),'gap');
 assert.equal(completionAction(context,{...e,orders_sent:true}),'gap');
 const build=fs.readFileSync('ops/build_mac_workbench.py','utf8');
 const catalog=build.slice(build.indexOf(' async catalog(){'),build.indexOf('\n refresh(){'));
 const cases=[{follow:false,expected:'2026-10-29|old',loads:0},{follow:true,expected:'2026-10-30|new',loads:1}];
 for(const test of cases){
 const options=[{value:'2026-10-29|old',textContent:'2026-10-29'}],select={options,append(option){options.push(option)},value:options[0].value};
 let loads=0;const scope={selection:()=>({date:select.value.split('|')[0]}),loadJson:async()=>({days:[{source_date:'2026-11-02',revision:null,status:'FAILED'},{source_date:'2026-10-30',revision:'new'},{source_date:'2026-10-29',revision:'old'}]}),integrationBase:'/api',node:(_tag,text)=>({textContent:text}),$:id=>id==='date'?select:{},loadDay:async()=>{loads++}};
 const make=new Function(...Object.keys(scope),`let catalogSerial=0,day={source_date:'2026-10-29'},followLatestResearchDay=${test.follow};return ({${catalog}}).catalog`);
 await make(...Object.values(scope))();assert.equal(select.value,test.expected);assert.equal(loads,test.loads);assert.equal(options.length,3);
 }
 assert.match(build,/addEventListener\('change',\(\)=>\{followLatestResearchDay=false/);
 console.log('PASS completion catalog discovery, fixed date, same-day version, source changes and bad completion');
})().catch(error=>{console.error(error);process.exitCode=1});

if(process.argv.includes('--async-ready-only')){
 const vm=require('node:vm'),source=fs.readFileSync('research/stock_panel_collab_20261030/mac-host/bootstrap.mjs','utf8');
 const start=source.indexOf('function cancelOriginalReady()'),end=source.indexOf('\nwindow.StockPanelHost=',start);assert(start>0&&end>start);
 const code=source.slice(start,end),cases=[];
 const fixture=()=>{
  const observers=[],listeners={},calls=[],rows=Array.from({length:30},(_,i)=>({trade_date:20261001+i})),context={symbol:'000528.SZ',source_date:'2026-10-30',generation:'g'};
  const state={symbol:context.symbol,rows:[],view:null,selected:0};const child={documentElement:{dataset:{}},getElementById:()=>({})};
  const w={RESEARCH_PANEL_STATE:state,setOriginalWindow(count,end){calls.push(['window',count,end]);state.view={count,start:end-count}},choose(index){calls.push(['choose',index]);state.selected=index},paint(){calls.push(['paint'])}};
  const frame={hidden:false,contentWindow:w,contentDocument:child,addEventListener(name,callback){listeners[name]=callback}};
  class MutationObserver{constructor(callback){this.callback=callback;this.disconnected=false;observers.push(this)}observe(target,options){assert.deepEqual(Array.from(options.attributeFilter),['data-loaded']);this.target=target}disconnect(){this.disconnected=true}fire(){this.callback()}}
  const select={replaceChildren(){}};const scope={frame,MutationObserver,el:()=>select,add:()=>({}),current:{context,projection:{data:{rows}}},preservedChart:{...context,start:5,count:10,selected:8}};vm.createContext(scope);vm.runInContext('let originalReadyObserver=null;'+code,scope);
  const initialize=()=>{state.rows=rows;state.view={start:10,count:20};state.selected=29;child.documentElement.dataset.loaded=context.symbol};
  return {scope,frame,state,child,context,observers,calls,load:listeners.load,initialize,cancel:()=>vm.runInContext('cancelOriginalReady()',scope)};
 };
 let f=fixture();f.load();assert.equal(f.calls.length,0);assert.equal(f.observers.length,1);f.initialize();f.observers[0].fire();assert.equal(f.state.view.start,5);assert.equal(f.state.view.count,10);assert.equal(f.state.selected,8);assert(f.observers[0].disconnected);cases.push('delayed-real-marker-restores-exact-window-and-point');
 f=fixture();f.initialize();f.load();assert.equal(f.state.selected,8);assert(f.observers[0].disconnected);cases.push('already-ready-frame-applies-once');
 f=fixture();f.load();f.initialize();f.child.documentElement.dataset.loaded='OTHER.SZ';f.observers[0].fire();assert.equal(f.calls.length,0);cases.push('wrong-symbol-marker-does-not-apply');
 f=fixture();f.load();f.initialize();f.scope.current={context:{...f.context,generation:'new'},projection:{data:{rows:f.state.rows}}};f.observers[0].fire();assert.equal(f.calls.length,0);assert(f.observers[0].disconnected);cases.push('newer-context-cancels-old-callback');
 f=fixture();f.load();f.initialize();f.frame.contentDocument={documentElement:{dataset:{loaded:f.context.symbol}}};f.observers[0].fire();assert.equal(f.calls.length,0);assert(f.observers[0].disconnected);cases.push('replaced-document-cancels-old-callback');
 f=fixture();f.load();f.cancel();assert(f.observers[0].disconnected);f.scope.current=null;f.initialize();f.observers[0].fire();assert.equal(f.calls.length,0);assert.match(source,/clear\(\)\{cancelOriginalReady\(\);/);cases.push('clear-cancels-pending-observer');
 f=fixture();f.load();const old=f.observers[0];f.load();assert(old.disconnected);f.initialize();f.scope.preservedChart={...f.scope.preservedChart,symbol:'OTHER.SZ'};f.observers.at(-1).fire();assert.equal(f.calls.length,0);cases.push('new-load-cancels-old-and-wrong-preserved-identity');
 console.log(JSON.stringify({status:'PASS_ASYNC_ORIGINAL_READY',cases,formula_or_source_computations:0}));
}
