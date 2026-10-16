# Announcement saved partial publication — R7

A late runner failure left completed validated announcements invisible because no result artifact was indexed. This change publishes a PARTIAL result from already validated saved outputs while preserving the failed job and unfinished work. Future runner failures use the same existing publication path. The completed failed job was materialized once without inference or queue changes.

The live 20261016 page now displays 26 research candidate stocks, including 11 from the current batch. Its current-version article accounting is 129 succeeded, 8 failed, 0 normal pending. The original job remains FAILED with INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT. Long-body repairs and synthesis remain incomplete; the full 354-article workflow is not complete. Candidate semantic review is unchanged.

## Reproduction and provenance

Source root: /Users/lexi/Desktop/学习/v4_app. Apply source-delta.patch only to files matching file-shas.json. Base handoff commit: 5ad3d50df8cc5fafba24baaab4fb375887076628. Exact runtime baseline is the local R6 immutable release, not a generic GitHub checkout. Live release: announcement-partial-api-20261016-r7b. Manifest and source hashes are recorded separately. The one-shot publication script is bound to the already-published job and refuses an existing result; it is evidence, not a recurring launcher.

## Validation

Independent checks: 47 focused Python tests and 2 announcement component tests passed; real saved-input isolated replay produced 26 stocks with zero queue dispatch/model/key calls. Type repair preserved active industry definitions. Isolated Vite build passed. Full typecheck still reports unrelated project errors; no manager-workbench diagnostics remain.

Live publication retained the failed job, indexed PARTIAL, and preserved original queue/input/progress bytes. API and reloaded UI show 26 stocks and the failure. This is manual saved-result publication, not a successful full batch or a natural scheduled-run acceptance.

Only necessary source/test delta, file hashes, the bounded publication entrypoint, and compact results are included. No raw announcements, queue outputs, credentials, runtime datasets, node_modules, or dist are uploaded. No merge was performed.
