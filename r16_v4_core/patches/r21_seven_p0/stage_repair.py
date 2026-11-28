"""Materialize only the audited deltas for the frozen r21 18874 serving lanes."""
from hashlib import sha256
import json
from pathlib import Path
import sys

from seven_p0_reads import SOP_PATH, SOP_SHA

HERE = Path(__file__).resolve().parent
MAIN = "frontend/dist/assets/main-CT7TeoHf.js"
INDEX = "frontend/dist/index.html"
OVERLAY = "content_projection/read_overlay.py"
PANEL = "static/research-panel/"
HOST = PANEL + "workbench-host/"
SHELL = HOST + "dot/shell/workbench.local.mjs"
BOOTSTRAP = HOST + "bootstrap.mjs"
ARCHIVED = HOST + "archived-market-observations.mjs"
BASE_SHA = {
    MAIN: "f710014191f948495871e01bce37e70e3c9dcabb101c033084f8043598dbd534",
    INDEX: "c26b9d30f125cc6dbc867f09503e4a3ab8d1a6d30f8628208e9c166a2ae7b027",
    OVERLAY: "c97d10b4781deeeeb014f3a744d3b7eb8a3a3018aa736d26bdb7afdfcf59d813",
    SHELL: "4df924a2eaf875333ec6d273858a6efb176888e8b2e1460e61b96f3a240d12ff",
    ARCHIVED: "b1ed6c5fa9c48d9220067cc2b0028fcfcb8ad2ad026f7028ace460b7b207c52c",
    PANEL + "workbench.html": "c0916a16ca35f06ffe671a4e5807a134bf42dc6e2b601fb2ee60ce610e0867d7",
    BOOTSTRAP: "8724134cd272bee013be7fad88477bd2bbd4884e930b08fbefa41f91dc33e6c9",
}

# The shipped main bundle contains the older production-compatible SOP and date shell.
# Keep its compiled siblings and unrelated UI. Propagate the active ResearchView response
# to the App header without mutating the selected day or triggering another exact request.
MAIN_EDITS = (
    (
        '__name:"ResearchView",props:{archiveDate:{}},setup(n){',
        '__name:"ResearchView",props:{archiveDate:{}},emits:["researchIdentity"],setup(n,{emit:r21Emit}){',
    ),
    (
        'async function C(B,v){const h=++d;u.value=!0,o.value="",i.value=null;try{const q=await B();se(q,v),h===d&&(i.value=q)}',
        'async function C(B,v){const h=++d;u.value=!0,o.value="",i.value=null;r21Emit("researchIdentity",null);'
        'try{const q=await B();se(q,v);if(h===d){i.value=q;r21Emit("researchIdentity",{requested:a.archiveDate,'
        'source:q.research_date,mode:v?"EXACT":"LATEST",archive:q.daily_archive_status??"CANNOT_CONFIRM",'
        'lane:q.lane_status??q.status??"CANNOT_CONFIRM"})}}',
    ),
    ('__name:"App",setup(n){', '__name:"App",setup(n){const r21ResearchHeader=j(null);'),
    (
        'r(X)?(s(),l("small",Kf,t(r(Ut)),1)):y("",!0)',
        'r(X)?(s(),l("small",Kf,t(r(Nt)&&r21ResearchHeader.value?.requested===r(X)?'
        '`实际载入上海研究日：${r21ResearchHeader.value.source.replace(/^(\\d{4})(\\d{2})(\\d{2})$/,"$1-$2-$3")} · ${r21ResearchHeader.value.mode} · '
        '日档状态 ${r21ResearchHeader.value.archive} · 研报流 ${r21ResearchHeader.value.lane}`:r(Ut)),1)):y("",!0)',
    ),
    (
        'r(Nt)?(s(),xe(tv,{key:5,"archive-date":r(X),"initial-feed-filter":r(ln)?"wechat":"latest"},null,8,["archive-date","initial-feed-filter"]))',
        'r(Nt)?(s(),xe(tv,{key:5,"archive-date":r(X),"initial-feed-filter":r(ln)?"wechat":"latest",'
        'onResearchIdentity:g.r21ResearchIdentity||(g.r21ResearchIdentity=p=>{r21ResearchHeader.value=p})},'
        'null,8,["archive-date","initial-feed-filter"]))',
    ),
    (
        'v.pool_hit?m(v.pool_memberships)||"汇总命中；分池归因不可确认":"未命中已物化来源池"',
        'v.pool_hit===null?"来源池命中待核":v.pool_hit?m(v.pool_memberships)||"汇总命中；分池归因不可确认":"未命中已物化来源池"',
    ),
    (
        'v.stage_memberships.length?T(v.stage_memberships):"未命中已物化阶段"',
        'v.stage_coverage_known===false?"阶段命中待核":v.stage_memberships.length?T(v.stage_memberships):"未命中已物化阶段"',
    ),
)

