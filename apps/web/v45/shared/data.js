// Calendar navigation only. The original market API remains authoritative for trading days.
export const DEFAULT_DATE = new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Shanghai"}).format(new Date()).replaceAll("-","");
export const FORMULA_COMPARISONS = Object.freeze([
  { sourceDate: "20261111", observationDate: "20261112", original: 44, v192: 25, common: 0, originalOnly: 44, v192Only: 25, status: "FROZEN_COMPARISON" },
  { sourceDate: "20261112", observationDate: "20261113", original: 40, v192: 10, common: 1, originalOnly: 39, v192Only: 9, status: "FROZEN_COMPARISON" },
]);

export function normaliseDate(value) {
  const digits = String(value ?? "").replaceAll("-", "");
  if (!/^\d{8}$/.test(digits)) throw new Error("日期必须为YYYYMMDD");
  const year = Number(digits.slice(0, 4)), month = Number(digits.slice(4, 6)), day = Number(digits.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) throw new Error("日期无效");
  return digits;
}

export function marketOf(value) {
  const market = String(value ?? "").toUpperCase();
  return market === "HK" || market === "HK_CONNECT" || market === "HK_SECURITIES" ? "HK" : market === "A_SHARE" || market === "A" ? "A" : market;
}

export function securityIdentity(marketValue, symbolValue) {
  const market = marketOf(marketValue);
  const raw = String(symbolValue ?? "").trim().toUpperCase();
  if (!raw || !["A","HK"].includes(market)) return "";
  if (market === "A" && (/^HK\./.test(raw) || /\.HK$/.test(raw))) return "";
  if (market === "HK" && (/^A\./.test(raw) || /\.(SZ|SH|BJ)$/.test(raw))) return "";
  const code = raw.replace(/^A\./, "").replace(/^HK\./, "").replace(/\.(SZ|SH|BJ|HK)$/, "");
  if (market === "A" && !/^\d{6}$/.test(code)) return "";
  if (market === "HK" && !/^\d{1,5}$/.test(code)) return "";
  return market + ":" + (market === "HK" ? code.padStart(5,"0") : code);
}

export function apiSymbol(marketValue, symbolValue) {
  const market = marketOf(marketValue);
  const raw = String(symbolValue ?? "").trim().toUpperCase();
  const identity=securityIdentity(market,raw);
  if (!identity) throw new Error("证券与市场身份不匹配");
  if (market === "HK") return "HK." + identity.split(":")[1];
  if (/\.(SZ|SH|BJ)$/.test(raw)) return raw;
  const code = raw.replace(/^A\./, "");
  if (/^(92|[48])/.test(code)) return code + ".BJ";
  if (/^[569]/.test(code)) return code + ".SH";
  if (/^[023]/.test(code)) return code + ".SZ";
  if (/^[48]/.test(code)) return code + ".BJ";
  return code;
}

export function displaySymbol(marketValue, symbolValue) {
  const market = marketOf(marketValue);
  const raw = String(symbolValue ?? "").trim().toUpperCase();
  if (market === "A") return raw.replace(/^A\./, "");
  if (market === "HK") return raw.replace(/^HK\./, "").replace(/\.HK$/, "") + ".HK";
  return raw;
}

