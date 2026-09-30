<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";

import DailyResearchAlertPanel from "../components/daily-research-command/DailyResearchAlertPanel.vue";
import DailyResearchHourlyDiagnostic from "../components/daily-research-command/DailyResearchHourlyDiagnostic.vue";
import DailyResearchHero from "../components/daily-research-command/DailyResearchHero.vue";
import DailyResearchLineage from "../components/daily-research-command/DailyResearchLineage.vue";
import DailyResearchMetrics from "../components/daily-research-command/DailyResearchMetrics.vue";
import DailyResearchPools from "../components/daily-research-command/DailyResearchPools.vue";
import DailyResearchSlotMatrix from "../components/daily-research-command/DailyResearchSlotMatrix.vue";
import type {
  DailyResearchCommandState,
  DailyResearchSafetyKey,
  DailyResearchSafetyValues,
  DailyResearchPayload,
} from "../components/daily-research-command/types";
import {
  DAILY_RESEARCH_ORIGINS,
  DAILY_RESEARCH_SAFETY_KEYS,
} from "../components/daily-research-command/types";

const VALID_STATES = new Set<DailyResearchCommandState>([
  "READY",
  "READY_WITH_DECLARED_GAPS",
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
]);

const requestedDate = ref<string | null>(null);
const state = ref<DailyResearchCommandState>("NO_DATE_SELECTED");
const payload = ref<DailyResearchPayload | null>(null);
const safetyFlags = ref<DailyResearchSafetyValues | null>(null);
const errorMessage = ref<string | null>(null);
const requestSequence = ref(0);

function isCalendarDate(value: string): boolean {
  if (!/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= daysInMonth[month - 1];
}

function compactDate(value: string): string | null {
  const compact = value.replaceAll("-", "");
  return isCalendarDate(compact) ? compact : null;
}

function selectedQueryDate(): string | null {
  const value = new URLSearchParams(window.location.search).get("date");
  if (!value) return null;
  return isCalendarDate(value) ? value : null;
}

function setBrowserDate(date: string | null) {
  const url = new URL(window.location.href);
  if (date) url.searchParams.set("date", date);
  else url.searchParams.delete("date");
  window.history.replaceState({}, "", `${url.pathname}${url.search}`);
}

function isExactResponseFor(body: Partial<DailyResearchPayload>, date: string): boolean {
  if (body.archive_date !== date) return false;
  if (body.requested_date !== undefined && body.requested_date !== date) return false;
  if (body.resolved_date !== undefined && body.resolved_date !== null && body.resolved_date !== date) return false;
  if (!["NOT_MATERIALIZED", "CANNOT_CONFIRM"].includes(body.status ?? "") && body.resolved_date !== date) return false;
  return body.date_mode === "EXACT";
}

function displayWireValue(value: unknown): string {
  if (value === undefined) return "CANNOT_CONFIRM";
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "boolean" || typeof value === "number") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "CANNOT_CONFIRM";
  }
}

function readWireSafety(body: Partial<DailyResearchPayload>): DailyResearchSafetyValues {
  return Object.fromEntries(
    DAILY_RESEARCH_SAFETY_KEYS.map((key) => [key, body[key as DailyResearchSafetyKey]]),
  ) as DailyResearchSafetyValues;
}

function safetyIssues(body: Partial<DailyResearchPayload>): string[] {
  return DAILY_RESEARCH_SAFETY_KEYS.flatMap((key) => {
    const value = body[key as DailyResearchSafetyKey];
    const expected = key === "RESEARCH_ONLY" ? true : false;
    return value === expected ? [] : [`${key}=${displayWireValue(value)} expected ${expected}`];
  });
}

function executionOriginIssues(body: Partial<DailyResearchPayload>): {
  issues: string[];
  missing: boolean;
} {
  const value = body.execution_origin;
  if (value === undefined) {
    return { issues: ["execution_origin=CANNOT_CONFIRM"], missing: true };
  }
  if (
    typeof value !== "string" ||
    !DAILY_RESEARCH_ORIGINS.includes(value as (typeof DAILY_RESEARCH_ORIGINS)[number])
  ) {
    return { issues: [`execution_origin=${displayWireValue(value)}`], missing: false };
  }
  return { issues: [], missing: false };
}

