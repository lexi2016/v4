# Friday US close observation and automation issue package

```text
GOAL: Use the completed 2026-10-16 US market session and the existing 667-stock / 1,003-relation recovery-overlay library to produce a reproducible research-only observation list, then package the evidenced failure to advance the US selection automatically for a Chat code repair.
WRITER: /root/friday_us_selection_packet_writer (sole writer for this handoff directory)
REVIEWER: Independent different-identity Luna Max Reviewer, read-only; inspect the actual handoff diff, replay frozen inputs, verify relation/bucket conservation and issue-package evidence, and report REVIEWED / BEHAVIOR_VERIFIED or FAIL.
ALLOWED_PATHS: docs/handoffs/us_hk_friday_close_20261017/** except audit/** and independent-review output; scripts, reports, evidence, packet, minimal source reproduction copies, and a local ZIP.
FORBIDDEN_PATHS: Business source, runtime/configuration, scheduler/service changes, mapping inputs, trading, raw quote-source mutation, Git operations, and external messages/actions.
PASS_SIGNAL: The 2026-10-16 Futu after-close snapshot timestamp/session and mapping identity are traceable; the deterministic join reproduces ranked observations and conserves all 1,003 relations; Chat package contains evidence-backed root cause or a precise CANNOT_CONFIRM, fixed source/target-date contract, minimal patch objective, acceptance matrix, source/version identity and replay instructions; independent Reviewer PASS. Official daily-close bar and canonical owner receipt remain CANNOT_CONFIRM.
STOP_RULE: Stop data capture if the owner source or date/session identity cannot be proved, or a recovery attempt would require a new producer, broad historical query, repeated quota spend, or a changed data contract. Keep source/root-cause gaps explicit and route them to the controller for a bounded recovery decision.
```

## Frozen research contract

- Target US session: Friday 2026-10-16 (`20261016`), after the session completed. A later Saturday capture timestamp alone does not establish exact-close data.
- Mapping set: current V4 recovery overlay with 667 Hong Kong stocks and 1,003 relations, overlay SHA-256 `3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c`; preserve 757 `CLOSED_RESEARCH_SCOPE`, 25 `CLOSED_EXCLUDED_SCOPE`, and 221 `OPEN` rows.
- Classification: a Futu snapshot with `update_time` on 2026-10-16 at or after 16:00 US Eastern and valid positive prices yields `positive` or `flat-negative` by `(last_price / prev_close_price) - 1`; missing or invalid exact-session timestamps/prices yield `missing`. This is an after-close quote snapshot, not a verified daily close. `OPEN` and `CLOSED_EXCLUDED_SCOPE` take precedence over price direction and never enter the observation list.
- Candidate order: group positive relations by mapped Hong Kong code, order by the strongest linked Futu snapshot change, and retain all positive relation identities, uses, current research statuses, evidence IDs, and gaps. This is a descriptive research observation only.
- Safety: `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`. No BUY recommendation or trade signal is produced.
- Next Hong Kong session: HKEX lists 2026-10-19 as a Hong Kong market holiday (the day following Chung Yeung Festival), so Monday is not the next HK trading session; the calendar points to Tuesday 2026-10-20. Source: [HKEX 2026 trading calendar](https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/Stock-Connect/Reference-Materials/Trading-Hour%2C-Trading-and-Settlement-Calendar/2026-Calendar_pdf_e.pdf).

## Completion state

- `IMPLEMENTED`: the one-shot Futu snapshot evidence, deterministic 1,003-relation result, and audit-based Chat repair issue are prepared under this handoff.
- `TESTED`: the frozen-input builder replay passes locally and conserves all 1,003 relation rows. The source is an after-close Futu snapshot, not an independently verified official daily-close bar or a shared owner receipt.
- `REVIEWED`: pending an independent different-identity Luna Max Reviewer.
- Scheduler repair, API/UI refresh, notification delivery, and natural-slot behavior are not implemented or verified in this handoff.
- The old 2026-10-16 target at 15:02 `INPUT_MISSING` / zero rows remains pre-market display evidence only. The current read-only audit is the authority for the later scheduler failure and missing post-close consumer handoff.
