const DATASETS = {
  disposition: { label: "全范围处置", filename: "00_全范围处置.csv", expectedRows: 5572 },
  shortlist: { label: "量价初筛", filename: "01_量价初筛.csv", expectedRows: 822 },
  scores: { label: "原33评分", filename: "03_模型精选排序.csv", expectedRows: 33 },
};
const PAGE_SIZE = 40;
const state = { datasets: {}, identity: null, active: "shortlist", page: 0, selectedOriginalIndex: 0, filtered: [] };
const $ = (id) => document.getElementById(id);

function parseCsv(text) {
  const source = String(text).replace(/^\uFEFF/, "");
  const rows = [];
  let row = [], value = "", quoted = false;
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    if (quoted) {
      if (ch === '"' && source[i + 1] === '"') { value += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else value += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(value); value = ""; }
    else if (ch === "\r" || ch === "\n") {
      if (ch === "\r" && source[i + 1] === "\n") i += 1;
      row.push(value); rows.push(row); row = []; value = "";
    } else value += ch;
  }
  if (value !== "" || row.length) { row.push(value); rows.push(row); }
  return rows.filter((candidate) => !(candidate.length === 1 && candidate[0] === ""));
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function columnIndex(dataset, names) {
  for (const name of names) {
    const index = dataset.headers.indexOf(name);
    if (index >= 0) return index;
  }
  return -1;
}

function col(row, index) { return index < 0 ? "" : row[index] ?? ""; }
function field(row, dataset, names) { return col(row, columnIndex(dataset, names)); }

function htmlText(parent, value, tag = "span", className = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value == null || value === "" ? "—" : String(value);
  parent.append(element);
  return element;
}

function currentDataset() { return state.datasets[state.active]; }

function stageNames(dataset) {
  const column = columnIndex(dataset, ["信号类型", "初筛信号"]);
  if (column < 0) return [];
  return [...new Set(dataset.rows.map((row) => row[column]).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
}

function dayValues(dataset) {
  const column = columnIndex(dataset, ["结构回调日数"]);
  if (column >= 0) return [...new Set(dataset.rows.map((row) => row[column]).filter(Boolean))]
    .sort((a, b) => Number(a) - Number(b));
  const pb = columnIndex(dataset, ["R2_PB"]);
  if (pb >= 0) return [...new Set(dataset.rows.map((row) => row[pb]).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "en", { numeric: true }));
  return [];
}

function resetSelect(select, label, values) {
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = ""; all.textContent = label; select.append(all);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value; option.textContent = value; select.append(option);
  }
  select.hidden = values.length === 0;
  select.disabled = values.length === 0;
}

function configureFilters(dataset) {
  const statusColumn = columnIndex(dataset, ["结构初筛"]);
  const statusValues = statusColumn < 0 ? [] : [...new Set(dataset.rows.map((row) => row[statusColumn]).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "zh-CN"));
  resetSelect($("dispositionFilter"), "全部处置", statusValues);
  resetSelect($("stageFilter"), "全部信号阶段", stageNames(dataset));
  resetSelect($("dayFilter"), "全部回调日 / PB", dayValues(dataset));

  const nameKeys = ["结构回调日数", "D涨跌%", "原A排序", "CLIP16排序", "代码", "简称"];
  const available = nameKeys.filter((key) => dataset.headers.includes(key));
  const sort = $("archiveSort");
  sort.replaceChildren();
  const original = document.createElement("option");
  original.value = "original"; original.textContent = "原始顺序"; sort.append(original);
  for (const key of available) {
    for (const direction of key === "代码" || key === "简称" ? ["asc", "desc"] : ["asc", "desc"]) {
      const option = document.createElement("option");
      option.value = `${key}:${direction}`;
      option.textContent = `${key} ${direction === "asc" ? "↑" : "↓"}`;
      sort.append(option);
    }
  }
  sort.value = "original";
}

function activeFilters(row, dataset) {
  const query = $("archiveQuery").value.trim().toLocaleLowerCase("zh-CN");
  if (query) {
    const code = field(row, dataset, ["代码"]).toLocaleLowerCase("zh-CN");
    const name = field(row, dataset, ["简称"]).toLocaleLowerCase("zh-CN");
    if (!code.includes(query) && !name.includes(query)) return false;
  }
  const disposition = $("dispositionFilter").value;
  if (disposition && field(row, dataset, ["结构初筛"]) !== disposition) return false;
  const stage = $("stageFilter").value;
  if (stage && field(row, dataset, ["信号类型", "初筛信号"]) !== stage) return false;
  const day = $("dayFilter").value;
  if (day) {
    const selectedDay = field(row, dataset, ["结构回调日数", "R2_PB"]);
    if (selectedDay !== day) return false;
  }
  return true;
}

function stableRows(dataset) {
  const rows = dataset.rows.map((cells, originalIndex) => ({ cells, originalIndex }))
    .filter(({ cells }) => activeFilters(cells, dataset));
  const sort = $("archiveSort").value;
  if (sort === "original") return rows;
  const [key, direction] = sort.split(":");
  const keyIndex = dataset.headers.indexOf(key);
  if (keyIndex < 0) return rows;
  const multiplier = direction === "desc" ? -1 : 1;
  return rows.sort((left, right) => {
    const a = left.cells[keyIndex] ?? "", b = right.cells[keyIndex] ?? "";
    const aNumber = a.trim() === "" ? Number.NaN : Number(a);
    const bNumber = b.trim() === "" ? Number.NaN : Number(b);
    let comparison;
    if (Number.isFinite(aNumber) && Number.isFinite(bNumber)) comparison = aNumber - bNumber;
    else comparison = a.localeCompare(b, "zh-CN", { numeric: true, sensitivity: "base" });
    if (comparison === 0) return left.originalIndex - right.originalIndex;
    return comparison * multiplier;
  });
}

function selectedRow() {
  if (!state.filtered.length) return null;
  const entry = state.filtered.find(({ originalIndex }) => originalIndex === state.selectedOriginalIndex);
  return entry?.cells ?? state.filtered[0]?.cells ?? null;
}

function renderDetail(dataset, row) {
  if (!row) {
    $("detailDataset").textContent = `${DATASETS[state.active].label} · 当前筛选`;
    $("detailName").textContent = "无匹配记录";
    $("detailCode").textContent = "";
    $("detailState").textContent = "空结果";
    $("detailSummary").textContent = "筛选结果为 0；不显示其他证券或替代值。";
    $("detailPills").replaceChildren();
    $("detailFields").replaceChildren();
    $("detailFieldCount").textContent = "0 行";
    return;
  }
  const title = DATASETS[state.active].label;
  $("detailDataset").textContent = `${title} · 原始字段直读`;
  $("detailName").textContent = field(row, dataset, ["简称"]) || "未提供名称";
  $("detailCode").textContent = field(row, dataset, ["代码"]);
  $("detailState").textContent = state.active === "scores" ? "独立历史评分账本" : "只读档案 · 未接分";
  $("detailSummary").textContent = state.active === "scores"
    ? "本行是原33评分文件中的原始记录；没有通过证券代码合并回822只名单。"
    : state.active === "shortlist"
      ? "本行来自原822只量价初筛文件；所有原始列逐项显示，未查询行情或附加评分。"
      : "本行来自原5,572只全范围处置文件；所有原始列逐项显示。";
  const pills = $("detailPills"); pills.replaceChildren();
  for (const label of ["结构初筛", "信号类型", "初筛信号", "结构回调日数", "R2_PB", "合格锚数"]) {
    const value = field(row, dataset, [label]);
    if (value) htmlText(pills, `${label}：${value}`, "span", "archive-pill");
  }
  const body = $("detailFields"); body.replaceChildren();
  dataset.headers.forEach((header, index) => {
    const tr = document.createElement("tr");
    htmlText(tr, header, "th");
    const value = row[index] ?? "";
    htmlText(tr, value === "" ? "（原值为空）" : value, "td");
    body.append(tr);
  });
  $("detailFieldCount").textContent = `${dataset.headers.length} 原列 · 未补字段`;
}

function renderList(resetPage = false) {
  const dataset = currentDataset();
  if (!dataset) return;
  if (resetPage) state.page = 0;
  state.filtered = stableRows(dataset);
  const lastPage = Math.max(0, Math.ceil(state.filtered.length / PAGE_SIZE) - 1);
  state.page = Math.min(Math.max(0, state.page), lastPage);
  const start = state.page * PAGE_SIZE;
  const pageRows = state.filtered.slice(start, start + PAGE_SIZE);
  const list = $("archiveList"); list.replaceChildren();

  for (const item of pageRows) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "stock-item"; button.setAttribute("role", "option");
    button.dataset.originalIndex = String(item.originalIndex);
    const name = field(item.cells, dataset, ["简称"]) || "未提供名称";
    const code = field(item.cells, dataset, ["代码"]);
    if (item.originalIndex === state.selectedOriginalIndex) button.classList.add("active");
    htmlText(button, name, "strong"); htmlText(button, code, "small", "stock-code");
    const meta = document.createElement("span"); meta.className = "archive-row-meta";
    for (const text of [field(item.cells, dataset, ["结构初筛", "信号类型", "初筛信号"]),
      field(item.cells, dataset, ["结构回调日数", "R2_PB"]),
      field(item.cells, dataset, ["R2母起点"])]) {
      if (text) htmlText(meta, text);
    }
    if (meta.childElementCount) button.append(meta);
    button.addEventListener("click", () => {
      state.selectedOriginalIndex = item.originalIndex;
      renderList(false);
      renderDetail(dataset, item.cells);
    });
    list.append(button);
  }
  if (!pageRows.length) htmlText(list, "当前筛选没有匹配记录", "p", "archive-filter-empty");
  const unit = state.active === "scores" ? "行" : "只";
  $("sidebarTitle").textContent = `${DATASETS[state.active].label} · ${dataset.rows.length.toLocaleString("zh-CN")}${unit}`;
  $("archiveListCount").textContent = `筛选后 ${state.filtered.length.toLocaleString("zh-CN")}${unit} · 本页 ${pageRows.length}${unit}（${state.filtered.length ? start + 1 : 0}–${start + pageRows.length}）`;
  $("archiveListPage").textContent = `第 ${state.page + 1} 页 / 共 ${Math.max(1, Math.ceil(state.filtered.length / PAGE_SIZE))} 页 · 每页 ${PAGE_SIZE}只`;
  $("archivePrev").disabled = state.page === 0;
  $("archiveNext").disabled = state.page >= lastPage;
  $("pageStatus").textContent = `已读取归档原件 · ${dataset.headers.length}列 · 证券信息按源原值显示`;

  const onPage = pageRows.some(({ originalIndex }) => originalIndex === state.selectedOriginalIndex);
  if (!onPage && pageRows.length) state.selectedOriginalIndex = pageRows[0].originalIndex;
  renderDetail(dataset, selectedRow());
}

function switchDataset(id) {
  if (!DATASETS[id] || !state.datasets[id]) return;
  state.active = id; state.page = 0;
  const first = state.datasets[id].rows[0];
  state.selectedOriginalIndex = 0;
  configureFilters(state.datasets[id]);
  $("archiveQuery").value = "";
  for (const button of document.querySelectorAll("[data-dataset]")) {
    button.classList.toggle("active", button.dataset.dataset === id);
    button.setAttribute("aria-pressed", button.dataset.dataset === id ? "true" : "false");
  }
  renderList(true);
  renderDetail(state.datasets[id], first);
}

function downloadDataset(id) {
  const dataset = state.datasets[id];
  if (!dataset) return;
  const csv = `\uFEFF${[dataset.headers, ...dataset.rows].map((row) => row.map(csvCell).join(",")).join("\r\n")}\r\n`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `D17_${id}_${dataset.rows.length}_original.csv`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function identityMarkup(identity) {
  const fragment = document.createDocumentFragment();
  htmlText(fragment, `D17 冻结日期 ${identity.screen.source_date} · 来源记录 ${identity.screen.captured_at}`, "div");
  htmlText(fragment, `V3 档案展示适配器：${identity.v3_display_binding.adapter_version}`, "div");
  htmlText(fragment, `V3 实际文件字节绑定：${identity.v3_display_binding.status} · 纯展示入口`, "div");
  for (const id of ["disposition", "shortlist", "scores"]) {
    const source = identity.files[id];
    htmlText(fragment, `${DATASETS[id].label}: ${source.rows}行 × ${source.columns}列 · ${source.bytes.toLocaleString("zh-CN")} bytes`, "div");
  }
  $("sourceIdentity").replaceChildren(fragment);
}

async function init() {
  try {
    const identityResponse = await fetch("/archive-data/identity.json", { cache: "no-store" });
    if (!identityResponse.ok) throw new Error(`identity HTTP ${identityResponse.status}`);
    state.identity = await identityResponse.json();
    for (const [id, metadata] of Object.entries(DATASETS)) {
      const response = await fetch(`/archive-data/${encodeURIComponent(metadata.filename)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`${metadata.filename} HTTP ${response.status}`);
      const rows = parseCsv(await response.text());
      const [headers, ...body] = rows;
      if (!headers || body.length !== metadata.expectedRows) {
        throw new Error(`${metadata.filename} 行数异常：${body.length}`);
      }
      if (body.some((row) => row.length !== headers.length)) throw new Error(`${metadata.filename} 列数不一致`);
      state.datasets[id] = { headers, rows: body };
    }
    identityMarkup(state.identity);
    $("pageStatus").textContent = "3份原始CSV加载完成；名单、处置与历史评分未进行键关联。";
    switchDataset("shortlist");
  } catch (error) {
    $("pageStatus").textContent = `档案读取失败：${error.message}`;
    throw error;
  }
}

for (const button of document.querySelectorAll("[data-dataset]")) {
  button.addEventListener("click", () => switchDataset(button.dataset.dataset));
}
for (const select of [$("dispositionFilter"), $("stageFilter"), $("dayFilter"), $("archiveSort")]) {
  select.addEventListener("change", () => renderList(true));
}
$("archiveQuery").addEventListener("input", () => renderList(true));
$("archivePrev").addEventListener("click", () => { state.page = Math.max(0, state.page - 1); renderList(false); });
$("archiveNext").addEventListener("click", () => {
  const lastPage = Math.max(0, Math.ceil(state.filtered.length / PAGE_SIZE) - 1);
  state.page = Math.min(lastPage, state.page + 1); renderList(false);
});
for (const button of document.querySelectorAll("[data-export]")) {
  button.addEventListener("click", () => downloadDataset(button.dataset.export));
}

const originalWorkbenchElements = [
  document.querySelector("body > .stage-strip"),
  document.querySelector("body > .market-strip"),
  document.querySelector("body > .layout"),
  document.querySelector("body > .app-foot"),
].filter(Boolean);
let archiveInitialized = false;

function enterArchive() {
  originalWorkbenchElements.forEach((element) => { element.hidden = true; });
  $("p515ArchiveView").hidden = false;
  $("archiveRail").hidden = false;
  document.body.dataset.activeView = "d17-archive-preview";
  if (!archiveInitialized) {
    archiveInitialized = true;
    init();
  }
}

function leaveArchive() {
  $("p515ArchiveView").hidden = true;
  originalWorkbenchElements.forEach((element) => { element.hidden = false; });
  delete document.body.dataset.activeView;
}

$("p515ArchiveEntry").addEventListener("click", enterArchive);
$("p515ArchiveBack").addEventListener("click", leaveArchive);
window.P515_ARCHIVE_PREVIEW = {
  DATASETS, PAGE_SIZE, state, enterArchive, leaveArchive,
  exportCsv: downloadDataset,
};
