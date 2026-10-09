# Regression reproduction

Independent comparison command used on the Mac:

```sh
/Users/lexi/Desktop/学习/v4_app/.venv/bin/python -B /Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_DEPLOY_20261009/review/compare_legacy_frontend_failures.py
```

The runner compares the exact active rollback copy with the integrated candidate using the same eight existing Vitest specs, Node `v24.19.0`, Vitest `4.1.10`, and Python `3.14.6`. The recorded before/after cwd, config, exact selected-spec command, exit code, summary, and SHA values are in `reviewer/legacy-frontend-failure-classification.json`; raw logs are adjacent in `reviewer/logs/`. This is synthetic frontend test evidence only; it does not call live APIs or write business state.

Recorded outcome: active rollback `14 failed / 215 passed` across 229 tests, with `issue8R2.spec.ts` 76/76 passing; integrated candidate `59 failed / 170 passed`, with 45 additional failures confined to the same unchanged 76-test `issue8R2.spec.ts`. All 14 other baseline failures were unchanged.

The focused contract check used for the three-channel candidate is recorded in `D/evidence/frontend_targeted_receipt.json` and `D/evidence/frontend_typecheck_retry1_receipt.json` from the deployment evidence root. It passed 25/25 specs and changed-source typecheck before this regression was discovered by the broader matched baseline comparison.
