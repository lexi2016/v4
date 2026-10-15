GOAL: Preserve 667 stocks / 1003 original relations, integrate source-bound 40-record review overlay, browse/search/filter and clickable sources, measured catalog loading improvement.
WRITER: us_mapping_finish_writer (gpt-6.1-sol high, explicit user override).
REVIEWER: independent identity assigned by controller; writer tests are supporting evidence only.
ALLOWED_PATHS: v4/manager_workbench/us_mapping_catalog.py; api.py catalog route only; research_data/us_hk_667_review_overlay_20261015.json; apps/web/src/manager-workbench/{Workbench.vue,types.ts,api.ts,useWorkbench.ts} catalog only; catalog Python/Vue tests; this handoff directory.
FORBIDDEN_PATHS: all other business code, engine, fixed33 sources, scoring, BUY, services, original source/catalog JSON.
PASS_SIGNAL: conservation + fail-closed tamper tests + API/component target behavior + measured loading improvement; independent reviewer.
STOP_RULE: missing source identity, source row mismatch or unsafe promotion blocks overlay; no service/deploy/commit/push by writer.
RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
