# Public framework code map and maintenance SOP — pending increment

Scope: the sanitized framework source manifest supplied with this same package. Known base commit is `34c353cc1ba4ae0d02fbf36bc6158f38ff17fe10`, but the new source commit is not yet assigned. It is intentionally `null`, not invented. Exact source identity is per-file SHA256 plus source_digest.

Status: **VISUAL_QA_BLOCKED_NOT_DEPLOYED**. Source tests and public content review do not authorize or certify a production release.

- `graph.json`: static imports/global references/SQL candidates and unknowns.
- `MAP.md`: module graph and source SHA/line index.
- `impact_examples.json`: reverse static dependencies, not runtime coverage.
- `OPERATIONS.md`: non-sensitive engineering diagnosis/test/release/backup SOP.
- `SOURCE_VERSION.json` and `PUBLIC_MANIFEST.json`: exact byte and version bindings.

Install this add-on at `research/dashboard_framework_collab_20261030/docs/code-map/`. Relative links such as `../../shell/workbench.mjs#L1` resolve to source in the same eventual commit, not to the older base. No private runtime graph, source data, real user schedule, Drive identity or internal SOP is included.

## Built-ins-only inspection
```
node --test inspect-map.test.mjs
node inspect-map.mjs impact shell/workbench.mjs
node inspect-map.mjs check /path/to/authorized/public/framework-package
```
The checker reads only exact indexed paths within the explicit public root, rejects symlinks/unsafe paths, bounds input and compares source hashes. It does not execute source or access network. It detects changes/deletions of indexed sources, **not newly added unindexed files**. New source files require graph regeneration from the updated sanitized source manifest. A matching indexed-file check is not full-tree freshness or runtime proof.
