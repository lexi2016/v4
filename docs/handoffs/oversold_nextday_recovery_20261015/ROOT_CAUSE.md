# Initial root-cause evidence

Read-only investigator: oversold_binding_triage, Luna Max; controller consumed its final report.

Failed saved NEXT_DAY run: 18425e50e6294f15a6bc02ac881c5af2; target 20261016; source HK session 20261015; cutoff 2026-10-15 16:30 +08. API/live UI returns INPUT_MISSING / HK_PANEL_EXACT_DATE_BINDING_MISSING, not a completed empty selection.

The existing shared owner panel assets/hk_0_2/panels/20261015-a562369dbc49/manifest.json (SHA a562369dbc49f06761304c10ba7128d2289c7f0befd0d9264f7dbbc50404241c) was published 17:20:02 +08; exact-date security master was captured 17:30:18 +08. Both are later than the saved cutoff. Current exact-date resolver correctly rejects them for the old cutoff.

The existing MANUAL run endpoint permits a fresh actual cutoff and OVERSOLD-only lanes; retry of the old run preserves the old cutoff and is unsuitable. The current panel has 58 of 61 expected sessions in the required window 20260722–20261015; exact missing dates and actual engine consequences are assigned to the execution writer. No last-known-good run was established. Same-source/unit/adjustment rules must be assessed under the existing engine, not invented or weakened. No code change is currently justified for the original temporal rejection.
