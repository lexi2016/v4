import { describe, expect, it } from 'vitest';
import { renderAnnouncementReview } from '../announcementObservation';
import { validateAnnouncementReview } from '../../api/managerWorkspace';

const date = '20261012';
const safety = { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
const actualTarget = {
  ...safety,
  event_id: 'df4455e516ebf322f437665d042a511542db1e08c0446f33675305c99e5b7f90',
  news_id: '12369250',
  target_trade_date: date,
  symbol: 'HK.02665',
  name: '图达通',
  title: '自願性公告 未經審核之二零二六年第三季度激光雷達出貨量',
  source: 'HKEX_OFFICIAL',
  source_identity: 'HKEX_OFFICIAL_MARKET_DIRECTORY',
  source_url: 'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/2026101200006_c.pdf',
  published_at: '2026-10-12T06:05+08:00',
  publication_date: '20261012',
  release_time: '12/10/2026 06:05',
  available_at: '2026-10-12T02:43:54+00:00',
  retrieved_at: '2026-10-12T02:43:55+00:00',
  body_observed_at: '2026-10-12T02:43:55+00:00',
  query_cutoff: '2026-10-12T10:43:28.075526+08:00',
  document_sha256: 'd004e3e4f2c9339f52b4a641452faee3b17edbdfcb13d45686b1234c01a14f57',
  body_status: 'BODY_CAPTURED_UNASSESSED',
  semantic_status: 'NOT_REVIEWED',
  body_reason: null,
};
const failedBody = {
  ...safety,
  event_id: 'b'.repeat(64),
  news_id: '99999999',
  target_trade_date: date,
  symbol: 'HK.00005',
  name: '测试发行人',
  title: '公告正文暂不可读取',
  source: 'HKEX_OFFICIAL',
  source_identity: 'HKEX_OFFICIAL_MARKET_DIRECTORY',
  source_url: 'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1012/body-failure.pdf',
  published_at: '2026-10-12T06:10:00+08:00',
  available_at: '2026-10-12T02:44:00+00:00',
  retrieved_at: '2026-10-12T02:44:01+00:00',
  body_status: 'BODY_FETCH_FAILED',
  semantic_status: 'NOT_REVIEWED',
  body_reason: 'HTTP_503',
};

function reviewFixture() {
  return {
    ...safety,
    schema_version: 'v4.manager_research.announcement_review.v1',
    target_trade_date: date,
    daily_publication_date: date,
    publication_timezone: 'Asia/Hong_Kong',
    status: 'PARTIAL',
    count_known: true,
    official_documents: [actualTarget, failedBody],
    coverage: {
      publication_date: date,
      source_coverage_cutoff: '2026-10-12T10:44:00+08:00',
      observed_document_count: 2,
      observed_count_is_not_market_total: true,
      queried_issuer_count: 0,
      successfully_observed_issuer_count: 0,
      failed_issuers: [],
      pending_issuers: [],
      directory_exhaustion: 'COMPLETE',
      market_directory_products: [{
        status: 'PARTIAL',
        from_date: '20261009',
        to_date: date,
        window_mode: 'FALLBACK_PREVIOUS_HK_SESSION_CLOSE',
        publication_window_start: '2026-10-09T16:10:00+08:00',
        query_cutoff: '2026-10-12T10:43:28.075526+08:00',
        loaded_record: 678,
        record_count: 678,
        captured_page_count: 7,
        expected_page_count: 7,
        directory_exhaustion: 'COMPLETE',
        body_document_count: 677,
        pending_document_count: 1,
        gaps: [],
        body_gaps: ['NEWS_ID99999999_BODY_FETCH_FAILED'],
      }],
    },
    gaps: ['ISSUER_LANE_NOT_QUERIED_IN_ISOLATED_CANARY'],
    capture_runs: [],
    retained_cross_day: { counts_by_publication_date: {}, source_products: [] },
  };
}

describe('HKEX publication-day review renderer', () => {
  it('accepts the observed official target row and preserves its HKEX date and time', () => {
    const value = validateAnnouncementReview(reviewFixture(), date);
    const target = value.official_documents.find(doc => doc.news_id === '12369250')!;
    expect(target.symbol).toBe('HK.02665');
    expect(target.published_at).toBe('2026-10-12T06:05+08:00');
    expect(target.body_status).toBe('BODY_CAPTURED_UNASSESSED');
    expect(target.semantic_status).toBe('NOT_REVIEWED');
    expect(target.document_sha256).toBe('d004e3e4f2c9339f52b4a641452faee3b17edbdfcb13d45686b1234c01a14f57');
  });

  it('shows the official 06:05 target, unassessed body, partial coverage, and failed-body row', () => {
    const value = validateAnnouncementReview(reviewFixture(), date);
    const host = document.createElement('section');
    renderAnnouncementReview(host, value, date);

    expect(host.textContent).toContain('部分覆盖');
    expect(host.textContent).toContain('HKEX 全市场目录：PARTIAL');
    expect(host.textContent).toContain('正文捕获缺口：NEWS_ID99999999_BODY_FETCH_FAILED');
    expect(host.textContent).toContain('展开 2 条已观察 HKEX 公告（不代表全市场总数）');

    const documents = host.querySelector<HTMLDetailsElement>('details[data-daily-announcement-documents]')!;
    documents.open = true;
    documents.dispatchEvent(new Event('toggle'));
    const target = host.querySelector<HTMLDetailsElement>(`details[data-announcement-source="${actualTarget.event_id}"]`)!;
    target.open = true;
    target.dispatchEvent(new Event('toggle'));
    expect(target.textContent).toContain(actualTarget.title);
    expect(target.textContent).toContain('HKEX_OFFICIAL_MARKET_DIRECTORY');
    expect(target.textContent).toContain('香港日期 20261012 12/10/2026 06:05');
    expect(target.textContent).toContain('BODY_CAPTURED_UNASSESSED');
    expect(target.textContent).toContain('NOT_REVIEWED');
    expect(target.textContent).toContain('2026-10-12T02:43:55+00:00');

    const failed = host.querySelector<HTMLDetailsElement>(`details[data-announcement-source="${failedBody.event_id}"]`)!;
    failed.open = true;
    failed.dispatchEvent(new Event('toggle'));
    expect(failed.textContent).toContain('BODY_FETCH_FAILED');
    expect(failed.textContent).toContain('HTTP_503');
  });

  it('keeps an unknown count visibly unknown instead of rendering zero records', () => {
    const raw = {
      ...safety,
      schema_version: 'v4.manager_research.announcement_review.v1',
      target_trade_date: date,
      daily_publication_date: date,
      publication_timezone: 'Asia/Hong_Kong',
      status: 'NOT_RUN',
      count_known: false,
      official_documents: [],
      coverage: {
        publication_date: date,
        source_coverage_cutoff: null,
        observed_document_count: null,
        observed_count_is_not_market_total: false,
        market_directory_products: [],
      },
      gaps: ['HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_NOT_RUN'],
      capture_runs: [],
      retained_cross_day: { counts_by_publication_date: {}, source_products: [] },
    };
    const value = validateAnnouncementReview(raw, date);
    const host = document.createElement('section');
    renderAnnouncementReview(host, value, date);

    expect(host.textContent).toContain('观察数量未知');
    expect(host.textContent).not.toContain('0 条已观察公告');
    expect(host.textContent).toContain('展开 0 条已观察 HKEX 公告（不代表全市场总数）');
  });
});