function sourceEntry(pool, row) {
  return {
    poolId: String(pool.pool_id ?? "UNKNOWN_SOURCE"),
    poolStatus: String(pool.status ?? "CANNOT_CONFIRM"),
    sourceDate: row.source_date || row.signal_date || pool.signal_date || null,
    rank: row.original_rank ?? row.pool_rank ?? row.rank ?? row.stage_rank ?? null,
    score: row.original_score ?? row.pool_score ?? row.score ?? row.stage_score ?? null,
    sourceRole: row.source_role ?? pool.source_role ?? null,
    sourceSha256: row.source_sha256 ?? pool.source_sha256 ?? pool.source_artifact_sha256 ?? null,
    stageSelectionEligible: row.stage_selection_eligible ?? pool.stage_selection_eligible ?? null,
    sourceMergeRole: row.source_merge_role ?? pool.source_merge_role ?? null,
    reason: row.source_trace || row.reason || row.research_title || row.recommendation_status || null,
    decision: row.recommendation_status ?? row.candidate_role ?? pool.recommendation_status ?? null,
    quoteAsOf: row.source_last_bar_time || row.quote_asof || row.source_time || row.update_time || null,
    runId: row.source_run_id || pool.source_run_id || null,
    evidenceMode: row.source_mode || pool.source_mode || row.evidence_mode || pool.evidence_mode || null,
    temporalCutoffSafe: row.temporal_cutoff_safe ?? pool.temporal_cutoff_safe ?? null,
  };
}

const countOrNull = value => value !== null && value !== undefined && value !== "" && Number.isInteger(Number(value)) && Number(value)>=0 ? Number(value) : null;
const stableObject = value => JSON.stringify(Object.entries(value ?? {}).sort(([a],[b])=>a.localeCompare(b)));
const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);
export function statusKind(value) {
  const s=String(value??"UNKNOWN").toUpperCase();
  if (/PARTIAL|STALE|EXPIRED|NOT_MATURED|RUNNING/.test(s)) return "warn";
  if (/FAIL|ERROR|CONFLICT|INVALID/.test(s)) return "bad";
  if (/NOT_|UNKNOWN|MISSING|CANNOT|UNVERIFIED|PENDING/.test(s)) return "warn";
  return /READY|VERIFIED|COMPLETE|SUCCEEDED/.test(s) ? "good" : "warn";
}

