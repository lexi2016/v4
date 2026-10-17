# Friday US research and Chat repair handoff

- User objective: research from US session 20261016 and a self-contained Chat repair packet for the missing post-close automatic selection.
- Canonical source: `/Users/lexi/Desktop/学习/v4_app`.
- GitHub baseline: `5e780a69134b1273bb467f7e3ed6858651973e81`.
- Handoff branch: `codex/us-hk-friday-close-packet-20261017` in private `lexi2016/v4`.
- Research output: [reports/REPORT.md](reports/REPORT.md); source capture is local, Futu after-close snapshot, not an independently certified daily-close bar.
- Repair brief: [packet/CHAT_ISSUE.md](packet/CHAT_ISSUE.md).
- Runtime audit: [audit/READ_ONLY_AUDIT.md](audit/READ_ONLY_AUDIT.md).
- Frozen problems: release identity blocks workload; scheduled date/US session/HK target differ; no evidenced post-close refresh of the existing target draft; displayed 1003-relation catalog differs from the currently consumed 37 relation identities.
- US session 20261016 maps to next HK session 20261020; 20261019 is a holiday.

## Boundaries

This task produces research and a code-repair handoff. No business-code fix, service/configuration change, application deployment, automatic recovery, API/UI integration of the manual output, notification delivery, or natural-slot validation is claimed. The observed next-HK-date page still displayed the pre-US-close draft `5feb2dbf6d3c4b6b8598e9dae67af542`, generated 20261016 17:39 HKT, with `INPUT_MISSING / US_MAPPING_EXACT_DATE_BINDING_MISSING`.

The local report covers 448 requested symbols, 446 with usable Friday after-close snapshot fields and two missing update times. The positive bucket describes source-price direction, not a beneficial HK price impact. Cost exposures and weak peer context need their own direction and scope interpretation. Raw captures and full coverage CSV remain local and are excluded from GitHub.

## Acceptance and synchronization

Independent REVIEWED and TESTED: PASS for the frozen descriptive replay and final packet integrity. See INDEPENDENT_REVIEW.md/json. BEHAVIOR_VERIFIED applies only to the deterministic descriptive builder; automatic selection is CANNOT_CONFIRM. Final GitHub readback is recorded separately in GITHUB_SYNC_RECEIPT.json. No new runtime tests or repairs were performed.

`RESEARCH_ONLY=true`; `production_allowed=false`; `buy_gate_updated=false`; `orders_sent=false`.