OVERLAY_EDITS = (
    ('from .workbench_parity import WorkbenchParity\n',
     'from .workbench_parity import WorkbenchParity\nfrom .seven_p0_reads import SevenP0Reads\n'),
    (
        '        self.preselection = BoundPreselection(app.state.store, data / "r21_preselection_proof.json")\n',
        '        self.preselection = BoundPreselection(app.state.store, data / "r21_preselection_proof.json")\n'
        '        self.seven_p0_reads = SevenP0Reads(app.state.store, data, self.preselection)\n',
    ),
    (
        "        banner = ('<aside role",
        '        identity = "研报决策台" if research_selected else day\n'
        "        banner = ('<aside role",
    ),
    ("f'隔离只读快照 · {day} · {source_note}'", "f'隔离只读快照 · {identity} · {source_note}'"),
    (
        '        if response is None:\n            return await self.app(scope, receive, send)\n',
        '        if response is None:\n            response = self.seven_p0_reads.resolve(path, query)\n'
        '        if response is None:\n            return await self.app(scope, receive, send)\n',
    ),
)

RATE_CONFIGURATION = """ $('showStockRates').disabled=Boolean(formulaGroups);
 document.querySelector('label[for="scope"]').hidden=Boolean(formulaGroups);
 for(const option of $('stockSort').options){
  if(!/^d[25]_/.test(option.value))continue;
  option.hidden=Boolean(formulaGroups);
  option.disabled=Boolean(formulaGroups);
 }
 for(const header of document.querySelectorAll('[data-stock-sort="d2"], [data-stock-sort="d5"]'))header.disabled=Boolean(formulaGroups);
 if(formulaGroups&&/^d[25]_/.test($('stockSort').value))$('stockSort').value='name_asc';"""