function strictWireIssues(body: Partial<DailyResearchPayload>, date: string): string[] {
  const issues: string[] = [];
  if (body.schema_version !== "v3_5.research_day_product.v1") issues.push(`schema_version=${displayWireValue(body.schema_version)}`);
  if (body.contract_id !== "v3_5.research_day_product.v1") issues.push(`contract_id=${displayWireValue(body.contract_id)}`);
  if (body.workflow_name !== "V35_DAILY_RESEARCH_AUTHORITY_V1") issues.push(`workflow_name=${displayWireValue(body.workflow_name)}`);
  if (body.pass_signal !== "V35_DAILY_RESEARCH_AUTHORITY_PASS_V1") issues.push(`pass_signal=${displayWireValue(body.pass_signal)}`);
  if (body.endpoint_mode !== "EXACT") issues.push(`endpoint_mode=${displayWireValue(body.endpoint_mode)}`);
  if (body.date_mode !== "EXACT") issues.push(`date_mode=${displayWireValue(body.date_mode)}`);
  if (body.timezone !== "Asia/Shanghai") issues.push(`timezone=${displayWireValue(body.timezone)}`);
  if (body.archive_date !== date) issues.push(`archive_date=${displayWireValue(body.archive_date)}`);
  if (body.requested_date !== date) issues.push(`requested_date=${displayWireValue(body.requested_date)}`);
  if (!["NOT_MATERIALIZED", "CANNOT_CONFIRM"].includes(body.status ?? "") && body.resolved_date !== date) issues.push(`resolved_date=${displayWireValue(body.resolved_date)}`);
  if (body.write_policy !== "read_only") issues.push(`write_policy=${displayWireValue(body.write_policy)}`);
  if (body.recommendation_status !== "RESEARCH_ONLY") issues.push(`recommendation_status=${displayWireValue(body.recommendation_status)}`);
  return [...issues, ...safetyIssues(body), ...executionOriginIssues(body).issues];
}

async function loadDate(date: string) {
  const requestId = ++requestSequence.value;
  requestedDate.value = date;
  payload.value = null;
  safetyFlags.value = null;
  errorMessage.value = null;
  state.value = "LOADING";

  try {
    const response = await fetch(`/api/v3/research/day?archive_date=${date}`);
    if (requestId !== requestSequence.value) return;
    if (!response.ok) {
      throw new Error(`strict day request failed (${response.status})`);
    }
    const rawBody = await response.json();
    if (!rawBody || typeof rawBody !== "object") {
      payload.value = null;
      safetyFlags.value = null;
      state.value = "REJECTED";
      errorMessage.value = "strict day response is not an object";
      return;
    }
    const body = rawBody as Partial<DailyResearchPayload>;
    if (requestId !== requestSequence.value) return;
    safetyFlags.value = readWireSafety(body);
    if (!isExactResponseFor(body, date)) {
      payload.value = null;
      state.value = "STALE";
      errorMessage.value = null;
      return;
    }
    if (!body.status || !VALID_STATES.has(body.status as DailyResearchCommandState)) {
      payload.value = null;
      state.value = "REJECTED";
      errorMessage.value = `unsupported day product status: ${String(body.status ?? "missing")}`;
      return;
    }
    const wireIssues = strictWireIssues(body, date);
    if (wireIssues.length) {
      payload.value = body as DailyResearchPayload;
      const nonRejectingIssues = [
        ...safetyIssues(body),
        ...(executionOriginIssues(body).missing ? executionOriginIssues(body).issues : []),
      ];
      state.value = wireIssues.every((issue) => nonRejectingIssues.includes(issue))
        ? "CANNOT_CONFIRM"
        : "REJECTED";
      errorMessage.value = wireIssues.join("; ");
      return;
    }
    const nextPayload = body as DailyResearchPayload;
    payload.value = nextPayload;
    if (nextPayload.status === "READY" && nextPayload.authoritative !== true) {
      state.value = "CANNOT_CONFIRM";
    } else {
      state.value = nextPayload.status as DailyResearchCommandState;
    }
  } catch (error) {
    if (requestId !== requestSequence.value) return;
    payload.value = null;
    state.value = "ERROR";
    errorMessage.value = error instanceof Error ? error.message : "strict day request failed";
  }
}

