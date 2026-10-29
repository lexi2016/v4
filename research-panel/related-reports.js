'use strict';

// Fixed 2026-10-27 identity date is supplied by this archived page, not the browser clock.
(() => {
  const section = document.getElementById('relatedReports');
  const state = document.getElementById('relatedReportsState');
  const output = document.getElementById('relatedReportsOutput');
  const PAGE_SIZE = 5, MAX_PAGES = 20, MAX_RESTARTS = 1;
  class HttpError extends Error {
    constructor(status) { super(`HTTP ${status}${status === 401 || status === 403 ? '（访问未获授权）' : ''}`); this.status = status; }
  }
  class SnapshotChanged extends Error {}
  let current = null, requestController = null, detailController = null, detailTarget = null, detailPending = false, sequence = 0;
  // A client observation is not an index-update receipt. Keep it only in the
  // current page, by exact stock/date/name, and never treat it as fresh data.
  const successfulQueries = new Map();
  const queryKey = item => JSON.stringify([item.day, item.symbol, item.name, item.generation]);
  function showState(message) {
    const prior = current ? successfulQueries.get(queryKey(current)) : null;
    state.textContent = `${message} 本页本股上次成功读取：${prior?.observedAt || '未知'}（本机观察时间，不等于索引更新或完整覆盖）；` +
      `上次响应所报索引最近成功：${prior?.indexAt || '未知'}（不是当前更新状态）。`;
  }
  function latestIndexSuccess(coverage) {
    const updates = coverage?.index_updates;
    if (!updates || typeof updates !== 'object' || Array.isArray(updates)) return null;
    let found = null, latest = -Infinity;
    for (const value of Object.values(updates)) {
      const stamp = value?.last_success_at;
      if (typeof stamp !== 'string' || stamp.length > 64) continue;
      const millis = Date.parse(stamp);
      if (Number.isFinite(millis) && millis > latest) { latest = millis; found = stamp; }
    }
    return found;
  }

  function node(tag, value, className) {
    const item = document.createElement(tag);
    if (value !== undefined) item.textContent = String(value);
    if (className) item.className = className;
    return item;
  }
  function append(parent, tag, value, className) { const item = node(tag, value, className); parent.append(item); return item; }
  function printable(value) { return value === null || value === undefined || value === '' ? '未知' : String(value); }
  function validDay(value) {
    const day = String(value ?? '');
    if (!/^\d{8}$/.test(day)) return false;
    const y = Number(day.slice(0, 4)), m = Number(day.slice(4, 6)), d = Number(day.slice(6, 8));
    const date = new Date(Date.UTC(y, m - 1, d));
    return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
  }
  function abortAll() {
    if (requestController) requestController.abort();
    if (detailController) detailController.abort();
    requestController = null; detailController = null; detailTarget = null; detailPending = false;
  }
  function clear() {
    sequence++;
    abortAll(); current = null;
    state.textContent = '等待选择股票。';
    output.replaceChildren();
  }
  function safety(data) {
    return data?.research_only === true && data.production_allowed === false && data.buy_gate_updated === false && data.orders_sent === false;
  }
  async function jsonFrom(url, controller) {
    let expired = false;
    const timer = setTimeout(() => { expired = true; controller.abort(); }, 60000);
    try {
      const response = await fetch(url, { cache: 'no-store', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', signal: controller.signal });
      if (!response.ok) throw new HttpError(response.status);
      try { return await response.json(); } catch (_) { throw new Error('响应不是有效 JSON'); }
    } catch (error) {
      if (expired) throw new Error('请求超时（60 秒）');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function role(value) {
    return ({ TITLE_SUBJECT_TEXT_CANDIDATE: '标题主体候选，待核', REPORT_PUBLISHER_TEXT_CANDIDATE: '发布方候选，待核',
      TITLE_OR_FILENAME_MENTION_CANDIDATE: '标题或文件名提及', BODY_MENTION_CANDIDATE: '正文提及' })[value] || printable(value);
  }
  async function openDocument(source, report, target, button, token) {
    if (target.childNodes.length) {
      if (detailTarget === target && detailController) { detailController.abort(); detailController = null; detailTarget = null; detailPending = false; }
      target.replaceChildren(); button.textContent = '查看已校验 OCR 正文'; return;
    }
    if (!/^[0-9a-f]{64}$/.test(String(source.document_id ?? '')) || !validDay(source.research_date)) {
      target.textContent = '正文身份不完整，无法打开。'; return;
    }
    if (detailController) {
      detailController.abort();
      if (detailPending && detailTarget) detailTarget.textContent = '已切换至另一篇，正文请求已取消。';
    }
    const controller = new AbortController();
    detailController = controller; detailTarget = target; detailPending = true;
    target.textContent = '正在读取已校验 OCR 正文…';
    try {
      const query = new URLSearchParams({ research_date: source.research_date });
      const detail = await jsonFrom('/api/v4/research/pdf-documents/' + encodeURIComponent(source.document_id) + '?' + query, controller);
      if (token !== sequence || detailController !== controller) return;
      if (detail.schema_version !== 'v4.zsxq_pdf_document_detail.v1' || !safety(detail) || detail.status !== 'READY' ||
          detail.document_id !== source.document_id || detail.research_date !== source.research_date ||
          detail.receipt?.integrity !== 'SOURCE_PDF_AND_PAGE_HASHES_VERIFIED' || !Array.isArray(detail.pages) ||
          !detail.pages.every(page => page && Number.isInteger(page.page_number) && typeof page.text === 'string')) {
        throw new Error('正文身份或校验状态不匹配');
      }
      const isSha256 = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
      const expectedReceipt = source.receipt_sha256, actualReceipt = detail.receipt?.sha256;
      const expectedPdf = report.verified_pdf_sha256, actualPdf = detail.receipt?.verified_pdf_sha256;
      const hasExpectedPdf = expectedPdf !== null && expectedPdf !== undefined;
      if (!isSha256(expectedReceipt) || !isSha256(actualReceipt) || expectedReceipt !== actualReceipt ||
          (hasExpectedPdf && (!isSha256(expectedPdf) || !isSha256(actualPdf) || expectedPdf !== actualPdf))) {
        throw new Error('正文版本已变化或摘要缺失，请重新查询研报关联后再查看正文');
      }
      target.replaceChildren();
      if (!detail.pages.length) append(target, 'p', '正文页未返回。');
      for (const page of detail.pages) {
        const part = append(target, 'section');
        append(part, 'h4', `第 ${page.page_number} 页`);
        const pre = append(part, 'pre', page.text);
        pre.style.whiteSpace = 'pre-wrap';
      }
      button.textContent = '收起正文';
      detailPending = false;
    } catch (error) {
      if (token !== sequence || detailController !== controller) return;
      target.textContent = `正文待核：${error?.message || '网络不可达'}。`;
      detailPending = false;
    }
  }
  function canonical(value) {
    function ordered(item) {
      if (Array.isArray(item)) return item.map(ordered);
      if (item && typeof item === 'object') return Object.fromEntries(Object.keys(item).sort().map(key => [key, ordered(item[key])]));
      return item;
    }
    return JSON.stringify(ordered(value));
  }
  function sourceKey(source) {
    return validDay(source.research_date) && /^[0-9a-f]{64}$/.test(String(source.document_id ?? ''))
      ? `${source.research_date}:${source.document_id}` : null;
  }
  function sourceMetadata(source) {
    const copy = { ...source }; delete copy.evidence; delete copy.text_match_in_source;
    return canonical(copy);
  }
  function reportMetadata(report) { const copy = { ...report }; delete copy.sources; return canonical(copy); }
  function verifiedReportSha(report) {
    return typeof report.verified_pdf_sha256 === 'string' && /^[0-9a-f]{64}$/.test(report.verified_pdf_sha256) &&
      report.dedup_status === 'VERIFIED_PDF_BYTES' ? report.verified_pdf_sha256 : null;
  }
  function appendReports(acc, stock) {
    for (const report of stock.reports) {
      const sha = verifiedReportSha(report);
      let existing = sha ? acc.bySha.get(sha) : null;
      if (!existing) {
        existing = { ...report, sources: [] };
        acc.reports.push(existing);
        if (sha) acc.bySha.set(sha, existing);
      } else if (reportMetadata(existing) !== reportMetadata(report)) throw new SnapshotChanged('同一 PDF 的关联元数据发生变化');
      for (const source of report.sources) {
        const key = sourceKey(source);
        const prior = key ? acc.sourcesByKey.get(key) : null;
        if (prior && ((prior.sha && sha && prior.sha !== sha) || sourceMetadata(prior.source) !== sourceMetadata(source))) {
          throw new SnapshotChanged('同一来源版本或 PDF 摘要发生变化');
        }
        if (key && prior && !prior.sha && sha) acc.sourcesByKey.set(key, { sha, source: prior.source });
        // Unverified hashes remain separate reports, even if a source identifier repeats.
        const same = sha && key ? existing.sources.find(item => sourceKey(item) === key) : null;
        if (same) {
          const seen = new Set(same.evidence.map(canonical));
          for (const evidence of source.evidence) if (!seen.has(canonical(evidence))) { same.evidence.push(evidence); seen.add(canonical(evidence)); }
          const matches = [same.text_match_in_source, source.text_match_in_source];
          same.text_match_in_source = matches.includes(true) ? true : matches.includes(false) ? false : null;
        } else {
          const copy = { ...source, evidence: [...source.evidence] };
          existing.sources.push(copy);
          if (key && !prior) acc.sourcesByKey.set(key, { sha, source: copy });
        }
      }
    }
  }
  function largeCounts(coverage, mode) {
    const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
    const matches = coverage.gaps.filter(gap => gap && gap.reason === 'SEARCH_INDEX_LARGE_PENDING');
    if (matches.length > 1) throw new SnapshotChanged('大文件索引缺口重复，覆盖状态待核');
    const gap = matches[0];
    const topPending = count(coverage.large_ready_pending), topErrors = count(coverage.large_verification_error);
    const gapPending = count(gap?.count), gapErrors = count(gap?.verification_errors);
    if (gap && ((topPending !== null && gapPending !== null && topPending !== gapPending) ||
        (topErrors !== null && gapErrors !== null && topErrors !== gapErrors))) {
      throw new SnapshotChanged('大文件索引覆盖计数冲突');
    }
    const pending = mode === 'FULLTEXT_INDEX' ? (gap && gapPending === null ? null : topPending)
      : Object.hasOwn(coverage, 'large_ready_pending') && topPending === null ? null : gapPending;
    const errors = mode === 'FULLTEXT_INDEX' ? (gap && gapErrors === null ? null : topErrors)
      : Object.hasOwn(coverage, 'large_verification_error') && topErrors === null ? null : gapErrors;
    if (pending !== null && errors !== null && errors > pending) throw new SnapshotChanged('大文件校验失败数超过待索引数');
    return { pending, errors };
  }
  function snapshotSignature(data) {
    const coverage = data.coverage;
    const keys = ['scope', 'indexed_dates_seen', 'cache_dates_seen', 'dates_considered', 'dates_scanned', 'owner_documents',
      'indexed_documents', 'unindexed_ready', 'stale_documents', 'unavailable_documents', 'removed_documents',
      'malformed_documents', 'index_updates', 'search_method', 'historical_sources_complete', 'candidate_documents',
      'indexed_content_time', 'legacy_max_dates_ignored', 'large_ready_pending', 'large_verification_error'];
    const fixedCoverage = Object.fromEntries(keys.map(key => [key, coverage[key] ?? null]));
    const sourceGaps = coverage.gaps.filter(gap => gap && typeof gap === 'object' && gap.source_run_id && !gap.document_id)
      .map(canonical).sort();
    const largeGaps = coverage.gaps.filter(gap => gap && gap.reason === 'SEARCH_INDEX_LARGE_PENDING').map(canonical).sort();
    return canonical({ identity: data.stocks[0].identity, search_hint: data.stocks[0].search_hint ?? null, fixedCoverage, sourceGaps, largeGaps });
  }
  function validatePage(data, day, expected, cursor, expectedOffset) {
    if (!data || data.schema_version !== 'v4.related_pdf_reports.candidate.v1' || data.identity_date !== day ||
        data.time_semantics !== 'CURRENT_KNOWLEDGE_NON_PIT' || !safety(data) ||
        !Array.isArray(data.stocks) || data.stocks.length !== 1 || data.stocks[0]?.symbol !== expected ||
        !data.stocks[0].identity || !Array.isArray(data.stocks[0].reports) || !data.coverage ||
        !Array.isArray(data.coverage.gaps) || !data.stocks[0].reports.every(report => report && Array.isArray(report.sources) &&
          report.sources.every(source => source && Array.isArray(source.evidence)))) {
      throw new Error('研报接口身份、覆盖或研究安全合同不匹配');
    }
    if (data.status === 'NOT_MATERIALIZED' && data.search_mode === 'NOT_MATERIALIZED') {
      if (cursor || data.next_cursor !== null || data.stocks[0].reports.length) throw new SnapshotChanged('未物化索引响应范围冲突');
      return { mode: 'NOT_MATERIALIZED', next: null, notMaterialized: true };
    }
    if (data.status !== 'PARTIAL') throw new Error('研报接口状态未知');
    if (data.coverage.gaps.some(gap => gap && ['SEARCH_CHECKPOINT_CHANGED_DURING_READ', 'SEARCH_CHECKPOINT_RECHECK_FAILED'].includes(gap.reason))) {
      throw new SnapshotChanged('索引或来源 checkpoint 已变化或复核失败');
    }
    const mode = data.search_mode ?? 'EXCERPT_CANARY';
    if (mode !== 'FULLTEXT_INDEX' && mode !== 'EXCERPT_CANARY') throw new Error('研报检索模式未知');
    largeCounts(data.coverage, mode);
    const next = data.next_cursor ?? null;
    if (next !== null && (typeof next !== 'string' || !/^[A-Za-z0-9_-]{1,1024}$/.test(next))) throw new Error('续页游标格式无效');
    if (mode === 'EXCERPT_CANARY') {
      if (next !== null || cursor) throw new SnapshotChanged('索引模式在续页期间变化');
      return { mode, next: null };
    }
    const coverage = data.coverage, attempts = coverage.detail_attempts, verified = coverage.verified_documents;
    const limitGap = coverage.gaps.some(gap => gap && gap.reason === 'SEARCH_PAGINATION_VALIDATION_LIMIT');
    const backendIncomplete = coverage.pagination_incomplete === true || limitGap;
    if (!Object.hasOwn(data, 'next_cursor') || !Number.isInteger(coverage.page_offset) || coverage.page_offset !== expectedOffset ||
        !Number.isInteger(attempts) || attempts < 0 || attempts > PAGE_SIZE || !Number.isInteger(verified) || verified < 0 || verified > attempts ||
        !Number.isInteger(coverage.candidate_documents) || coverage.candidate_documents < expectedOffset + attempts ||
        coverage.limits?.documents !== PAGE_SIZE || coverage.pagination_required !== (next !== null) ||
        (coverage.pagination_incomplete !== undefined && typeof coverage.pagination_incomplete !== 'boolean') ||
        (next !== null && (attempts === 0 || backendIncomplete)) ||
        (next === null && !backendIncomplete && coverage.candidate_documents !== expectedOffset + attempts)) {
      throw new SnapshotChanged('续页范围、候选数量或页大小不一致');
    }
    return { mode, next, backendIncomplete };
  }
  async function readPages(symbol, day, query, controller, token) {
    const expected = 'A.' + symbol.slice(0, 6);
    const acc = { reports: [], bySha: new Map(), sourcesByKey: new Map(), gaps: [], verified: 0, attempts: 0 };
    const seen = new Set();
    let cursor = null, signature = null, base = null, mode = null, offset = 0, pages = 0;
    for (;;) {
      if (cursor) query.set('cursor', cursor); else query.delete('cursor');
      let data;
      try { data = await jsonFrom('/api/v4/research/pdf-relations?' + query, controller); }
      catch (error) {
        if (error instanceof HttpError && (error.status === 409 || (cursor && error.status === 422))) {
          throw new SnapshotChanged(`HTTP ${error.status}：续页索引或身份可能已变化`);
        }
        throw error;
      }
      if (token !== sequence) return null;
      const info = validatePage(data, day, expected, cursor, offset);
      if (mode && info.mode !== mode) throw new SnapshotChanged('检索模式在分页期间变化');
      mode = info.mode;
      if (info.notMaterialized) {
        return { data, stock: data.stocks[0], mode, pages: 0, gaps: data.coverage.gaps,
          verified: 0, attempts: 0, incomplete: true, incompleteReason: 'index_not_materialized' };
      }
      if (info.mode === 'FULLTEXT_INDEX') {
        const currentSignature = snapshotSignature(data);
        if (signature !== null && signature !== currentSignature) throw new SnapshotChanged('索引、来源状态或证券身份在分页期间变化');
        signature = currentSignature;
        if (info.next !== null && seen.has(info.next)) throw new SnapshotChanged('续页游标重复');
        if (info.next !== null) seen.add(info.next);
        offset += data.coverage.detail_attempts;
        acc.attempts += data.coverage.detail_attempts;
        acc.verified += data.coverage.verified_documents;
      }
      pages++;
      if (!base) base = data;
      appendReports(acc, data.stocks[0]);
      for (const gap of data.coverage.gaps) acc.gaps.push({ page: pages, detail: gap });
      if (info.next === null || pages >= MAX_PAGES) {
        const stock = { ...base.stocks[0], reports: acc.reports };
        const incompleteReason = info.backendIncomplete ? 'backend_limit' : info.next !== null ? 'page_limit' : null;
        return { data: base, stock, mode, pages, gaps: acc.gaps, verified: acc.verified, attempts: acc.attempts, incomplete: !!incompleteReason, incompleteReason };
      }
      cursor = info.next;
      showState(`${symbol}：正在读取全文索引候选，已读取 ${pages} 页（PARTIAL）；请等待续页。`);
    }
  }
  function render(result, token) {
    const { data, stock, mode, pages, gaps, verified, attempts, incomplete, incompleteReason } = result;
    const coverage = data.coverage;
    output.replaceChildren();
    append(output, 'p', `接口状态 ${data.status}；身份日期 ${data.identity_date}。资料为当前知识补充，非历史 PIT，不能认为在研究日盘中已可用。`);
    if (mode === 'NOT_MATERIALIZED') {
      append(output, 'p', '预建研报关系索引未就绪。本次只返回索引状态；未启动全量索引、历史来源扫描、OCR 或公式计算。');
    } else if (mode === 'FULLTEXT_INDEX') {
      const ending = incompleteReason === 'backend_limit' ? '；达到后端复验资源上限，续页未完成'
        : incomplete ? '；达到页数上限，续页未完成' : '；本次查询的游标已结束';
      append(output, 'p', `全文索引已读取 ${pages} 页${ending}。仍为 PARTIAL，未覆盖全部历史资料。`);
      append(output, 'p', `已索引日期 ${printable(coverage.indexed_dates_seen)}；本次扫描 ${Array.isArray(coverage.dates_scanned) ? (coverage.dates_scanned.join('、') || '无') : '未提供'}；索引文档 ${printable(coverage.indexed_documents)}；候选文档 ${printable(coverage.candidate_documents)}；本次尝试 ${attempts} / 已校验 ${verified}；每页最多 ${PAGE_SIZE} 篇。`);
      append(output, 'p', `未入索引 ${printable(coverage.unindexed_ready)}；索引过期 ${printable(coverage.stale_documents)}；不可用 ${printable(coverage.unavailable_documents)}；已移除 ${printable(coverage.removed_documents)}。返回候选在各自分页时重新核验，未返回原件以最近索引时的校验为准；文字提及不是已认证主体。`);
      if (coverage.index_updates && typeof coverage.index_updates === 'object' && !Array.isArray(coverage.index_updates)) {
        const updates = append(output, 'details'); append(updates, 'summary', '各日期索引更新状态');
        for (const day of Object.keys(coverage.index_updates).sort()) {
          const value = coverage.index_updates[day] || {};
          append(updates, 'p', `${day} · 最近成功 ${printable(value.last_success_at)} · 最近尝试 ${printable(value.last_attempt_at)} · 状态 ${printable(value.last_update_status)}`);
        }
      }
    } else {
      append(output, 'p', `首尾片段有限检索：已索引日期 ${printable(coverage.indexed_dates_seen)}；本次扫描 ${Array.isArray(coverage.dates_scanned) ? (coverage.dates_scanned.join('、') || '无') : '未提供'}；已校验文档 ${printable(coverage.verified_documents)}；上限 ${printable(coverage.limits?.dates)} 日 / ${printable(coverage.limits?.documents)} 篇。`);
      append(output, 'p', '仅筛标题、文件名及首尾片段，可能漏掉中间页和历史文档；该结果不是全文检索，文本提及不等于确认研报主体。');
    }
    if (mode !== 'NOT_MATERIALIZED') {
      const large = largeCounts(coverage, mode);
      append(output, 'p', `大小已知且大于 4 MiB、至多 64 MiB 的 READY 资料待索引：${printable(large.pending)} 篇；其中校验失败：${printable(large.errors)} 篇。统计依据来源元数据与派生索引，非当前股票匹配数量。`);
    }
    append(output, 'p', `证券身份：${printable(stock.identity?.status)}；名称：${printable(stock.identity?.name)}；原因：${printable(stock.identity?.reason)}。`);
    if (stock.search_hint?.status === 'CALLER_PROVIDED_UNVERIFIED') {
      append(output, 'p', `名单名称“${printable(stock.search_hint.name)}”仅作为未认证的文字搜索提示，不构成身份确认。`);
    } else {
      append(output, 'p', `名称提示状态：${printable(stock.search_hint?.status)}。`);
    }
    if (!stock.reports.length) append(output, 'p', '已读取范围未返回匹配；覆盖不完整或续页未完成，不能据此判断没有研报。');
    stock.reports.forEach((report, index) => {
      const article = append(output, 'article');
      append(article, 'h4', `相关候选 ${index + 1}`);
      append(article, 'p', `关联状态：${printable(report.relation_status)}；来源去重状态：${printable(report.dedup_status)}；原件 SHA256：${printable(report.verified_pdf_sha256)}。${verifiedReportSha(report) ? '本页按已核摘要合并。' : '摘要未认证，本页不跨记录合并。'}`);
      if (!report.sources.length) append(article, 'p', '来源未返回，候选待核。');
      report.sources.forEach(source => {
        const box = append(article, 'div');
        append(box, 'p', `${printable(source.original_filename || source.topic_title)}；来源日期 ${printable(source.research_date)}；文档 ID ${printable(source.document_id)}。`);
        append(box, 'p', `主题发布时间：${printable(source.source_topic_published_at)}；PDF 发布时间：${printable(source.pdf_published_at)}；来源获取：${printable(source.source_fetched_at)}；OCR 可得：${printable(source.available_at)}；PIT 状态：${printable(source.pit_status)}。`);
        append(box, 'p', `本来源文字命中：${source.text_match_in_source === true ? '是' : source.text_match_in_source === false ? '否' : '未提供'}。`);
        if (!source.evidence.length) append(box, 'p', '该来源未返回文字命中证据。');
        source.evidence.forEach(item => {
          const where = item.location === 'page' ? `第 ${printable(item.page_number)} 页` : printable(item.location);
          append(box, 'p', `${role(item.role)}；${printable(item.kind)}；${where}：${printable(item.text)}`);
        });
        const button = append(box, 'button', '查看已校验 OCR 正文'); button.type = 'button';
        const detail = append(box, 'div'); button.onclick = () => openDocument(source, report, detail, button, token);
      });
    });
    const details = append(output, 'details');
    append(details, 'summary', `查看逐页覆盖缺口（${gaps.length} 条）`);
    const pre = append(details, 'pre', JSON.stringify(gaps, null, 2)); pre.style.whiteSpace = 'pre-wrap';
  }
  async function select(symbol, name, force = false) {
    const day = String(section.dataset.identityDate || '');
    const generation = String(section.dataset.generation || '');
    if (!force && current?.symbol === symbol && current?.name === name && current?.day === day && current?.generation === generation) return;
    const token = ++sequence;
    abortAll(); current = { symbol, name, day, generation }; output.replaceChildren();
    if (!validDay(day)) { showState('名单身份日期缺失或无效；未请求相关研报。'); return; }
    if (!/^\d{6}\.(SH|SZ|BJ)$/.test(String(symbol))) { showState('股票代码无效；未请求相关研报。'); return; }
    const query = new URLSearchParams({ identity_date: day });
    query.append('symbols', symbol);
    const hint = String(name || '').trim();
    const hintAccepted = /^[\u3400-\u9fffA-Za-z0-9·* .&-]{2,32}$/.test(hint) && /[\u3400-\u9fffA-Za-z]/.test(hint);
    if (hintAccepted) query.append('hints', `${symbol}:${hint}`);
    query.set('max_documents', String(PAGE_SIZE));
    const controller = new AbortController(); requestController = controller;
    showState(`${symbol}：正在查询研报候选${hintAccepted ? '（名单名称为未认证搜索提示）' : '（名单名称不可用，仅查代码）'}。`);
    try {
      let result;
      for (let restart = 0; restart <= MAX_RESTARTS; restart++) {
        try { result = await readPages(symbol, day, query, controller, token); break; }
        catch (error) {
          if (token !== sequence) return;
          if (!(error instanceof SnapshotChanged) || restart === MAX_RESTARTS) throw error;
          output.replaceChildren();
          showState(`${symbol}：${error.message}；已丢弃旧页，正在从第一页重读（最多一次）。`);
        }
      }
      if (token !== sequence || !result) return;
      if (!result.incomplete) {
        successfulQueries.set(queryKey(current), { observedAt: new Date().toISOString(), indexAt: latestIndexSuccess(result.data.coverage) });
        if (successfulQueries.size > 512) successfulQueries.delete(successfulQueries.keys().next().value);
      }
      showState(result.incomplete
        ? result.incompleteReason === 'index_not_materialized' ? `${symbol}：预建研报关系索引未就绪，未运行全量扫描或索引构建。`
          : result.incompleteReason === 'backend_limit' ? `${symbol}：PARTIAL，已达后端复验资源上限，续页未完成。`
          : `${symbol}：PARTIAL，已达 ${MAX_PAGES} 页上限，续页未完成。`
        : `${symbol}：候选已读取 ${result.pages} 页（PARTIAL，覆盖仍有边界）。`);
      render(result, token);
    } catch (error) {
      if (token !== sequence) return;
      showState(`${symbol}：相关研报未完整或读取失败：${error?.message || '网络不可达'}；已丢弃本次页面，不能据此判断没有研报。`);
      output.replaceChildren();
    }
  }
  document.getElementById('relatedReportsRefresh').onclick = () => { if (current) select(current.symbol, current.name, true); };
  window.RelatedReports = { select, clear };
})();
