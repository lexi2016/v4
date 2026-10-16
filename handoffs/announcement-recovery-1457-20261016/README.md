# Automatic announcement batch recovery — 2026-10-16

This bounded patch repairs verified source-body cache reuse, HK Connect-only model admission, continuation of eligible unattempted pending items, and lossless long-body processing in the existing manager workbench.

The patch includes nine source/test files. Apply it only to the exact per-file baseline hashes in `file-shas.json`; the baseline is the active r7 release listed there, not a claim that this handoff repository is a standalone source checkout. `git apply --check` passed against an isolated copy of those baseline files.

The deployed r5 candidate passed independent review and 38 focused tests. Independent read-only validation used the actual saved input: 757 captured rows, 354 eligible body bindings, including 86 restored bodies. The real failed child resolves to the original 14:57 parent, and altered body hashes/content are rejected.

One existing page button click started the live continuation at 17:55. It progressed automatically into model processing. The batch was still running at the last observation; the user asked to stop reading progress and will notify when it ends. Completion, full pending-item accounting, long-body synthesis, final semantic acceptance, and final API/UI readback are not claimed. Earlier actual failures and their fixes remain recorded in `result.json`.

Research only. No BUY changes or orders. Raw announcements, model outputs, live queues, configuration, authentication material, service plists and built assets are excluded.
