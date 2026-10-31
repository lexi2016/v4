// Classify only the currently selected source day. Admission changes invalidate
// old views; other days never take over the user's date selection.
const sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const ref=v=>typeof v?.path==='string'&&v.path.length>0&&sha(v.sha256);
export function completionAction(context,event){
  if(event.schema_version!=='v4.a_share.daily_completion.v1'||!['READY','PARTIAL_WITH_ROWS'].includes(event.status)||!sha(event.source_generation)||!sha(event.input_sha256)||!sha(event.event_id)||!ref(event.manifest)||!ref(event.artifact)||event.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>event[k]!==false))return 'gap';
  if(!context||event.data_date!==context.source_date.replaceAll('-',''))return 'catalog';
  return event.source_generation===context.generation&&event.input_sha256===context.input_sha256?'refresh':'source_changed';
}
