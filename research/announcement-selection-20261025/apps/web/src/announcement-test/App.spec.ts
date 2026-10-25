import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import App from './App.vue';
import { createTestApi } from './api';
import { SCHEMA_VERSION } from '../manager-workbench/types';
const safety = { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
const context = { test_run_id: 'fixture-task7', target_date: '20261021', mode: 'fixture', source_manifest_sha256: 'a'.repeat(64),
  read_only_material_roots: { fixture: '/isolated/materials' }, independent_state_root: '/isolated/state',
  code_identity: { component: 'b'.repeat(64) }, config_identity: 'c'.repeat(64), model_identity: { model_id: 'FIXTURE_NO_MODEL', configuration_sha256: 'd'.repeat(64) },
  canary_allowed: false, evidence_kind: 'FIXTURE_NOT_PRODUCTION_EVIDENCE' };
const wrap = (data: unknown) => ({ schema_version: SCHEMA_VERSION, state: 'PARTIAL', data, gaps: [], ...safety });
function data() {
  const old = 'a'.repeat(32), current = 'b'.repeat(32);
  return { state:'PARTIAL', source_date:'20261021', target_trade_date:'20261021', counts:{model_succeeded:14,pending:201,displayed_stocks:0},
    test_context_binding:{test_run_id:context.test_run_id,target_date:context.target_date,source_manifest_sha256:context.source_manifest_sha256},
    stocks:[],failures:[],pending:[{article_id:'pending',queue_reason:'DEFERRED'}],gaps:[{code:'SOURCE_MISSING',detail:'来源尚未补齐'}],
    test_evidence_kind:'FIXTURE_NOT_PRODUCTION_EVIDENCE',current_pointer:{job_id:current,state:'QUEUED',target_date:'20261021'},
    current_job:{job_id:current,state:'FAILED',target_date:'20261021',failure_code:'EXTENSION_PROMPT_TOKEN_CAP_EXCEEDED'},
    day_summary:{ target_trade_date:'20261021', availability:'AVAILABLE',contribution_count:1,candidate_stocks:1,
      unreviewed_count:1,isolated_count:1,contributions:[{job_id:old,availability:'AVAILABLE',delivery_sha256:'e'.repeat(64),
        semantic_review_sha256:'f'.repeat(64),capture_product:{sha256:'1'.repeat(64)},stocks:[]}]},
    unreviewed_contributions:[{job_id:'c'.repeat(32),availability:'UNREVIEWED',reason:'SEMANTIC_REVIEW_NOT_VERIFIED',stocks:[]}],
    isolated_contributions:[{job_id:'d'.repeat(32),availability:'ISOLATED',reason:'DELIVERY_SOURCE_BINDING_CHANGED',stocks:[]}],
    dedupe_evidence:[{symbol:'HK.00001',article_id:'same',body_sha256:'2'.repeat(64),source_sha256:'3'.repeat(64),job_ids:[old,current],basis:'SYMBOL_ARTICLE_BODY_SHA'}] };
}
function transport(value=data()) {
  return vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if ((init?.method || 'GET') !== 'GET') throw Error('unexpected POST');
    return new Response(JSON.stringify(wrap(String(url).endsWith('/context') ? context : value)), {status:200});
  });
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe('isolated announcement page', () => {
  it('mount/focus/refresh only GET isolated routes; shows fixture and actual attempt separately', async () => {
    const fetcher=transport();
    vi.stubGlobal('fetch', vi.fn(() => { throw Error('global production fetch forbidden'); }));
    render(App, {props:{transport:fetcher}});
    await screen.findByText(/14.*201/);
    expect(screen.getAllByText(/FIXTURE_NOT_PRODUCTION_EVIDENCE/).length).toBeGreaterThan(0);
    const pointer=screen.getByLabelText('当前任务与保存指针').textContent;
    expect(pointer).toContain('FAILED');expect(pointer).toContain('QUEUED');expect(pointer).toContain('EXTENSION_PROMPT_TOKEN_CAP_EXCEEDED');
    expect(screen.getByLabelText('目标日合法贡献').textContent).toContain('a'.repeat(32));
    expect(screen.getByLabelText('目标日合法贡献').textContent).toContain('f'.repeat(64));
    expect(screen.getByLabelText('未复核与隔离贡献').textContent).toContain('UNREVIEWED');
    expect(screen.getByLabelText('未复核与隔离贡献').textContent).toContain('ISOLATED');
    expect(screen.getByLabelText('去重依据').textContent).toContain('SYMBOL_ARTICLE_BODY_SHA');
    expect(screen.queryByRole('button',{name:'检查新增公告并预处理'})).toBeNull();
    expect(screen.queryByRole('button',{name:'按日期查看历史'})).toBeNull();
    window.dispatchEvent(new Event('focus'));
    await fireEvent.click(screen.getByRole('button',{name:'刷新只读上下文'}));
    await waitFor(() => expect(fetcher.mock.calls.length).toBeGreaterThan(3));
    expect(fetcher.mock.calls.every(([url,init]) => String(url).startsWith('/api/v4/announcement-test/') && (!init?.method || init.method==='GET'))).toBe(true);
  });
  it('closed transport rejects all formal actions, foreign dates and fixture canary', async () => {
    const fetcher=transport();const session=await createTestApi(fetcher);
    await expect(session.announcementApi.startAnnouncementFlashUpdate('20261021')).rejects.toThrow();
    await expect(session.announcementApi.getAnnouncementFlash('20261022')).rejects.toThrow();
    await expect(session.executeCanary()).rejects.toThrow();
    expect(fetcher.mock.calls.every(([,init]) => !init?.method || init.method==='GET')).toBe(true);
  });
  it('shows read failure honestly without canary action', async () => {
    const fetcher=transport();fetcher.mockRejectedValueOnce(Error('fixture unavailable'));
    render(App,{props:{transport:fetcher}});await screen.findByRole('alert');
    expect(screen.queryByRole('button',{name:/执行.*canary/})).toBeNull();
  });
});

