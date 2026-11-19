#!/usr/bin/env python3
"""Build a loopback-only archive overlay from the current V4 workbench shell."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ARCHIVE_CSS = r"""
<style id="p515-archive-preview">
  .brand small { font-size: 12px; }
  .archive-entry { margin-left:2px; border-color:var(--cyan); color:#fff; font-weight:650; }
  #p515ArchiveView { display:block; padding:10px; }
  #p515ArchiveView[hidden] { display:none !important; }
  .archive-intro { display:flex; align-items:center; justify-content:space-between; gap:10px; border:1px solid var(--line); border-radius:6px; background:#031b2b; padding:8px 12px; margin-bottom:8px; }
  .archive-intro h1 { margin:0; font-size:18px; }
  .archive-intro p { margin:2px 0 0; color:var(--muted); font-size:10px; }
  .archive-strip { align-items:center; }
  .archive-date { display:grid; gap:3px; align-content:center; padding:0 10px 0 2px; border-right:1px solid var(--line); }
  .archive-date strong { font-size:15px; color:var(--text); }
  .archive-date small { font-size:10px; color:var(--muted); }
  .archive-tabs { grid-template-columns:repeat(3,minmax(0,1fr)); }
  .archive-tabs button { min-height:58px; }
  .archive-tabs button strong { display:block; font-size:15px; }
  .archive-tabs button span { display:block; font-size:10px; color:var(--muted); }
  .archive-banner { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; align-items:center; height:auto; min-height:62px; }
  .archive-banner > div { min-width:0; }
  .archive-banner strong { display:block; font-size:13px; }
  .archive-banner small { display:block; color:var(--muted); font-size:10px; }
  .archive-layout { grid-template-columns:clamp(230px,20vw,288px) minmax(0,1fr) clamp(250px,22vw,320px); }
  .archive-sidebar { gap:2px; }
  .archive-sidebar .scope-options { display:grid; gap:4px; }
  .archive-sidebar label { font-size:10px; color:var(--muted); }
  .archive-sidebar select { width:100%; font-size:11px; }
  .archive-sidebar .filter-pair { display:grid; grid-template-columns:1fr 1fr; gap:5px; }
  .archive-sidebar #query { margin:5px 0; }
  .archive-sidebar #archiveList { flex:1; overflow:auto; min-height:160px; max-height:clamp(180px,calc(100vh - 690px),380px); }
  .archive-sidebar .stock-item { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:1px 6px; padding:6px; }
  .archive-sidebar .stock-item strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .archive-sidebar .stock-item .stock-code { float:none; margin:2px 0 0; text-align:right; }
  .archive-sidebar .archive-row-meta { grid-column:1 / -1; display:flex; gap:8px; color:var(--muted); font-size:9px; white-space:nowrap; overflow:hidden; min-width:0; }
  .archive-sidebar .archive-row-meta > span { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-width:0; }
  .archive-sidebar .archive-row-meta > span:nth-child(2) { max-width:96px; }
  .archive-main { display:flex; flex-direction:column; gap:8px; }
  .archive-card { border:1px solid var(--line); border-radius:6px; background:#031b2b; padding:10px; }
  .archive-card h1 { font-size:20px; margin:0; }
  .archive-card h1 small { font-size:12px; color:var(--muted); margin-left:8px; }
  .archive-card .identity { margin-bottom:8px; }
  .archive-note { color:var(--muted); font-size:11px; margin:5px 0 0; }
  .archive-pill { display:inline-block; border:1px solid #287486; border-radius:12px; padding:3px 7px; font-size:10px; color:var(--cyan); margin:2px 3px 2px 0; }
  .archive-details { overflow:auto; min-height:200px; max-height:calc(100vh - 430px); }
  .archive-fields { border-collapse:collapse; width:100%; font-size:11px; }
  .archive-fields th,.archive-fields td { border-bottom:1px solid #16445b; padding:5px 7px; text-align:left; vertical-align:top; overflow-wrap:anywhere; }
  .archive-fields th { width:32%; color:var(--muted); font-weight:500; }
  .archive-rail { overflow:auto; padding:10px; }
  .archive-rail h2 { font-size:14px; margin:4px 0 8px; }
  .archive-rail h3 { font-size:11px; margin:12px 0 4px; }
  .archive-rail p,.archive-rail li { font-size:10px; line-height:1.55; color:var(--muted); }
  .archive-export { display:grid; gap:6px; }
  .archive-export button { text-align:left; font-size:10px; }
  .archive-source-id { border-top:1px solid var(--line); padding-top:6px; overflow-wrap:anywhere; }
  .archive-source-id code { font-size:9px; color:var(--cyan); }
  .archive-foot { margin:8px 12px 10px; color:var(--muted); font-size:10px; }
  .archive-controls { display:flex; gap:5px; align-items:center; margin-top:4px; }
  .archive-controls button { flex:1; }
  .archive-filter-empty { padding:12px; color:var(--muted); }
  @media(max-width:1050px) {
    .archive-layout { grid-template-columns:230px minmax(0,1fr); }
    .archive-rail { grid-column:1 / -1; min-height:220px; height:auto; }
  }
  @media(max-width:700px) {
    .archive-strip { height:auto; grid-template-columns:1fr; }
    .archive-date { border-right:0; border-bottom:1px solid var(--line); padding:0 0 5px; }
    .archive-layout { display:flex; flex-direction:column; }
    .archive-layout > * { width:100%; min-height:240px; height:auto; }
    .archive-sidebar #archiveList { max-height:280px; }
    .archive-details { max-height:none; }
  }
</style>
"""

ARCHIVE_VIEW = r'''<section id="p515ArchiveView" hidden aria-label="D17回顾档案预览">
<div class="archive-intro"><div><h1>D17回顾档案 · 模型未接入</h1><p>由原 V4 工作台入口进入的隔离只读预览；D17 原始名单、处置与历史评分保持分账。</p></div><button id="p515ArchiveBack" type="button">返回原工作台</button></div>
<section class="stage-strip archive-strip" aria-label="D17档案类别">
  <div class="archive-date"><label>档案交易日</label><strong>2026-11-17</strong><small>原件冻结；不读取后续行情</small></div>
  <nav id="datasetTabs" class="stage-timeline archive-tabs" aria-label="档案数据集">
    <button type="button" data-dataset="shortlist" class="active"><strong>量价初筛</strong><span>822只 · 默认主名单</span></button>
    <button type="button" data-dataset="disposition"><strong>全范围处置</strong><span>5,572只 · 原处置记录</span></button>
    <button type="button" data-dataset="scores"><strong>原33评分</strong><span>33行 · 独立历史账本</span></button>
  </nav>
</section>
<section class="market-strip archive-banner" aria-label="档案范围与边界">
  <div><strong>789 只源无分</strong><small>源表未提供评分；不以缺失推断概率</small></div>
  <div><strong>822 只主名单</strong><small>822 行全部未接分；接分 0 行</small></div>
  <div><strong>33 行历史评分</strong><small>原始 20 列 / 660 个数据单元；与822只名单分开</small></div>
</section>
<div class="layout archive-layout">
  <aside class="sidebar archive-sidebar" aria-label="档案筛选与分页">
    <div class="sidebar-title"><strong id="sidebarTitle">量价初筛 · 822只</strong><span class="subtle">原序可复核</span></div>
    <section class="scope-options" aria-label="筛选条件">
      <label for="dispositionFilter">处置状态</label><select id="dispositionFilter" aria-label="处置状态"></select>
      <div class="filter-pair"><div><label for="stageFilter">信号阶段</label><select id="stageFilter" aria-label="信号阶段"></select></div><div><label for="dayFilter">回调日 / PB</label><select id="dayFilter" aria-label="回调日或PB"></select></div></div>
      <label for="archiveQuery">名称或证券代码</label><input id="archiveQuery" type="search" placeholder="搜索名称或代码" aria-label="搜索名称或代码">
      <label for="archiveSort">稳定排序</label><select id="archiveSort" aria-label="稳定排序"></select>
    </section>
    <p id="archiveListCount" class="counts" aria-live="polite"></p>
    <div id="archiveList" role="listbox" aria-label="档案证券列表"></div>
    <div class="list-pager"><button id="archivePrev" type="button">上一页</button><span id="archiveListPage"></span><button id="archiveNext" type="button">下一页</button></div>
    <p id="pageStatus" class="archive-note" role="status" aria-live="polite">正在读取原归档…</p>
  </aside>
  <main class="archive-main" aria-label="档案详情">
    <section class="archive-card">
      <div class="identity"><div><span id="detailDataset" class="eyebrow">量价初筛 · 原始候选</span><h1><span id="detailName">载入中</span><small id="detailCode"></small></h1></div><span id="detailState" class="review-badge">只读档案</span></div>
      <div id="detailPills" aria-label="来源字段标签"></div>
      <p id="detailSummary" class="archive-note">原字段原值展示。未将原33行评分并入822行名单。</p>
    </section>
    <section class="archive-card archive-details" aria-label="原始字段与值">
      <div class="section-head"><h2>原始字段与值</h2><span id="detailFieldCount" class="status"></span></div>
      <table class="archive-fields"><tbody id="detailFields"></tbody></table>
    </section>
  </main>
  <aside id="archiveRail" class="workflow-rail archive-rail" aria-label="来源身份与原生导出">
    <h2>原生 CSV 导出</h2>
    <p>由浏览器 Blob → object URL → anchor 下载。只导出各原表全部行和原字段，不按当前筛选缩减。</p>
    <div class="archive-export">
      <button type="button" data-export="disposition">导出 5,572 行全范围处置原表</button>
      <button type="button" data-export="shortlist">导出 822 行量价初筛原表</button>
      <button type="button" data-export="scores">导出 33 行原评分独立账本</button>
    </div>
    <h3>原名单与评分关系</h3>
    <p>789 只源无分；822 行主名单全部未接分（接分 0）；33 行原评分保留为独立原账本。页面不按证券键关联旧分。</p>
    <h3>来源身份</h3>
    <div id="sourceIdentity" class="archive-source-id">读取档案身份中…</div>
    <h3>功能边界</h3>
    <ul><li>使用 D17 已归档 CSV 原件。</li><li>不调用市场行情、模型 API、训练或静态评分。</li><li>排序仅改变浏览次序；稳定并列按原始行序。</li><li>本页为回顾档案预览，未接入生产工作台。</li></ul>
  </aside>
</div>
<div class="app-foot archive-foot">D17 回顾档案 · RESEARCH_ONLY=true · production_allowed=false · buy_gate_updated=false · orders_sent=false</div>
</section>
<script type="module" src="/archive-preview.mjs"></script>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-html", required=True)
    parser.add_argument("--output-html", required=True)
    parser.add_argument("--expected-sha256", default="31d362bd8e256a812e94a5065d9dd5e9f6fbff3170b0de250a49a92d079d69ed")
    args = parser.parse_args()

    original_path = Path(args.original_html)
    source = original_path.read_bytes()
    source_sha = hashlib.sha256(source).hexdigest()
    if source_sha != args.expected_sha256:
        raise SystemExit(f"CANNOT_CONFIRM: original workbench HTML SHA mismatch: {source_sha}")
    decoded = source.decode("utf-8")
    head_end = decoded.find("</head>")
    if head_end < 0 or "<body>" not in decoded:
        raise SystemExit("CANNOT_CONFIRM: original workbench shell boundaries not found")
    head = decoded[: head_end + len("</head>")]
    head = re.sub(r'<meta name="framework-api-base"[^>]*>', "", head)
    head = re.sub(r"<title>.*?</title>", "<title>D17 原生档案预览 · 跨市场观察工作台</title>", head, count=1, flags=re.S)
    head = head.replace("</head>", ARCHIVE_CSS + "</head>")
    output = Path(args.output_html)
    output.parent.mkdir(parents=True, exist_ok=True)
    body_open = decoded.find("<body>") + len("<body>")
    body_close = decoded.rfind("</body>")
    if body_close <= body_open:
        raise SystemExit("CANNOT_CONFIRM: original workbench body end not found")
    body = decoded[body_open:body_close]
    entry_anchor = '<span class="private-badge">Mac本地 · 同源只读</span>'
    if entry_anchor not in body:
        raise SystemExit("CANNOT_CONFIRM: original workbench header entry anchor not found")
    body = body.replace(entry_anchor, entry_anchor + '<button id="p515ArchiveEntry" class="archive-entry" type="button">D17 档案预览</button>', 1)
    original_loading = '<p id="loadingState" role="status" aria-live="polite">正在读取研究资料…</p>'
    if original_loading not in body:
        raise SystemExit("CANNOT_CONFIRM: original workbench loading-state anchor not found")
    body = body.replace(
        original_loading,
        '<p id="loadingState" role="status" aria-live="polite">原 V4 工作台静态隔离外壳；生产 Bootstrap 与 API 已禁用。点击右上角 D17 档案预览打开只读历史归档。</p>',
        1,
    )
    body = re.sub(r'<script\b[^>]*>.*?</script>', "", body, flags=re.S)
    with output.open("w", encoding="utf-8", newline="") as target:
        target.write(head + "<body>" + body + ARCHIVE_VIEW + "</body></html>")
    receipt = {
        "artifact": str(output),
        "artifact_bytes": output.stat().st_size,
        "artifact_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "derived_from_original_workbench_html": str(original_path),
        "original_workbench_html_bytes": len(source),
        "original_workbench_html_sha256": source_sha,
        "reused": [
            "original complete workbench body DOM retained except the added archive-entry button",
            "original workbench CSS at workbench-host/dot/shell/workbench.css",
            "workbench mast/stage-strip/market-strip/layout/sidebar/main/workflow-rail visual system",
            "workbench pageSize=40, list-pager markup, and page-bound clamp behavior; controls are namespaced in the archive panel",
            "numeric283-panel.js native Blob/object-URL/anchor CSV download pattern",
        ],
        "isolated_replacements": [
            "live bootstrap and all V4 API readers removed from the isolated runtime",
            "D17 archive is opened only by clicking the added button in the retained workbench masthead",
            "market/industry/workflow controls remain inert static placeholders; archive reads only D17 CSVs",
            "original 33-row score ledger remains separate and is never joined to the 822-row source",
        ],
        "original_workbench_DOM_retained": True,
        "live_scripts_included": False,
        "framework_api_base_meta_included": False,
    }
    receipt_path = output.with_name("ASSEMBLY_RECEIPT.json")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
