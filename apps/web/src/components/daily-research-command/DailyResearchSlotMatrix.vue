<script setup lang="ts">
import { computed } from "vue";

import type { DailyResearchPayload, DailyResearchSlotRow } from "./types";
import { DAILY_RESEARCH_SLOTS } from "./types";

const props = defineProps<{ payload: DailyResearchPayload }>();

const rows = computed<DailyResearchSlotRow[]>(() => {
  const source = new Map((props.payload.slot_matrix ?? props.payload.coverage?.slot_matrix ?? []).map((row) => [row.slot, row]));
  return DAILY_RESEARCH_SLOTS.map((slot) => source.get(slot) ?? {
    slot,
    status: "MISSING",
    raw_rows: 0,
    exact_rows: 0,
    excluded_rows: 0,
  });
});
</script>

<template>
  <section class="daily-research-command__section daily-research-command__slot-section" aria-labelledby="daily-research-slots-title">
    <div class="daily-research-command__section-heading">
      <div>
        <p class="daily-research-command__eyebrow">SOURCE COVERAGE</p>
        <h2 id="daily-research-slots-title" class="daily-research-command__section-title">8 槽位矩阵</h2>
      </div>
      <span class="daily-research-command__coverage-badge">{{ props.payload.coverage?.ready_slots ?? 0 }}/{{ props.payload.coverage?.expected_slots ?? 8 }} READY</span>
    </div>
    <div class="daily-research-command__table-wrap">
      <table class="daily-research-command__slot-table" data-slot-matrix>
        <thead>
          <tr>
            <th scope="col">slot</th>
            <th scope="col">status</th>
            <th scope="col">raw</th>
            <th scope="col">exact</th>
            <th scope="col">excluded</th>
            <th scope="col">source / receipt</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.slot" :data-slot="row.slot">
            <th scope="row">{{ row.slot }}</th>
            <td><span class="daily-research-command__slot-status">{{ row.status }}</span></td>
            <td>{{ row.raw_rows }}</td>
            <td>{{ row.exact_rows }}</td>
            <td>{{ row.excluded_rows }}</td>
            <td class="daily-research-command__slot-lineage">
              <span>{{ row.artifact_sha256 ? `artifact ${row.artifact_sha256.slice(0, 8)}…` : "artifact CANNOT_CONFIRM" }}</span>
              <span>{{ row.receipt_sha256 ? `receipt ${row.receipt_sha256.slice(0, 8)}…` : "receipt CANNOT_CONFIRM" }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="daily-research-command__section-caption">每个 slot 保留 source artifact、input SHA 与 receipt 入口；缺一层即 CANNOT_CONFIRM。</p>
  </section>
</template>