it('rejects a response bound to another test manifest', async () => {
  const value=data();value.test_context_binding.source_manifest_sha256='0'.repeat(64);
  const session=await createTestApi(transport(value));
  await expect(session.announcementApi.getAnnouncementFlash('20261021')).rejects.toThrow();
});

it('polls only the fixed test target while an actual attempt is running', async () => {
  const value=data();value.current_job.state='RUNNING';
  const fetcher=transport(value);
  const { unmount }=render(App,{props:{transport:fetcher}});
  await screen.findByLabelText('当前任务与保存指针');
  vi.useFakeTimers();
  window.dispatchEvent(new Event('focus'));
  await vi.advanceTimersByTimeAsync(1900);
  expect(fetcher.mock.calls.every(([url,init]) => String(url).endsWith('/context') ||
    (String(url).includes('target_date=20261021') && (!init?.method || init.method==='GET')))).toBe(true);
  unmount();vi.useRealTimers();
});

it('renders each job full analysis under its own SHA and retains an unavailable neighbor', async () => {
  const base=data();
  const article={article_id:'FIXTURE:ONE',source_sha256:'1'.repeat(64),body_sha256:'2'.repeat(64),result_sha256:'3'.repeat(64),state:'SUCCEEDED',title:'Fixture 完整分析'};
  const reader={disposition:'SELECTED_EVENT',direction:'POSITIVE',selection_basis:'synthetic basis',evidence_sufficiency:'FIXTURE',reason:'fixture reason',
    facts:[{claim:'fact',quote:'unique complete quotation',locator:'L1'}],changes:[],impact:[],confirmation_conditions:[],counter_evidence:[],risk_notes:[],source_sha256:article.source_sha256,body_sha256:article.body_sha256};
  const contribution=base.day_summary.contributions[0]!;
  const good={...contribution,daily_delivery:{job_id:contribution.job_id,target_trade_date:'20261021',preprocessing_report_sha256:'4'.repeat(64),state:'PARTIAL',articles:[article],counts:{}},
    daily_analysis:{schema:'v4.manager_workbench.announcement_analysis_projection.v1',delivery_sha256:contribution.delivery_sha256,articles:[{...article,analysis_state:'AVAILABLE',reader_output:reader}]}};
  const bad={...good,job_id:'9'.repeat(32),daily_delivery:{...good.daily_delivery,job_id:'9'.repeat(32),articles:[{...article,article_id:'FIXTURE:BAD',title:'Fixture 无法读取'}]},
    daily_analysis:{...good.daily_analysis,delivery_sha256:'0'.repeat(64)}};
  const fetcher=transport({...base,day_summary:{...base.day_summary,contributions:[good,bad]}});
  render(App,{props:{transport:fetcher}});
  await screen.findByText('unique complete quotation');
  expect(screen.getByText('L1')).toBeTruthy();
  expect(screen.getByText(/完整分析暂不可读/)).toBeTruthy();
});

