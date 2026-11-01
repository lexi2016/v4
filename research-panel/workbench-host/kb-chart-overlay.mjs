import {chartEvents} from './kb-signal-view.mjs';

const lines=['BBI','白线','黄线','MA60','守线'];
const number=value=>value===null||value===undefined?null:(Number.isFinite(Number(value))?Number(value):null);

// Reuse the R19 visible rows, price range and x geometry; no formula is run.
export function overlayMarkers(state,byDate){
  const rows=state.visible??[],g=state.geometry;if(!rows.length||!g?.step)return [];
  const prices=[];
  for(const row of rows){
    for(const value of [row.ohlcv.high,row.ohlcv.low,...lines.map(key=>row.values[key])]){const v=number(value);if(v!==null)prices.push(v);}
    for(const drawing of row.drawings)if(drawing.condition===true&&number(drawing.y)!==null)prices.push(number(drawing.y));
  }
  if(!prices.length)return [];
  let lo=Math.min(...prices),hi=Math.max(...prices),pad=Math.max((hi-lo)*.07,.01);lo-=pad;hi+=pad;
  const top=22,bottom=g.h-95,y=value=>top+(hi-value)/(hi-lo)*(bottom-top);
  const markers=[];
  rows.forEach((row,index)=>{
    const input=byDate.get(Number(row.trade_date));if(!input)return;
    const low=number(row.ohlcv.low);if(low===null)return;
    for(const event of chartEvents(input.kb))markers.push({date:Number(row.trade_date),key:event.key,label:event.label,
      index:state.offset+index,x:g.L+(index+.5)*g.step,y:Math.min(bottom-4,y(low)+6)});
  });
  return markers;
}

export function installKbOverlay(frame,byDate){
  const win=frame.contentWindow,doc=frame.contentDocument,canvas=doc?.getElementById('chart');
  if(!win?.paint||!canvas)throw Error('KB_OVERLAY_RENDERER_NOT_READY');
  const parent=canvas.parentElement;parent.style.position='relative';
  const overlay=doc.createElement('canvas');overlay.id='kb-event-overlay';overlay.setAttribute('aria-label','KB逐日事件标记');
  Object.assign(overlay.style,{position:'absolute',pointerEvents:'none',zIndex:'2'});parent.appendChild(overlay);
  const original=win.paint;
  function draw(){
    const state=win.RESEARCH_PANEL_STATE;if(!state?.geometry||!state.visible?.length)return;
    overlay.width=canvas.width;overlay.height=canvas.height;
    Object.assign(overlay.style,{left:canvas.offsetLeft+'px',top:canvas.offsetTop+'px',width:canvas.clientWidth+'px',height:canvas.clientHeight+'px'});
    const ctx=overlay.getContext('2d'),ratio=canvas.width/Math.max(canvas.clientWidth,1);ctx.setTransform(ratio,0,0,ratio,0,0);
    const marks=overlayMarkers(state,byDate),grouped=new Map;
    for(const mark of marks){ctx.fillStyle=mark.key==='kb_violence_k'?'#ffd366':'#59d8f2';ctx.beginPath();ctx.arc(mark.x,mark.y,2.7,0,Math.PI*2);ctx.fill();
      const group=grouped.get(mark.date)??[];group.push(mark);grouped.set(mark.date,group);}
    // All event dots remain on their K-line. Text uses non-overlapping lanes;
    // the explicitly selected day takes priority when the window is crowded.
    const chosen=Number(frame.ownerDocument.getElementById('kbSingleDate')?.value.replaceAll('-',''));
    const groups=[...grouped.values()].sort((a,b)=>Number(b[0].date===chosen)-Number(a[0].date===chosen)
      ||Number(b[0].index===state.selected)-Number(a[0].index===state.selected)
      ||Number(b.some(x=>x.key==='kb_violence_k'))-Number(a.some(x=>x.key==='kb_violence_k'))||b[0].index-a[0].index);
    const lanes=Array.from({length:2},()=>[]);ctx.font='10px sans-serif';ctx.textAlign='center';let placed=0;
    for(const group of groups){
      if(placed>=12)break;
      const label=group.map((x,i)=>i?x.label.replace(/^KB /,''):x.label).join('/'),width=Math.min(ctx.measureText(label).width+8,240);
      const x=Math.max(state.geometry.L+width/2,Math.min(state.geometry.w-state.geometry.R-width/2,group[0].x));
      const lane=lanes.findIndex(used=>used.every(([left,right])=>x+width/2+3<left||x-width/2-3>right));
      if(lane<0)continue;placed++;lanes[lane].push([x-width/2,x+width/2]);const y=13+lane*14;
      ctx.fillStyle='rgba(5,25,35,.88)';ctx.fillRect(x-width/2,y-9,width,13);ctx.fillStyle='#a9eeff';ctx.fillText(label,x,y,236);
      if(group[0].date===chosen||group[0].index===state.selected){ctx.strokeStyle='rgba(89,216,242,.45)';ctx.beginPath();ctx.moveTo(group[0].x,y+4);ctx.lineTo(group[0].x,group[0].y-3);ctx.stroke()}
      for(const mark of group)mark.label_visible=true;
    }
    win.KB_OVERLAY_MARKERS=marks;
  }
  win.paint=function(...args){const result=original.apply(this,args);draw();return result};
  const resize=()=>win.requestAnimationFrame(draw);win.addEventListener('resize',resize);win.paint();
  return ()=>{win.removeEventListener('resize',resize);if(win.paint!==original)win.paint=original;overlay.remove();};
}
