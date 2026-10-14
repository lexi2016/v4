# HK close union label repair · 2026-10-14

Goal: replace the misleading unavailable summary with existing observation counts and the exact pending evidence reason. Canonical source: `/Users/lexi/Desktop/学习/v4_app`; 8873 only. Vibe 8910 unchanged.

Baseline remote commit: `9e10fd96f3604f8b7c5743b26e831ed75796682d`. Only `HkCloseReviewPanel.vue`, its component spec, and this receipt are in the sync scope. Both remote baseline source files matched the preserved local before files.

The card now shows `7/20`, `已有观察结果 27 只`, and `09:40–09:45证据待验证：分钟数据为事后补采，不能证明当时已获得；没有留存该时段盘口`. Valid formal counts, including zero, retain precedence. Observation counts still require the existing count/code consistency checks. No metric, stage artifact, producer, or gate changes.

Source SHA256 (before → after):
- Component: `3f8680037a21804b641cf64fe2a22155a8a1afe52edae36b9ef08d91bafcede6` → `7a1eacbe709d38071107e116cdc81be8eed3659e5eaf9ca294273c1f88127e33`.
- Spec: `e2d4a98d11026a23378e30a0cba53162f163f8fc6bb6d3595bdaca2e0845a77f` → `f7043f8dc1ef94da3efdf2a106241b25ac0e54ca4cb0498165b0271637a596d3`.

Validation in canonical web dependency environment: component Vitest 8/8 passed; Vite build passed. Broader ReviewView run has one existing failure expecting `3/20` from an invalid fixture; reproduced against the preserved pre-change component in an isolated baseline. No unrelated test was changed. Main assistant checks only; independent REVIEWED / TESTED / BEHAVIOR_VERIFIED: NOT_RUN under this task's direct-execution constraint.

DEPLOYED: API-only release `close-union-label-api-20261014-r1` at 2026-10-14T17:37:54+08:00, root `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/close-union-label-api-20261014-r1/app`. Manifest SHA256 `48db403b12cc96cdb8852baf414d79c1ff1aea5ee99290dd04bede0d49044d5e`; release identity validation passed.

API_VERIFIED: `/api/v3/review?date=20261014` HK payload exactly equals the pre-deployment payload. Formal union remains unconfirmed; observation union remains 27 stocks / 7 Top20 hits. Research-only and all trading gates remain unchanged.

UI_VERIFIED: reloaded the actual user tab on 8873, opened the existing 16:10 close-review entry, and verified the rendered card text above. Screenshot and API before/after receipts are local under `/Users/lexi/Desktop/学习/agents调试/V4_CLOSE_UNION_LABEL_20261014`. No new natural-slot claim is made for this display change.
