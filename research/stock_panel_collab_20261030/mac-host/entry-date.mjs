// Date roles are resolved only against the owned catalog, never date arithmetic.
function parsedDate(raw){
 if(raw===null)return null;
 const value=/^\d{8}$/.test(raw)?raw.slice(0,4)+'-'+raw.slice(4,6)+'-'+raw.slice(6):raw;
 if(!/^\d{4}-\d{2}-\d{2}$/.test(value))throw Error('REQUESTED_DATE_INVALID');
 const day=new Date(value+'T00:00:00Z');if(!Number.isFinite(day.valueOf())||day.toISOString().slice(0,10)!==value||value.startsWith('0000'))throw Error('REQUESTED_DATE_INVALID');
 return value;
}
export function requestedSourceDate(search){return parsedDate(new URLSearchParams(search).get('date'));}
export function requestedEntry(search){
 const params=new URLSearchParams(search);
 for(const key of ['date','source_date','observation_date'])if(params.getAll(key).length>1)throw Error('REQUESTED_DATE_CONFLICT');
 const legacy=parsedDate(params.get('date')),source=parsedDate(params.get('source_date')),observation=parsedDate(params.get('observation_date'));
 if(legacy&&source&&legacy!==source)throw Error('REQUESTED_DATE_CONFLICT');
 if(source||legacy&&observation)return {mode:'source',source_date:source??legacy,observation_date:observation};
 if(observation)return {mode:'observation',observation_date:observation};
 return legacy?{mode:'legacy',legacy_date:legacy}:{mode:'latest'};
}
export const catalogEntryKey=entry=>entry.source_date+(entry.revision?'|'+entry.revision:'');
export function preferredCatalogEntry(entries){
 return entries.filter(entry=>entry.revision).sort((a,b)=>b.source_date.localeCompare(a.source_date)||Number(b.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2')-Number(a.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'))[0]??null;
}
export function resolveCatalogRequest(intent,entries){
 const missing=status=>({entry:null,status,intent});
 const bound=entry=>entry?{entry,status:'BOUND',intent:intent.mode==='latest'?intent:{mode:'source',source_date:entry.source_date,observation_date:entry.observation_date}}:missing('NOT_MATERIALIZED');
 if(intent.mode==='latest')return bound(preferredCatalogEntry(entries));
 if(intent.mode==='source'){
  const matches=entries.filter(entry=>entry.source_date===intent.source_date);
  if(intent.observation_date&&matches.some(entry=>entry.observation_date!==intent.observation_date))return missing('SOURCE_OBSERVATION_CONFLICT');
  return bound(preferredCatalogEntry(matches));
 }
 if(intent.mode==='legacy'){
  const exactSource=entries.filter(entry=>entry.source_date===intent.legacy_date);
  if(exactSource.length)return bound(preferredCatalogEntry(exactSource));
 }
 const observation=intent.observation_date??intent.legacy_date,matches=entries.filter(entry=>entry.observation_date===observation&&entry.revision);
 if(new Set(matches.map(entry=>entry.source_date)).size>1)return missing('AMBIGUOUS_OBSERVATION_DATE');
 return bound(preferredCatalogEntry(matches));
}
export function entryUrl(href,intent){
 const url=new URL(href);for(const key of ['date','source_date','observation_date'])url.searchParams.delete(key);
 if(intent.mode==='source'){url.searchParams.set('source_date',intent.source_date);if(intent.observation_date)url.searchParams.set('observation_date',intent.observation_date);}
 else if(intent.mode==='observation')url.searchParams.set('observation_date',intent.observation_date);
 else if(intent.mode==='legacy')url.searchParams.set('date',intent.legacy_date);
 return url.href;
}
