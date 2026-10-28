# PDF research tools and finite completion

This change extends the existing local PDF research producer. It keeps the pinned simple-profile request at `tools=[]`; the model selects a bounded JSON action and the application executes page reads, whole-input PDF search, or `Decimal` arithmetic before the next model turn. Synthesis remains tool-free. A narrow HTTPS fetch helper checks official-domain scope, public DNS/IP constraints and every redirect hop, with bounded response size and no PDF text sent outside the machine.

The finite dispatcher now also contains one generic prefill-memory recovery path. It accepts only an exact frozen-document failure chain bound to the prior plan, progress, receipt, page input, queue item, request, stream receipt, raw SSE and the original authorized settings. It waits up to 15 minutes for either at least 1 GiB more available RAM or at least 512 MiB less used swap, with the threshold present in two consecutive five-second samples. Only then may it submit one generation-one recovery through the existing batch runner and shared lock. Existing successful chunks are recovered by the batch runner’s prior-queue validation and reused; a second document failure is isolated so the dispatcher can advance to unrelated work. Timeout, missing measurements or unsupported failure evidence skip recovery and preserve the failure.

## Runtime and scope

The frozen source cohort has 2,209 unique documents. Current reconciled status is 90 complete, 2 isolated failures, 59 `FAILED_NO_RETRY`, 7 source-repair failures, and 2,051 unprocessed. One unprocessed document is quarantined, leaving 2,050 runnable. These are pre-bulk counts; the remaining cohort has not been started by this writer.

The canary/recovery requests used local model settings SHA-256 `0da2c9d1044a1d86ac0037f06859248568ba82a03f1a26a17699c64b12e9c7c7` and runtime settings SHA-256 `e05af04aa712ee134354a8c0fa97812761cee7d1304b3914c87b6a8636b22a99`. The executable identity for the finite run is `/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python`, Python 3.12.13. After root integrates these exact bytes and refreshes the existing authorization’s code hashes, the single operator command is:

```sh
cd /Users/lexi/Desktop/学习/v4_app
/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python \
  -m ops.run_pdf_research_remaining_once --execute
```

The dispatcher enforces the existing authorization ceiling and cohort inventory. The remaining run uses the versioned evidence root `/Users/lexi/Desktop/学习/agents调试/V4_PDF_TOOL_ENABLED_COMPLETION_20261019_R1/remaining-execution-r1`; the earlier `resume-writer` journal is preserved because it is bound to prior code and has stop history. Root owns integration, authorization-hash refresh and run start. The existing authorization must be refreshed to the final dispatcher and runner hashes before execution; the dispatcher fails closed while either binding is stale.

At startup, the 142 original progress rows are compared with their statuses in the frozen inventory. Exact validated canary receipts may advance the live selection status without changing that historical comparison. The status loader preserves both views so completed canaries are excluded while historical source consistency remains checked.

## Canary evidence

The frozen inventory SHA-256 is `58c94d2899e02a17df46e2e3c9ed9e65ad7aa5e19194e7046c849fbe929a7dad`. The local-tools canary is document `fc551b8057828fc161d7efc134701242b43e9b95177c62e4fb6f625ec93b789b`, plan SHA-256 `40cab1194bd19d3caa5b54f4d9129fd8903c770d0cdc13f5f708b4b623e2f2d5`, page-input SHA-256 `2408358e4ae95ff5e31dc296f1f24722ccd60870a3836d75bf07107f2d22be2e`, report SHA-256 `d521155a327dec9d0013acd66894160b7a744e401403959e1b637e4916e15fe0`, and document receipt SHA-256 `cfd15fc9c0b47abbaa8c966b6047da991034c062e059c2394e51cc2518e0d6ab`. One local model request and one queue attempt executed PDF search/read and arithmetic; the ratio calculation matched the source after rounding. Independent review passed local content/tools. External search returned `WEB_SEARCH_UNAVAILABLE`; the replacement route diagnostic returned `provider_unavailable`, so actual official search-to-fetch behavior remains `CANNOT_CONFIRM` and no external supplement is claimed.

Three additional unfinished documents were frozen before inference in plan `writer/actual-three-document-canary/continuation-plan.json`, SHA-256 `393665466e50d74effefdbd6ea8e2f0b187baa1f342f5ef73de7999380866888`. Each prior status was `UNPROCESSED`; the set included a two-chunk, ten-page document. The successful source reports have these immutable producer receipts:

