// Executed through Codex functions tools; reference only, not an autonomous scheduler.
// Input QUERY_PLAN.json; load/store are functions session helpers.
// This records actual batching and exact public read-only query construction.
const runBatchedSearch = async function(limit){
 const plans=load("plans"),start=load("next"),end=Math.min(start+limit,plans.length);
 for(let off=start;off<end;off+=16){
  const units=[];for(let j=off;j<Math.min(off+16,end);j+=4)units.push(plans.slice(j,Math.min(j+4,end)));
  const rr=await Promise.allSettled(units.map(async batch=>{
   const qs=batch.map(p=>{const hi=new Date(p.main_window_end.slice(0,10)+"T00:00:00Z");hi.setUTCDate(hi.getUTCDate()+1);return {q:p.code.split(".")[0]+" "+p.name+" 公告 新闻 政策 题材 after:"+p.known_before_signal_start.slice(0,10)+" before:"+hi.toISOString().slice(0,10)};});
   const at=new Date().toISOString();const response=await tools.web__run({search_query:qs,response_length:"long"});return {batch,qs,at,response:typeof response==="string"?response:JSON.stringify(response)};
  }));
  for(let u=0;u<rr.length;u++){
   const batch=units[u];const ok=rr[u].status==="fulfilled";const val=ok?rr[u].value:null;
   const blocks=ok?val.response.split("--------------------------------------------------------------------------------"):[];
   for(let i=0;i<batch.length;i++){
    const p=batch[i],digits=p.code.split(".")[0];
    const matched=blocks.filter(b=>b.includes(digits)||(p.name.length>=2&&b.includes(p.name)));
    const sources=matched.flatMap(b=>[...b.matchAll(/^(.+?) \((https?:\/\/[^\n]+)\)\n/gm)].map(m=>({title:m[1],url:m[2]})));
    const r={...p,actual_query:ok?val.qs[i].q:null,requested_source:"WEB_SEARCH_PUBLIC_INDEX",retrieved_at:ok?val.at:new Date().toISOString(),query_status:ok?"QUERIED_BATCHED_PUBLIC_INDEX_COVERAGE_NOT_EXHAUSTIVE":"QUERY_FAILED",response_count:null,response_count_null_reason:"PROVIDER_COMBINES_UP_TO_FOUR_QUERIES_NO_PER_QUERY_HIT_COUNT",tool_response_block_count:null,tool_response_block_count_null_reason:"WEB_TOOL_RETURNS_COMBINED_TEXT",parsed_source_count:sources.length,parsed_source_count_scope:"SOURCE_BLOCKS_EXPLICITLY_MATCHING_CODE_OR_INPUT_NAME_IN_BATCH_RESPONSE_NOT_EXHAUSTIVE",search_hit_count:null,search_hit_count_null_reason:"TOTAL_SEARCH_ENGINE_HITS_NOT_EXPOSED",batch_query_ids:batch.map(x=>x.query_id),sources,response:ok?val.response:String(rr[u].reason)};
    const content=JSON.stringify(r,null,2);await tools.apply_patch("*** Begin Patch\n*** Add File: /Users/lexi/Desktop/学习/因子工厂/research/week_miss387_diagnosis_20261023/catalyst/raw/"+p.query_id+".json\n"+content.split("\n").map(x=>"+"+x).join("\n")+"\n*** End Patch");
   }
  }
  store("next",Math.min(off+16,end));notify({completed:Math.min(off+16,end),total:plans.length});
 }
 text({completed:end,total:plans.length});
}

const runOfficialSearch = async function(limit){
 const plans=load("officialPlans"),start=load("officialNext"),end=Math.min(start+limit,plans.length);
 for(let off=start;off<end;off+=16){
 const units=[];for(let j=off;j<Math.min(off+16,end);j+=4)units.push(plans.slice(j,Math.min(j+4,end)));
 const rr=await Promise.allSettled(units.map(async batch=>{
 const qs=batch.map(p=>({q:p.code.split(".")[0]+" "+p.name+" 公告 after:2026-10-11 before:2026-10-23",domains:["cninfo.com.cn","bse.cn","szse.cn","sse.com.cn"]}));
 const at=new Date().toISOString();const r=await tools.web__run({search_query:qs,response_length:"long"});return {qs,at,response:typeof r==="string"?r:JSON.stringify(r)};
 }));
 for(let u=0;u<units.length;u++){const batch=units[u],ok=rr[u].status==="fulfilled",v=ok?rr[u].value:null;
 for(let i=0;i<batch.length;i++){const p=batch[i],raw=ok?v.response:String(rr[u].reason);const blocks=raw.split("--------------------------------------------------------------------------------").filter(b=>b.includes(p.code.split(".")[0])||(p.name.length>=2&&b.includes(p.name)));
 const sources=blocks.flatMap(b=>[...b.matchAll(/^(.+?) \((https?:\/\/[^\n]+)\)\n/gm)].map(m=>({title:m[1],url:m[2]})));
 const r={query_id:"OFFICIAL_"+p.code.replace(".","_"),code:p.code,input_name:p.name,mapped_row_ids:p.rows,actual_query:ok?v.qs[i]:null,retrieved_at:ok?v.at:new Date().toISOString(),query_status:ok?"QUERIED_OFFICIAL_DOMAIN_PUBLIC_INDEX_NOT_EXHAUSTIVE":"QUERY_FAILED",parsed_source_count:sources.length,search_hit_count:null,search_hit_count_null_reason:"BATCH_SEARCH_TOTAL_HITS_NOT_EXPOSED",source_coverage:"INDEXED_OFFICIAL_DOCUMENTS_ONLY_NOT_EXHAUSTIVE_ISSUER_FEED",sources,response:raw};
 const content=JSON.stringify(r,null,2);await tools.apply_patch("*** Begin Patch\n*** Add File: /Users/lexi/Desktop/学习/因子工厂/research/week_miss387_diagnosis_20261023/catalyst/raw/"+r.query_id+".json\n"+content.split("\n").map(x=>"+"+x).join("\n")+"\n*** End Patch");
 }}store("officialNext",Math.min(off+16,end));if((off-start)%32===0||off+16>=end)notify({official_completed:Math.min(off+16,end),total:plans.length});
 }text({official_completed:end,total:plans.length});
}