RATE_CONTROLS = """function historyRateAvailable(currentDay,horizon){
 return group!=='top200'&&group!=='v192'&&!currentDay?.formula_groups
   &&Boolean(currentDay?.rows?.some(row=>
     (group==='all'||row.group_states?.[group]==='TRUE')&&historyRate(row,group,horizon).valid));
}
function updateRateControls(currentDay){
 const available={d2:historyRateAvailable(currentDay,'d2'),d5:historyRateAvailable(currentDay,'d5')};
 const paired=Object.values(available).some(Boolean);
 const jump=$('showStockRates');
 const message=group==='top200'?'Top200 不提供 D+2 / D+5 成功率':'所选日期及分组暂无已核验 D+2 / D+5 成功率';
 jump.disabled=!paired;
 jump.textContent=paired?'D+2 / D+5 →':'D+2 / D+5 暂不可用';
 jump.title=paired?'':message;
 jump.setAttribute('aria-label',paired?'横移到 D+2 / D+5 成功率':message);
 for(const option of $('stockSort').options){
  if(!/^d[25]_/.test(option.value))continue;
  option.hidden=Boolean(currentDay?.formula_groups);
  option.disabled=!available[option.value.slice(0,2)];
 }
 const sort=$('stockSort');
 if(/^d[25]_/.test(sort.value)&&!available[sort.value.slice(0,2)])sort.value='name_asc';
 return available;
}
function updateSortHeaders(){
 const available=updateRateControls(day);
 for(const button of document.querySelectorAll('[data-stock-sort]')){
  const key=button.dataset.stockSort,mode=$('stockSort').value,active=mode.startsWith(key+'_');
  button.disabled=group==='top200'||(Object.hasOwn(available,key)&&!available[key]);
  button.classList.toggle('active',active);
  const label=({name:'股票名称',price:'股价',percent_change:'涨幅',amount:'成交额',d2:'D+2',d5:'D+5'})[key];
  button.textContent=label+(active?(mode.endsWith('_asc')?' ↑':' ↓'):'');
  const description=button.disabled?(Object.hasOwn(available,key)
    ?label+'，所选日期及分组暂无已核验成功率':label+'，Top200 按收盘名次显示')
    :button.textContent+'，点击切换排序';
  button.setAttribute('aria-label',description);
  button.title=description;
 }
}
"""
ORIGINAL_RATE_SORT = """function updateSortHeaders(){for(const b of document.querySelectorAll('[data-stock-sort]')){const key=b.dataset.stockSort,mode=$('stockSort').value,active=mode.startsWith(key+'_');b.disabled=group==='top200'||Boolean(day?.formula_groups&&['d2','d5'].includes(key));b.classList.toggle('active',active);b.textContent=({name:'股票名称',price:'股价',percent_change:'涨幅',amount:'成交额',d2:'D+2',d5:'D+5'})[key]+(active?(mode.endsWith('_asc')?' ↑':' ↓'):'');b.setAttribute?.('aria-label',b.textContent+'，点击切换排序');}}
"""
SHELL_EDITS = (
    (RATE_CONFIGURATION,
     """ document.querySelector('label[for="scope"]').hidden=Boolean(formulaGroups);
 updateRateControls(currentDay);"""),
    (ORIGINAL_RATE_SORT, RATE_CONTROLS),
    (
        "showArchivedMarketObservations($('marketCards')).catch(()=>{});",
        """$('macLegacyStockPage').addEventListener('click',event=>{
 const params=new URLSearchParams({date:day?.source_date??selection().date});
 if(day&&selected?.eligible_candidate&&day.rows.some(row=>row.symbol===selected.symbol))params.set('symbol',selected.symbol);
 event.currentTarget.href='legacy-daily.html?'+params;
});""",
    ),
    (
        'window.StockPanelHost.unbindDay();observationLoading=false;',
        "window.StockPanelHost.unbindDay();void showArchivedMarketObservations($('marketCards'),null);observationLoading=false;",
    ),
    (
        'window.StockPanelHost.bindDay(day);renderFilters();renderSecondary();const initial=renderList(true,routeSelection);',
        "window.StockPanelHost.bindDay(day);void showArchivedMarketObservations($('marketCards'),day.observation_date);renderFilters();renderSecondary();const initial=renderList(true,routeSelection);",
    ),
    (
        "if(!day)return;if(group==='top200'){renderTop200List(selectFirst);return null;}filtered=filterStocks",
        "if(!day)return;if(group==='top200'){renderTop200List(selectFirst);return null;}updateRateControls(day);filtered=filterStocks",
    ),
)


BOOTSTRAP_EDITS = (
    (
        'contextReply={...value,markets:{...value.markets,US:unknownUsContext',
        'contextReply={...value,markets:{...contextReply.markets,...value.markets,US:unknownUsContext',
    ),
    (
        '''    if(market==='US'){
      const dates=contextReply.us_context;''',
        '''    if(market==='US'){
      const dates=contextReply.us_context;
      if(dates?.us_session_date?.replaceAll('-','')!==identity.observation_date.replaceAll('-','')){
        renderMarketCard(host,market,unknownUsContext('所选观察日无同日美股收盘来源'),identity,document);
        continue;
      }''',
    ),
    (
        '    renderMarketCard(host,market,value,identity,document);',
        '''    if(market!=='US'&&value.source_asof
      &&!value.source_asof.split(' / ').every(stamp=>stamp.startsWith(identity.observation_date+'T'))){
      value={status:'UNKNOWN',summary:'所选观察日无同日收盘来源 · CANNOT_CONFIRM'};
    }
    renderMarketCard(host,market,value,identity,document);''',
    ),
)

