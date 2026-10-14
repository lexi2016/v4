---
name: local-omlx-announcement-debug
description: "Debug local oMLX Flash announcement runs: launch/runtime drift, streamed failures, and source-safe recovery. Not for canonical V4 changes or model-answer editing."
---

# Local oMLX announcement debugging

Use this skill for local Flash announcement-analysis failures or performance questions. Keep host-specific history separate from the state observed in the current run; read [references/local-profile.md](references/local-profile.md) only when working on that Mac profile.

First identify four distinct layers: the live process and model, the exact launcher command, the saved settings, and the runtime settings reported by the local API. A CLI flag can override and persist over a UI/API setting, so inspect the real launch path before changing settings. Treat a saved value as different from a confirmed runtime readback.

For a failed request, inspect the first raw stream or response and preserve its exact error code, request identity, and raw SHA. Separate transport/runtime failures from announcement-level semantic or validation failures. A shared system failure such as a prefill-memory rejection should stop remaining queued work and retain it as unrun; do not blindly retry the batch. After a bounded fix, resume with one real, visible local request before continuing. A semantic failure can be isolated per item, but keep the original source, request, and model output immutable; never rewrite an answer or weaken a gate to obtain a pass.

Keep the task division explicit: deterministic code owns source identity, deduplication, fixed fields, arithmetic, and lossless chunk boundaries; Flash reads the captured announcement and makes the business judgment. A prefilter may isolate clearly routine low-value notices or malformed/source-deficient items; retain risk notices, corporate actions, and unclassified items for model review. A missing body means incomplete source, not no research value. Do not prepare human summaries, answer keys, or expected judgments for model input. If a source is too long, chunk it by exact source units or byte ranges, prove full coverage and reconstruction SHA, retain global unit references, and aggregate only after every chunk succeeds. Label partial work as partial.

When an actual model run is authorized, use the visible in-app browser path and verify the requested `model_id`; keep the existing Qwen 27B baseline available. Measure the complete request path—prefill, first content, generation, validation, and end-to-end time. Low CPU use or a full cache-capacity indicator alone does not show whether a run is efficient or all model weights are resident. Compare the same frozen inputs and concurrency, and use modest resource snapshots rather than inferring from a single utilization reading.

Preserve provenance gaps: complete mirror text does not prove that official attachments or publication-time data are complete. When source research is authorized and a consequential fact is missing, check the official source and record that evidence separately from the captured announcement. Keep unknowns explicit, retain source quotes and hashes, and keep announcement research separate from automated trading. The skill does not authorize settings changes, service operations, external collection, or model requests; obtain the task's current authorization before those actions.
