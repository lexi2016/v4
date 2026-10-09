import { describe, expect, it } from 'vitest';
import { validateManagerWorkspace, type JsonObject } from './managerWorkspace';
import { fixture, date } from '../manager-selection/__tests__/fixtures/issue8R2.fixture';
import { dailyFixture, testFlags } from '../manager-selection/dailyChannels.testHelper';

// Synthetic coexistence checks. The original Issue8 fixtures and focused specs
// remain unchanged; no live source, API, browser, or business state is accessed.
const bindings = { plan_date: date, selection_date: '20260930', announcement_date: '20261001' };
const countFields = ['input_candidate_count', 'history_complete_count', 'history_pending_count',
  'strict_count', 'near_candidate_count', 'near_count', 'selected_count', 'panel_row_count', 'panel_code_count'];

function envelope(): JsonObject {
  const value = fixture() as JsonObject;
  const daily = dailyFixture(bindings) as unknown as JsonObject;
  for (const channel of daily.channels as JsonObject[]) {
    if (channel.channel === 'ANNOUNCEMENT') {
      const generatedAt = '2026-10-02T07:05:00+08:00';
      channel.generated_at = generatedAt;
      for (const check of channel.product_checks as JsonObject[]) check.owner_available_at = generatedAt;
      for (const row of channel.rows as JsonObject[]) row.generated_at = generatedAt;
    } else {
      channel.data_date = bindings.selection_date;
      if (channel.data_context) (channel.data_context as JsonObject).market_session = bindings.selection_date;
    }
  }
  value.date_bindings = { ...bindings };
  value.daily_channels = daily;
  value.market_screen = { ...testFlags,
    schema_version: 'v4.manager_research.rebound_v3_screen.v1',
    rule_version: '20260923_REBOUND_TWO_GATE_V1', target_trade_date: date, verified_session: date,
    status: 'CANNOT_CONFIRM', main_screen_ready: false, cards: [], strict: [], near: [], pending: [],
    input_identity: null, authority: null,
    coverage: { counts_known: false, ...Object.fromEntries(countFields.map(key => [key, null])) },
    gaps: ['SYNTHETIC_UNAVAILABLE_SCREEN'],
  };
  return value;
}

function firstObservation(value: JsonObject): JsonObject {
  const attention = value.research_attention as JsonObject;
  return ((attention.observation_only as JsonObject).cards as JsonObject[])[0];
}

function inputDiagnostics(value: JsonObject): JsonObject {
  return (value.research_attention as JsonObject).input_diagnostics as JsonObject;
}

function check(value: JsonObject): unknown {
  return validateManagerWorkspace(value, date, bindings);
}

function rejectUnchanged(value: JsonObject, error: string): void {
  const before = structuredClone(value);
  expect(() => check(value)).toThrowError(new Error(error));
  expect(value).toEqual(before);
}

describe('restored research validators coexist with three-channel contracts', () => {
  it('accepts observations, distinct channel dates and unknown screen counts without mutation', () => {
    const value = envelope(), before = structuredClone(value);
    expect(check(value)).toBe(value);
    expect(value).toEqual(before);
  });

  it('rejects an unsafe independent observation in the same envelope', () => {
    const value = envelope();
    firstObservation(value).orders_sent = true;
    rejectUnchanged(value, 'WORKSPACE_SAFETY_INVALID');
  });

  it('rejects assessed-zero when the US input remains incomplete', () => {
    const value = envelope();
    (inputDiagnostics(value).us_relations as JsonObject).assessment_state = 'ASSESSED_ZERO';
    rejectUnchanged(value, 'WORKSPACE_US_INPUT_COMPLETENESS_INVALID');
  });

  it('rejects a different calendar SHA in the filtered research scope', () => {
    const value = envelope();
    const scope = (inputDiagnostics(value).scope as JsonObject).announcements as JsonObject;
    ((scope.formal_selection as JsonObject).calendar as JsonObject).calendar_sha256 = 'd'.repeat(64);
    rejectUnchanged(value, 'WORKSPACE_RESEARCH_DISPLAY_CALENDAR_BINDING_INVALID');
  });

  it('continues rejecting an unknown-count screen that claims zero selected rows', () => {
    const value = envelope();
    ((value.market_screen as JsonObject).coverage as JsonObject).selected_count = 0;
    rejectUnchanged(value, 'WORKSPACE_SCREEN_COUNT_INVALID');
  });

  it('continues rejecting an announcement date different from the requested binding', () => {
    const value = envelope();
    (value.date_bindings as JsonObject).announcement_date = '20260930';
    rejectUnchanged(value, 'WORKSPACE_DAILY_DATE_BINDING_MISMATCH');
  });

  it('preserves valid minute-only observation clocks with an explicit timezone', () => {
    const value = envelope();
    Object.assign(firstObservation(value), { published_at: '2026-10-01T17:27+08:00',
      retrieved_at: '2026-10-01T17:27+08:00', available_at: '2026-10-01T17:27+08:00' });
    const before = structuredClone(value);
    expect(check(value)).toBe(value);
    expect(value).toEqual(before);
  });

  it('rejects an observation clock that Date.parse would roll from hour 24 to the next day', () => {
    const value = envelope();
    Object.assign(firstObservation(value), { published_at: '2026-10-01T24:00:00+08:00',
      retrieved_at: '2026-10-01T24:00:00+08:00', available_at: '2026-10-01T24:00:00+08:00' });
    rejectUnchanged(value, 'WORKSPACE_OBSERVATION_TIME_INVALID');
  });
});
