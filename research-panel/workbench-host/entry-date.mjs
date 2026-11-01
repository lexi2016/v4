// Preserve requested source date; the catalog must never substitute another day.
export function requestedSourceDate(search){
 const raw=new URLSearchParams(search).get('date');if(raw===null)return null;
 const value=/^\d{8}$/.test(raw)?raw.slice(0,4)+'-'+raw.slice(4,6)+'-'+raw.slice(6):raw;
 if(!/^\d{4}-\d{2}-\d{2}$/.test(value))throw Error('REQUESTED_DATE_INVALID');
 const day=new Date(value+'T00:00:00Z');if(!Number.isFinite(day.valueOf())||day.toISOString().slice(0,10)!==value||value.startsWith('0000'))throw Error('REQUESTED_DATE_INVALID');
 return value;
}
