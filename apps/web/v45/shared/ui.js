import {normaliseDate,statusKind} from "./data.js";

export const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
export const text=value=>value===null || value===undefined || value==="" ? "未知" : typeof value==="object" ? JSON.stringify(value) : String(value);
export const dateInput=value=>{const d=normaliseDate(value);return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`;};
export const pill=value=>`<span class="v45-pill ${statusKind(value)}">${esc(value??"CANNOT_CONFIRM")}</span>`;
export const lines=values=>values.filter(x=>x!==null && x!==undefined && x!=="").map(x=>`<p>${esc(text(x))}</p>`).join("");
export const card=(title,status,body)=>`<article class="v45-evidence"><h3>${esc(title)}</h3>${pill(status)}${body}</article>`;
export const detail=(title,value)=>`<details><summary>${esc(title)}</summary><pre class="v45-detail">${esc(JSON.stringify(value??null,null,2))}</pre></details>`;
export function setStatus(message,status="CANNOT_CONFIRM",id="status") {
  const node=document.getElementById(id);node.className="v45-status "+statusKind(status);node.textContent=message;
}
export function remember(values) {
  const query=new URLSearchParams(location.search);
  for(const [key,value] of Object.entries(values)) {
    if(value===null || value===undefined || value==="")query.delete(key);else query.set(key,String(value));
  }
  history.replaceState(null,"",location.pathname+(query.size?"?"+query:""));
}
export function pageLink(page,{date,observationDate,sourceDate,market,symbol,group,search,source,pageNumber,runId}={}) {
  const query=new URLSearchParams();
  const observation=observationDate || date;
  const material=sourceDate || date;
  const values=page==="selection" ? {date:observation,market,search,source,page:pageNumber}
    : page==="research" ? {date:material,observationDate:observation,market,symbol,group,search,source,page:pageNumber,runId}
      : {date:observation,sourceDate:material,market,symbol,group,search,source,page:pageNumber,runId};
  for(const [k,v] of Object.entries(values))if(v!==null && v!==undefined && v!=="")query.set(k,String(v));
  return `/v45/${page}/?${query}`;
}
export function updateNav(context) {
  for(const page of ["selection","research","review"])document.querySelectorAll(`[data-page="${page}"]`).forEach(a=>a.href=pageLink(page,context));
}
export function safeAssetUrl(value) {
  if(typeof value!=="string" || !value.startsWith("/api/v4/research/a-share/original-chart/"))return null;
  const url=new URL(value,location.origin);
  return url.origin===location.origin ? url.pathname+url.search : null;
}
export function maturityCard(label,value) {
  if(!value)return card(label,"CANNOT_CONFIRM","<p>原来源未提供该周期的统计。</p>");
  const cases=[...(value.cases??[])].sort((a,b)=>String(b.event_date??"").localeCompare(String(a.event_date??"")));
  const latest=value.latest??cases[0];
  return card(label,value.status??(value.not_matured?"PARTIAL_NOT_MATURED":value.total===0?"READY_EMPTY":"DESCRIPTIVE_STATS"),
    lines([`总案例 ${text(value.total)} · 成熟有效 ${text(value.valid)} · 未成熟 ${text(value.not_matured)}`,
      `缺价 ${text(value.missing_price)} · 非有限价格 ${text(value.nonfinite_price)} · 非正价格 ${text(value.nonpositive_price)} · 非有限收益 ${text(value.nonfinite_return)}`,
      `原分母核对：${text(value.reconciliation?.matches)} · 已分类 ${text(value.reconciliation?.classified_total)}`])+
    (latest?`<p class="v45-latest"><strong>最新事件 ${esc(latest.event_date)}</strong> → ${esc(latest.target_date)}：${pill(latest.status)} · 收益 ${latest.return_pct===null||latest.return_pct===undefined?"未知":esc(latest.return_pct)+"%"}</p>`:"<p>最新事件：未提供；不由历史均值推断。</p>")+
    (cases.length?`<details><summary>查看 ${cases.length} 条原事件</summary><ul>${cases.map(c=>`<li>${esc(c.event_date)} → ${esc(c.target_date)} · ${esc(c.status)} · ${c.return_pct==null?"收益未知":esc(c.return_pct)+"%"}</li>`).join("")}</ul></details>`:"")+
    "<p class=\"v45-muted\">统计沿用来源时点及市场交易日历，当前墙钟不改变冻结成熟度。</p>");
}