export function mergePoolPages(pages) {
  if (!Array.isArray(pages) || pages.length === 0) throw new Error("没有可合并的候选页");
  const expectedDate = String(pages[0].trade_date ?? pages[0].date ?? pages[0].target_date ?? "");
  if (!expectedDate) throw new Error("候选响应缺少交易日期");
  const first = pages[0];
  const isolated = [];
  const byPool = new Map();
  for (const payload of pages) {
    const actualDate = String(payload.trade_date ?? payload.date ?? payload.target_date ?? "");
    if (actualDate !== expectedDate) throw new Error("候选日期不匹配：" + actualDate + " != " + expectedDate);
    if ((payload.input_fingerprint ?? null)!==(first.input_fingerprint ?? null)
        || stableObject(payload.source_digests)!==stableObject(first.source_digests)
        || stableObject(payload.market_totals)!==stableObject(first.market_totals)) throw new Error("候选分页版本身份冲突（fingerprint / source_digests / 分母）");
    if (!Array.isArray(payload.pools)) {
      isolated.push({poolId: null, reason: "MALFORMED_SOURCE_POOLS"});
      continue;
    }
    for (const pool of payload.pools) {
      if (!isRecord(pool) || typeof pool.pool_id !== "string" || !pool.pool_id) {
        isolated.push({poolId: null, reason: "MALFORMED_SOURCE_POOL"});
        continue;
      }
      if (!byPool.has(pool.pool_id)) byPool.set(pool.pool_id, []);
      byPool.get(pool.pool_id).push(pool);
    }
  }
  const candidates = new Map();
  const poolStates = new Map();
  let membershipCount = 0;
  for (const [poolId, poolPages] of byPool) {
    const firstPool = poolPages[0];
    const market = marketOf(firstPool.market);
    const sourceSha256 = firstPool.source_sha256 ?? firstPool.source_artifact_sha256 ?? null;
    const totalRows = countOrNull(firstPool.pool_size ?? firstPool.source_row_count);
    if (poolPages.some(pool => marketOf(pool.market) !== market
      || (pool.source_sha256 ?? pool.source_artifact_sha256 ?? null) !== sourceSha256
      || countOrNull(pool.pool_size ?? pool.source_row_count) !== totalRows)) {
      isolated.push({poolId, reason: "SOURCE_POOL_IDENTITY_CONFLICT"});
      poolStates.set(poolId, {
        poolId, market, label: firstPool.display_name ?? poolId, status: "CONFLICT",
        totalRows: null, readRows: 0, sourceDate: null, sourceDates: [], sourceSha256: null,
        cannotConfirm: ["SOURCE_POOL_IDENTITY_CONFLICT"], hasMore: false,
      });
      continue;
    }
    const members = new Set();
    const sourceDates = new Set();
    const lastPool = poolPages.at(-1);
    const state = {
      poolId, market, status: String(lastPool.status ?? "CANNOT_CONFIRM"),
      label: lastPool.display_name ?? poolId, totalRows, sourceDate: null, sourceDates: [], sourceSha256,
      cannotConfirm: Array.isArray(lastPool.cannot_confirm) ? lastPool.cannot_confirm : [],
      hasMore: Boolean(lastPool.has_more),
    };
    for (const pool of poolPages) {
      if(pool.signal_date) sourceDates.add(pool.signal_date);
      const sourceRows=pool.rows ?? [];
      if(!Array.isArray(sourceRows)) {
        isolated.push({poolId,reason:'MALFORMED_SOURCE_ROWS'});
        state.status='INVALID_SOURCE_SHAPE';
        if (!state.cannotConfirm.includes('SOURCE_ROWS_NOT_ARRAY')) {
          state.cannotConfirm=[...state.cannotConfirm,'SOURCE_ROWS_NOT_ARRAY'];
        }
        continue;
      }
      for (const row of sourceRows) {
        if(!isRecord(row)) {
          isolated.push({poolId,reason:'MALFORMED_SOURCE_ROW'});continue;
        }
        const market = marketOf(row.market ?? pool.market);
        const symbol = String(row.symbol ?? row.code ?? row.stock_code ?? "").trim();
        const identity = securityIdentity(market, symbol);
        if (!identity || market!==marketOf(pool.market)) { isolated.push({poolId,symbol,reason:"MARKET_OR_SECURITY_CONFLICT"}); continue; }
        if(members.has(identity)) { isolated.push({poolId,symbol,reason:"DUPLICATE_SOURCE_MEMBERSHIP"}); continue; }
        members.add(identity);membershipCount += 1;
        if (!candidates.has(identity)) candidates.set(identity, {
          identity, market, symbol: row.ts_code && securityIdentity(market,row.ts_code)===identity ? row.ts_code : symbol, displaySymbol: displaySymbol(market, symbol),
          name: row.stock_name ?? row.name ?? row.display_name ?? symbol,
          sources: [], sourceDates: new Set(),
        });
        const candidate = candidates.get(identity);
        const entry = sourceEntry(pool, row);
        if(entry.sourceDate) sourceDates.add(entry.sourceDate);
        if (!candidate.sources.some(x => x.poolId === entry.poolId && x.rank === entry.rank && x.sourceSha256 === entry.sourceSha256)) candidate.sources.push(entry);
        if (entry.sourceDate) candidate.sourceDates.add(entry.sourceDate);
        if (!candidate.name || candidate.name === candidate.symbol) candidate.name = row.stock_name ?? row.name ?? row.display_name ?? candidate.name;
      }
    }
    state.sourceDates=[...sourceDates].sort();
    state.sourceDate=state.sourceDates.length ? state.sourceDates.join(", ") : null;
    state.readRows=members.size;
    poolStates.set(poolId, state);
  }
  const last = pages[pages.length - 1];
  const totals = last.market_totals ?? pages[0].market_totals ?? {};
  const rows = [...candidates.values()].map(row => ({
    ...row,
    sources: row.sources.sort((a,b) => a.poolId.localeCompare(b.poolId)),
    sourceDates: [...row.sourceDates].sort(),
  })).sort((a,b) => a.market.localeCompare(b.market) || a.displaySymbol.localeCompare(b.displaySymbol));
  const counts = { A: rows.filter(x => x.market === "A").length, HK: rows.filter(x => x.market === "HK").length };
  const expected = {
    A: countOrNull(totals.A ?? last.a_all_pool_row_count),
    HK: countOrNull(totals.HK ?? poolStates.get("hkconnect_d1_top100")?.totalRows),
  };
  const lastPage = pages[pages.length - 1];
  const paginationChainValid = first.pagination?.offset===0 && lastPage.pagination?.has_more === false && pages.every((p, i) => {
    if (!p.pagination) return false;
    if (i === pages.length - 1) return true;
    return p.pagination.has_more === true && Number.isInteger(p.pagination.next_offset)
      && p.pagination.next_offset > p.pagination.offset
      && p.pagination.next_offset === pages[i + 1]?.pagination?.offset;
  });
  const allPagesComplete = paginationChainValid;
  const countsMatch = expected.A !== null && expected.HK !== null && counts.A === expected.A && counts.HK === expected.HK;
  const pools = [...poolStates.values()].sort((a,b) => a.poolId.localeCompare(b.poolId));
  const membershipComplete=pools.every(p=>p.totalRows!==null && p.readRows===p.totalRows);
  const complete=allPagesComplete && countsMatch && membershipComplete && !isolated.length;
  return {
    date: expectedDate, rows, pools, counts, expected, membershipCount,
    dataStatus: String(last.data_status ?? last.daily_readiness_status ?? "CANNOT_CONFIRM"),
    complete, isolated,
    completenessReason: complete ? null : !allPagesComplete ? "分页尚未完整读取" : !countsMatch ? "去重数量与API市场总数不一致或分母缺失" : !membershipComplete ? "来源关系数量与逐池分母不一致" : "证券或来源关系存在冲突",
    generation: last.generation ?? last.run_id ?? null,
    inputSha256: last.input_fingerprint ?? last.input_sha256 ?? null,
    sourceDigests: last.source_digests ?? {},
    marketTotals: totals,
  };
}