- Export report: `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/continuation-three-document-canary-20261019-r1/documents/8a8e06be978f10311bfdff6e6a17b6d49bce6c5db29400e88c4df014bd5558aa/receipt.json`, SHA-256 `925fbe8fc3d01bb9886f067f68dd662e4f16cca937504e1cb985712fe1231ea6`. Independent review found one distribution-label error; the separate corrected derivative is `reviewed-report-r1.md`, SHA-256 `36163d033b1968f18bd57afa480ab97e5a191f8ca0e27252b4c409e5b7c8bcc8`, bound by erratum SHA-256 `ddec2631c6001d982e2700eb9b3d7b8062a6dbb192ad97ed5fd2638abe62cd5f` and physical page 5 evidence. Original report and receipt remain unchanged.
- PPI report after one partial-chunk recovery: `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/recovery-039fa67f32522085560d4c6032850a54d39612fdc2a1c6d12aae1925227428a1/documents/6892ef7be8071665aa96fdf125a4a1acac8367f3f7eb3a772e84fd121b9fd87b/receipt.json`, SHA-256 `03ff49b9eef8867d73acac1b808979bfe2cb0dc94d09b89080a6169bbe6246be`. The independent-review derivative corrects only the citation on line 46 to physical page 2, SHA-256 `e282b9fbebeb2117106616daa6363b97067359dc8ac8b66c55ec3c3232fe28c3`; erratum SHA-256 `7811e8df51ac57b84356c3c854478c9c0e12b5f58d7ab79a0d70559aca9547a3`. The original model report and successful first chunk remain preserved.
- AI-video report after one generic memory recovery: `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/external_sources/zsxq_hourly/pdf_local/research/batches/recovery-2c2e7b6aa372bc32abcb482043688cdd02feff3505d0f678c49efb171c467fc3/documents/eeed6e4916c2a8b44d0f3911d9303de754e6164d8d33cc7f11f4c15dae9f49a5/receipt.json`, SHA-256 `36b029d65106a748ca19e5cdd8fa0ed61717efd7a66a3ae0b3eec84e8f215276`. The separately reviewed derivative changes only the date distinction on line 5, SHA-256 `33237f6226c5874cf56235fe6a037e3d53f6d6156fb5d6b14cd0a7ca9e2000f5`; publication date remains `CANNOT_CONFIRM`. Its erratum SHA-256 is `d4a3ece43a21a384695e72eeaa3a64b2fc34b276d4bb1f9d2aeba079889b5b72`; evidence binds physical pages 1 and 2. Original report and failed first-attempt receipt remain unchanged.

Independent content review closed all three follow-on reports on their corrected derivatives. Producer statuses remain `MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING`; review acceptance does not mark those records user-accepted. The AI-video prior failed attempt is separately bound to one exact `prefill_memory_exceeded` SSE response, and its recovery used the same page-input SHA. PPI preserved and reused its successful first chunk byte-identically.

## Verification and unresolved evidence

Using pinned Python 3.12.13 and test dependencies at `/tmp/v4_pdf_tools_testdeps`, the final dispatcher test command after the historical-status guard change passed 27 tests:

```sh
PYTHONPATH=/tmp/v4_pdf_tools_testdeps:. \
  /Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next/runtime/venv/bin/python \
  -m pytest -q --basetemp=/tmp/v4-pdf-original-progress-fix \
  tests/test_pdf_research_remaining_once.py
```

This run includes exact reconstruction of the frozen AI-video recovery plan from the bound failure chain, stable resource-change gating, one-retry isolation, next-document continuation, acceptance of an exact receipt-bound status advance, and rejection of a mismatch between original progress and frozen inventory before a child can start. `py_compile` and `git diff --check` passed for the changed dispatcher and test. A preceding focused run of the dispatcher and batch modules passed 84 tests before this last guard change; it is not counted as a run of the final test bytes. The reviewer-readable final source patch and 9-path SHA manifest are stored beside this document as `writer/implementation-diff.patch` and `writer/implementation-diff-manifest.json`. Final source-code review and real-input, no-model startup preflight remain pending; dispatcher tests themselves made no model or service call.

Actual official-source search-to-fetch remains `CANNOT_CONFIRM` because the configured provider was unavailable. Future document-specific lookup gaps must remain explicit unknowns. Remaining queue execution and final unresolved-record accounting are owned by the root operator; no completion claim is made here.