def digest(value):
    return sha256(value).hexdigest()


def replace_once(content, edits, source):
    for before, after in edits:
        if content.count(before) != 1:
            raise RuntimeError(f"ACTIVE_PREIMAGE_NOT_UNIQUE: {source}: {before[:100]}")
        content = content.replace(before, after, 1)
    return content


def stage(root, output):
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("WRITER_STAGING_MUST_BE_OUTSIDE_ACTIVE_ROOT")
    original = {}
    for target, expected in BASE_SHA.items():
        raw = (root / target).read_bytes()
        if digest(raw) != expected:
            raise RuntimeError(f"ACTIVE_PREIMAGE_HASH_MISMATCH: {target}")
        original[target] = raw
    output.mkdir(parents=True, exist_ok=False)
    files = []

    def save(target, data):
        active = root / target
        old_hash = BASE_SHA.get(target)
        if (old_hash is None) != (not active.exists()):
            raise RuntimeError(f"ACTIVE_PREIMAGE_PRESENCE_CONFLICT: {target}")
        source = output / "files" / target
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
        files.append({"target": target, "source": str(source.relative_to(output)),
                      "old_sha256": old_hash, "new_sha256": digest(data)})

    def patched(base, edits):
        return replace_once(original[base].decode("utf-8"), edits, base).encode("utf-8")

    main = patched(MAIN, MAIN_EDITS)
    main_target = f"frontend/dist/assets/main-r21-p0-{digest(main)[:12]}.js"
    save(main_target, main)
    save(INDEX, patched(INDEX, ((Path(MAIN).name, Path(main_target).name),)))
    save(OVERLAY, patched(OVERLAY, OVERLAY_EDITS))
    save("content_projection/seven_p0_reads.py", (HERE / "seven_p0_reads.py").read_bytes())
    sop = Path(SOP_PATH).read_bytes()
    if digest(sop) != SOP_SHA:
        raise RuntimeError("SOP_PREIMAGE_HASH_MISMATCH")
    save("content_projection/p0_single_stock_repair.md", sop)
    save(PANEL + "legacy-daily.html", (HERE / "legacy-daily.html").read_bytes())
    save(PANEL + "legacy-daily.mjs", (HERE / "legacy-daily.mjs").read_bytes())
    archive = (HERE / "archived-market-observations.mjs").read_bytes()
    save(ARCHIVED, archive)
    shell = patched(SHELL, SHELL_EDITS + (
        ("'../../archived-market-observations.mjs'", f"'../../archived-market-observations.mjs?v={digest(archive)[:12]}'"),
    ))
    save(SHELL, shell)
    bootstrap = patched(BOOTSTRAP, BOOTSTRAP_EDITS + (
        ("./dot/shell/workbench.local.mjs?v=514e78b1505b",
         f"./dot/shell/workbench.local.mjs?v={digest(shell)[:12]}"),
    ))
    save(BOOTSTRAP, bootstrap)
    save(PANEL + "workbench.html", patched(PANEL + "workbench.html", (
        ("workbench-host/bootstrap.mjs?v=514e78b1505b", f"workbench-host/bootstrap.mjs?v={digest(bootstrap)[:12]}"),
    )))
    manifest = output / "ACTIVATION_MANIFEST.json"
    manifest.write_text(json.dumps({"active_root": str(root), "files": files}, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: stage_repair.py ACTIVE_ROOT NEW_WRITER_STAGING_DIR")
    print(stage(Path(sys.argv[1]), Path(sys.argv[2])))