export async function fetchAllPreselection(dateValue, fetcher = fetch) {
  const date = normaliseDate(dateValue);
  const limit = 300, pages = [];
  let offset = 0;
  for (let page = 0; page < 20; page += 1) {
    const url = "/api/v4/preselection-pools?" + new URLSearchParams({ date, limit: String(limit), offset: String(offset) });
    let payload;
    try {
      payload = await readJson(url, fetcher);
      if (!isRecord(payload)) throw new Error("候选响应结构无效");
    } catch(error) {
      if(!pages.length) throw error;
      return {...mergePoolPages(pages),complete:false,completenessReason:"后续候选页读取失败："+(error instanceof Error ? error.message : "未知读取错误")};
    }
    const responseDate = String(payload.trade_date ?? payload.date ?? payload.target_date ?? "");
    if (responseDate !== date) throw new Error("候选池日期不匹配，已拒绝展示");
    if (!payload.pagination || !Number.isInteger(payload.pagination.offset) || payload.pagination.offset !== offset) throw new Error("候选分页身份不完整");
    pages.push(payload);
    if (payload.pagination.has_more === false) return mergePoolPages(pages);
    const next = payload.pagination.next_offset;
    if (!Number.isInteger(next) || next <= offset) throw new Error("候选分页游标无效");
    offset = next;
  }
  throw new Error("候选分页超过安全页数上限，未宣称完整");
}

