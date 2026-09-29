# Isolated Stage A UI tests

This directory is not a new application, deployment or production dependency manifest.
Never replace apps/web/package.json or its lockfile with these files.

Executed by the code author: `node --test tests/wechat_ui/client.test.cjs` from V4 root,
which invokes the installed TypeScript compiler on the actual TS client and mocks only HTTP.

Not executed here: Vue mount/jsdom tests. The supplied V4 snapshot omits apps/web/package.json,
its lockfile, Vue, the existing lane API and multiple legacy components. The environment has no
Vue/Vitest and npm DNS access failed. The test manifest fixes direct harness versions but no
transitive lock was generated; this is not a reproducible full V4 dependency closure.

On the integration host, first prefer the existing app's approved test tooling/version. Otherwise
review this isolated dev manifest, `cd tests/wechat_ui && npm install && npm test`.
Review the produced lockfile; do not upgrade production Vue based on this harness.

Fixtures list.json/detail.json were produced by the real new reader using the supplied
report_original.md and legacy receipt in a temporary archive. Their indexed_at is the author's
isolated test time, NOT an actual V4 import/production availability event. They are display
contract fixtures, not a second authoritative archive. The same original text is never treated
as independently verified research.

The full ResearchView/legacy lane and a real browser still require V4's missing dependency
closure and a separately authorized local check. jsdom passing would not itself prove those.
