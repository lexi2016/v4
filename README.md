# V4 source review snapshot

This is the unified review entry point for this V4 source snapshot upload. The source bytes came from `/Users/lexi/Desktop/学习/v4_app`.

- Source HEAD: `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054` on `codex/system-consolidation-20260912`.
- The package includes the current working-tree bytes for selected tracked and untracked source, test, fixture, contract, documentation, and dependency files. Dirty and untracked production helpers are represented directly in the manifest.
- Working-tree status at capture: `116` tracked changed rows, `1` deleted rows, and `1051` untracked rows.
- This is a review snapshot. It does not claim that these bytes match the active deployment. Active-deploy equivalence is `CANNOT_CONFIRM`.
- No claim is made that all tests pass. This task did not run the test suite. Market-capture fixtures and runtime artifacts listed in `docs/source_snapshot_20260929/metadata/exclusions.json` are intentionally absent, including 16 excluded fixture paths.
- The payload contains 1312 source UTF-8 text files plus snapshot metadata and packaging scripts. `upload/tree_entries_*.json` stays at or below 400,000 bytes per file. Rows with one `path` are concatenated in ascending `part` order to recover that file's exact UTF-8 bytes. Each row carries `path`, `mode`, `type`, and `content`.
- `docs/source_snapshot_20260929/metadata/manifest.json` records source SHA-256 and Git blob SHA values. The source worktree had no root `README.md`; its `START_HERE.md` is included. The metadata directory also records source status, exclusions, path-only secret scan results, and the packaging scripts.
- The local package directory's `metadata/transport_index.json` records upload chunk hashes. It is uploader metadata and is not itself part of the GitHub tree, since it includes hashes of those transport chunks.

The snapshot does not contain `.git`, runtime data, local secret configuration, caches, `node_modules`, virtual environments, generated outputs, market captures, logs, or review receipts. The one deleted tracked Git link at `upstreams/review_core` is represented by its current untracked helper files, which are listed individually in the manifest.