it('guards mutating handlers even when invoked directly in readonly mode', async () => {
  const { mount }=await import('@vue/test-utils');
  const { default: Candidates }=await import('../manager-workbench/AnnouncementCandidates.vue');
  const { createWorkbenchApi }=await import('../manager-workbench/api');
  const api=createWorkbenchApi(vi.fn());
  for (const method of ['startAnnouncementFlashUpdate','stopAnnouncementFlash','executePreprocessedAnnouncement','resumeAnnouncementFlash'] as const)
    api[method]=vi.fn() as never;
  api.getAnnouncementFlash=vi.fn(async () => wrap(data())) as never;
  const wrapper=mount(Candidates,{props:{targetDate:'20261021',api,readOnly:true,lockTargetDate:true}});
  const state=(wrapper.vm as unknown as {$:{setupState:Record<string,(...args:unknown[])=>Promise<void>>}}).$.setupState;
  for (const name of ['startUpdate','stopUpdate','executeRecovery','executePrepared','resumeUpdate']) await state[name]?.('FIRST');
  expect(api.startAnnouncementFlashUpdate).not.toHaveBeenCalled();expect(api.stopAnnouncementFlash).not.toHaveBeenCalled();
  expect(api.executePreprocessedAnnouncement).not.toHaveBeenCalled();expect(api.resumeAnnouncementFlash).not.toHaveBeenCalled();
  wrapper.unmount();
});

describe('TASK7-R1 displayed delivery row progress', () => {
  function articles(prefix: string, states: (string | undefined)[]) {
    return states.map((state, index) => ({ article_id: `${prefix}:${index}`, state,
      body_sha256: '2'.repeat(64), source_sha256: '3'.repeat(64), title: `${prefix} ${index}` }));
  }
  function delivery(job: string, rows: ReturnType<typeof articles>) {
    return { job_id: job, target_trade_date: '20261021', preprocessing_report_sha256: '4'.repeat(64),
      state: 'PARTIAL', articles: rows, counts: {},
      model_progress: { total: 208, counts: { SUCCEEDED: 7, PENDING: 201 } } };
  }
  it('counts all215 task-article rows:14 succeeded and201 pending across both deliveries', async () => {
    const base = data();
    const first = delivery('a'.repeat(32), articles('first', Array(7).fill('SUCCEEDED')));
    const last = delivery('b'.repeat(32), articles('last', [...Array(7).fill('SUCCEEDED'), ...Array(201).fill('PENDING')]));
    const contributions = [first, last].map(saved => ({ ...base.day_summary.contributions[0]!,
      job_id: saved.job_id, daily_delivery: saved }));
    render(App, { props: { transport: transport({ ...base, daily_delivery: last,
      day_summary: { ...base.day_summary, contribution_count: 2, contributions } } as ReturnType<typeof data>) } });
    const progress = await screen.findByLabelText('逐篇列表记录统计');
    expect(progress.textContent).toBe('本列表按任务计：共 215 条文章记录，完成 14，失败 0，待分析 201，其他状态 0。同一文章跨任务分别计数。');
    const list = screen.getByLabelText('逐篇交付与未完成');
    expect(list.querySelectorAll(':scope > ul > li')).toHaveLength(215);
    expect(list.textContent).not.toContain('共 208 篇，完成 7');
  });
  it('counts the same article separately under its two contributing jobs', async () => {
    const base = data();
    const rows = articles('same', ['SUCCEEDED']);
    const contributions = ['a', 'b'].map(id => ({ ...base.day_summary.contributions[0]!,
      job_id: id.repeat(32), daily_delivery: delivery(id.repeat(32), rows) }));
    render(App, { props: { transport: transport({ ...base,
      day_summary: { ...base.day_summary, contribution_count: 2, contributions } }) } });
    const progress = await screen.findByLabelText('逐篇列表记录统计');
    expect(progress.textContent).toContain('共 2 条文章记录，完成 2');
    expect(progress.textContent).toContain('同一文章跨任务分别计数');
  });
  it.each([
    { name: 'legacy mixed and missing states', states: ['SUCCEEDED', 'FAILED', 'PENDING', 'DEFERRED', 'PARTIAL', '', undefined],
      expected: '共 7 条文章记录，完成 1，失败 1，待分析 2，其他状态 3' },
    { name: 'legacy empty delivery without model progress', states: [],
      expected: '共 0 条文章记录，完成 0，失败 0，待分析 0，其他状态 0' },
  ])('$name uses only rows from the displayed single-delivery fallback', async ({states, expected}) => {
    const { default: Candidates } = await import('../manager-workbench/AnnouncementCandidates.vue');
    const base = data();
    const value = { ...base, day_summary: undefined, unreviewed_contributions: undefined,
      daily_delivery: { ...delivery('a'.repeat(32), articles('legacy', states)), model_progress: undefined } };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(wrap(value)), {status:200})));
    render(Candidates, {props: {targetDate:'20261021'}});
    const progress = await screen.findByLabelText('逐篇列表记录统计');
    expect(progress.textContent).toContain(expected);
    expect(screen.getByRole('button', {name:'检查新增公告并预处理'})).toBeTruthy();
  });
});