export async function readJson(url, fetcher = fetch) {
  const response = await fetcher(url, { method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store" });
  if (!response.ok) throw new Error("读取失败 HTTP " + response.status);
  return response.json();
}

async function optionalJson(url, fetcher) {
  try { return await readJson(url,fetcher); }
  catch(error) { return {status:"FAILED",cannot_confirm:[error instanceof Error ? error.message : "读取失败"]}; }
}

function evidenceIdentity(item, symbol, date, product) {
  if(!isRecord(item) || typeof item.status!=='string') {
    return {status:'CANNOT_CONFIRM',cannot_confirm:['证据响应结构无效，已隔离该项']};
  }
  if(item.status==="FAILED")return item;
  const actualDate=item.data_date ?? item.dataDate;
  const actualSymbol=item.symbol ?? item.row?.symbol;
  const materialized=['READY','PARTIAL_RECEIVED'].includes(item.status);
  const manifests=[item.numeric_manifest,item.product_manifest,item.manifest].filter(ref=>ref!=null);
  const manifestShas=manifests.map(ref=>ref.sha256);
  let identityConflict=false;
  try {
    identityConflict=(actualDate && normaliseDate(actualDate)!==date)
      || (actualSymbol && apiSymbol("A",actualSymbol)!==symbol);
  } catch { identityConflict=true; }
  const conflict=identityConflict
    || (product?.source_generation && item.source_generation && product.source_generation!==item.source_generation)
    || (product?.source_identity?.input_sha256 && (item.input_sha256 || item.source_identity?.input_sha256)
      && product.source_identity.input_sha256!==(item.input_sha256 || item.source_identity?.input_sha256))
    || (product?.manifest?.sha256 && manifestShas.some(sha=>sha!==product.manifest.sha256));
  if(conflict)return {status:"CONFLICT",cannot_confirm:["证券、来源日或generation/input/manifest身份冲突，已隔离该项"]};
  const inputSha=item.input_sha256 || item.source_identity?.input_sha256;
  if(materialized && (!actualDate || !actualSymbol || !item.source_generation || !inputSha
    || !manifestShas.length || manifestShas.some(sha=>typeof sha!=="string" || !sha))) {
    return {status:'CANNOT_CONFIRM',original_status:item.status,cannot_confirm:['来源日期 / 证券 / generation / input SHA / numeric manifest 身份缺失，不能绑定本批证据']};
  }
  return item;
}

function companyEvidence(item, symbol, date, product) {
  const checked = evidenceIdentity(item, symbol, date, product);
  const {materials, items, summary, ...status} = checked;
  if (!["READY", "PARTIAL_RECEIVED"].includes(status.status)) return status;
  if (product.status !== "READY") {
    return {status: "CANNOT_CONFIRM", original_status: status.status,
      cannot_confirm: ["数值日包身份未核验，无法绑定公司材料"]};
  }
  return checked;
}

function hkEnvelope(payload) {
  if(payload.schema_version!=="v4.manager_workbench.v1")throw new Error("港股工作台合同不匹配");
  if(payload.production_allowed===true || payload.buy_gate_updated===true || payload.orders_sent===true)throw new Error("港股研究响应安全身份冲突");
  return payload;
}

export async function loadHkWorkbench({symbol,date,runId},fetcher=fetch) {
  const resolved=apiSymbol("HK",symbol),safeDate=normaliseDate(date);
  const qs=new URLSearchParams({q:resolved,limit:"200",offset:"0"});
  if(runId)qs.set("run_id",runId);
  const day=hkEnvelope(await readJson(`/api/v4/manager-workbench/days/${safeDate}?${qs}`,fetcher));
  const snapshot=day.data?.snapshot;
  if(!snapshot)return {status:day.state ?? "CANNOT_CONFIRM",day,stock:null};
  if(snapshot.context?.market!=="HK_CONNECT" || snapshot.context?.target_date!==safeDate || !snapshot.run_id
      || (runId && runId!==snapshot.run_id))throw new Error("港股日期、市场或run_id冲突");
  const detail=hkEnvelope(await readJson(`/api/v4/manager-workbench/stocks/${encodeURIComponent(resolved)}?`+new URLSearchParams({date:safeDate,run_id:snapshot.run_id}),fetcher));
  if(detail.data && (detail.data.plan_run_id!==snapshot.run_id
    || (detail.data.stock && (detail.data.stock.market!=="HK_CONNECT" || apiSymbol("HK",detail.data.stock.symbol)!==resolved))))throw new Error("港股个股与批次身份冲突");
  return {status:detail.state ?? day.state ?? "CANNOT_CONFIRM",day,detail,stock:detail.data?.stock ?? null,snapshot};
}

export async function loadHkReview({date,planRunId},fetcher=fetch) {
  const safeDate=normaliseDate(date);
  if(!planRunId)throw new Error("港股复盘缺少所选计划批次");
  const result=hkEnvelope(await readJson(`/api/v4/manager-workbench/reviews/${safeDate}?`+new URLSearchParams({plan_run_id:planRunId}),fetcher));
  if(result.data && (result.data.target_date!==safeDate || result.data.plan_run_id!==planRunId))throw new Error("港股复盘日期或计划批次冲突");
  if(result.data?.ranking_date && result.data.ranking_date!==safeDate)throw new Error("港股收盘榜日期冲突");
  if(result.state==='READY' && !result.data)throw new Error("港股复盘 READY 缺少同批结果");
  return result;
}

export function maturityGroups(product) {
  return (product?.row?.statistics?.groups ?? []).map(group=>{
    const horizon=name=>{
      const value=group.horizons?.[name];
      if(!value)return null;
      const cases=[...(value.cases??[])].sort((a,b)=>String(b.event_date??"").localeCompare(String(a.event_date??"")));
      return {...value,cases,latest:cases[0]??null};
    };
    return {groupId:group.group_id,status:group.status,identityStatus:group.identity_status,sourceIdentity:group.source_identity,d2:horizon("d2"),d5:horizon("d5")};
  });
}

export async function loadEventCases({symbol,date,group,horizon,product},fetcher=fetch) {
  const resolved=apiSymbol("A",symbol),safeDate=normaliseDate(date);
  if(!["original","nav_smallk","nav_pullback","nav_breakout"].includes(group) || !["d2","d5"].includes(horizon))throw new Error("事件分组或周期无效");
  const value=await optionalJson("/api/v4/research/a-share/event-cases?"+new URLSearchParams({date:safeDate,symbol:resolved,group,horizon}),fetcher);
  const checked=evidenceIdentity(value,resolved,safeDate,product);
  if(checked.status==="READY" && (checked.group!==group || checked.horizon!==horizon))return {status:"CONFLICT",cannot_confirm:["事件分组或周期身份冲突"]};
  return checked;
}

export async function loadDailyProduct({symbol,date},fetcher=fetch) {
  const resolved=apiSymbol("A",symbol),safeDate=normaliseDate(date);
  return evidenceIdentity(await optionalJson("/api/v4/research/a-share/daily-product?"+new URLSearchParams({date:safeDate,symbol:resolved}),fetcher),resolved,safeDate);
}

export async function loadResearchBundle({ market: marketValue, symbol, date, observationDate, runId }, fetcher = fetch) {
  const market = marketOf(marketValue);
  const safeDate = normaliseDate(date);
  if (!symbol) throw new Error("请提供证券代码");
  if (market === "HK") {
    const targetDate=normaliseDate(observationDate ?? date);
    const [workbenchResult,poolResult]=await Promise.allSettled([
      loadHkWorkbench({symbol,date:targetDate,runId},fetcher),fetchAllPreselection(targetDate,fetcher)
    ]);
    const workbench=workbenchResult.status==="fulfilled" ? workbenchResult.value : {status:"FAILED",cannot_confirm:[String(workbenchResult.reason.message ?? workbenchResult.reason)]};
    const pools=poolResult.status==="fulfilled" ? poolResult.value : null;
    const candidate=pools?.rows.find(x=>x.identity===securityIdentity("HK",symbol)) ?? null;
    return {market,symbol:apiSymbol("HK",symbol),date:safeDate,observationDate:targetDate,workbench,candidate,pools,
      status:workbench.status,source:"V4_MANAGER_WORKBENCH_AND_HK_0_2_POOL",poolError:poolResult.status==="rejected" ? String(poolResult.reason.message ?? poolResult.reason) : null};
  }
  if (market !== "A") throw new Error("不支持的市场身份：" + market);
  const resolvedSymbol = apiSymbol(market, symbol);
  const qs = new URLSearchParams({ date: safeDate, symbol: resolvedSymbol });
  const product=await loadDailyProduct({symbol:resolvedSymbol,date:safeDate},fetcher);
  if(product.source_generation)qs.set("generation",product.source_generation);
  if(product.source_identity?.input_sha256)qs.set("input_sha256",product.source_identity.input_sha256);
  const [chartRaw,companyRaw] = await Promise.all([
    optionalJson("/api/v4/research/a-share/original-chart?" + qs, fetcher),
    optionalJson("/api/v4/research/a-share/company-materials?" + qs, fetcher),
  ]);
  const chart=evidenceIdentity(chartRaw,resolvedSymbol,safeDate,product), company=companyEvidence(companyRaw,resolvedSymbol,safeDate,product);
  return { market, symbol: resolvedSymbol, date: safeDate, product, chart, company,
    maturity:maturityGroups(product),status: [product,chart,company].every(x=>x.status==="READY") ? "READY" : "PARTIAL", source: "V4_A_SHARE_DAILY_PRODUCT" };
}

export async function loadReview(dateValue, fetcher = fetch) {
  const date = normaliseDate(dateValue);
  const payload = await readJson("/api/v3/review?" + new URLSearchParams({ date }), fetcher);
  if (payload.trade_date !== date) throw new Error("复盘日期不匹配，已拒绝展示");
  return payload;
}

export function formulaComparisonFor(dateValue) {
  const date = normaliseDate(dateValue);
  return FORMULA_COMPARISONS.find(x => x.observationDate === date) ?? null;
}

export async function fetchFormulaComparisonRows(dateValue, fetcher = fetch) {
  const date = normaliseDate(dateValue);
  const response = await fetcher("/v45/shared/formula-comparison.v1.bin", {
    method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store",
  });
  if (!response.ok) throw new Error("冻结公式差异文件读取失败 HTTP " + response.status);
  if (typeof DecompressionStream === "undefined") throw new Error("浏览器不支持gzip解压，逐股对照不可读取");
  const compressed = await response.arrayBuffer();
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("gzip"));
  const parsed = JSON.parse(await new Response(stream).text());
  if (parsed.schema_version !== "v45.frozen_formula_comparison.v1"
      || parsed.status !== "FROZEN_SOURCE_DATA_NOT_RECALCULATED"
      || !Array.isArray(parsed.records)) throw new Error("冻结公式对照合同不匹配");
  const rows = parsed.records.filter(row => row.observation_date === date);
  const summary = formulaComparisonFor(date);
  if (!summary) return [];
  const categoryCounts = rows.reduce((acc, row) => {
    acc[row.category] = (acc[row.category] ?? 0) + 1;
    return acc;
  }, {});
  const valid = rows.length === summary.originalOnly + summary.v192Only + summary.common
    && (categoryCounts["仅原公式"] ?? 0) === summary.originalOnly
    && (categoryCounts["仅v1.9.2"] ?? 0) === summary.v192Only
    && (categoryCounts["共同入选"] ?? 0) === summary.common
    && rows.every(row => row.source_date === summary.sourceDate
      && /^[0-9a-f]{64}$/.test(row.source_checkpoint_sha256 ?? ""));
  if (!valid) throw new Error("逐股公式差异与冻结汇总/来源SHA不一致");
  return rows;
}