function handleDateChange(value: string) {
  const date = compactDate(value);
  ++requestSequence.value;
  payload.value = null;
  safetyFlags.value = null;
  errorMessage.value = null;
  if (!value) {
    requestedDate.value = null;
    state.value = "NO_DATE_SELECTED";
    setBrowserDate(null);
    return;
  }
  if (!date) {
    requestedDate.value = null;
    state.value = "REJECTED";
    errorMessage.value = "研究日期不是有效的日历日期";
    setBrowserDate(null);
    return;
  }
  setBrowserDate(date);
  void loadDate(date);
}

async function loadDefaultDate(): Promise<void> {
  // Without an explicit date the page follows the same canonical default the
  // rest of the app uses (newest verified evidence date); the strict day API
  // still receives exactly that one date — no latest substitution happens.
  try {
    const response = await fetch("/api/v1/runs/date-list");
    if (!response.ok) throw new Error("date-list request failed");
    const catalog = (await response.json()) as { default_date?: unknown; dates?: unknown };
    const candidate =
      typeof catalog?.default_date === "string" && catalog.default_date
        ? catalog.default_date
        : Array.isArray(catalog?.dates) && typeof catalog.dates[0] === "string"
          ? catalog.dates[0]
          : "";
    if (!isCalendarDate(candidate)) {
      state.value = "NO_DATE_SELECTED";
      return;
    }
    setBrowserDate(candidate);
    void loadDate(candidate);
  } catch {
    state.value = "NO_DATE_SELECTED";
  }
}

onMounted(() => {
  const date = selectedQueryDate();
  if (!date) {
    const raw = new URLSearchParams(window.location.search).get("date");
    if (raw) {
      requestedDate.value = raw;
      state.value = "REJECTED";
      errorMessage.value = "研究日期不是有效的日历日期";
      return;
    }
    void loadDefaultDate();
    return;
  }
  void loadDate(date);
});

onBeforeUnmount(() => {
  ++requestSequence.value;
});
</script>

<template>
  <main class="daily-research-command__page" :data-state="state">
    <DailyResearchHero
      :state="state"
      :requested-date="requestedDate"
      :payload="payload"
      :safety-flags="safetyFlags"
      @date-change="handleDateChange"
    />

    <div class="daily-research-command__content">
      <DailyResearchAlertPanel :state="state" :payload="payload" :error-message="errorMessage" />

      <section v-if="state === 'NO_DATE_SELECTED'" class="daily-research-command__empty-state">
        <p class="daily-research-command__eyebrow">NO DATE SELECTED</p>
        <h2>请选择 exact research date</h2>
        <p>此页面不会读取 latest；选择日期后才会发起 strict day 请求。</p>
      </section>
      <section v-else-if="state === 'LOADING'" class="daily-research-command__loading-state" aria-busy="true">
        <span class="daily-research-command__loading-bar"></span>
        <span class="daily-research-command__loading-bar daily-research-command__loading-bar--short"></span>
        <strong>LOADING exact day product…</strong>
      </section>
      <section v-else-if="state === 'ERROR' || state === 'REJECTED' || state === 'STALE'" class="daily-research-command__empty-state daily-research-command__empty-state--error">
        <p class="daily-research-command__eyebrow">FAIL CLOSED</p>
        <h2>FAIL CLOSED · {{ state }}</h2>
        <p>{{ errorMessage ?? "response was not promoted into the selected date" }}</p>
      </section>
      <template v-else-if="payload">
        <DailyResearchMetrics :payload="payload" />
        <DailyResearchSlotMatrix :payload="payload" />
        <DailyResearchLineage :payload="payload" />
        <DailyResearchHourlyDiagnostic :payload="payload" />
        <DailyResearchPools :payload="payload" />
      </template>
    </div>

    <footer class="daily-research-command__footer">
      <span>contract_id=v3_5.research_day_product.v1</span>
      <span>workflow=V35_DAILY_RESEARCH_AUTHORITY_V1</span>
      <span>read_only / CANNOT_CONFIRM when the chain is incomplete</span>
    </footer>
  </main>
</template>
