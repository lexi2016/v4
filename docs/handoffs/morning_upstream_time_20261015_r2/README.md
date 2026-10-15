# Morning upstream capture-time repair — 2026-10-15 R2

## Root cause

The active single-owner collector never recorded a successful article HTTP response completion time. Its `_published` helper selected the first naive date anywhere in the HTML, which could read body/comment dates and discard an offset. The scheduler skips collection when an exact-date artifact already exists. Its rewritten `generated_at` describes the job/duplicate check, not an article acquisition event. The publisher and gateway reader preserve article fields; they did not cause this data loss. The legacy normalizer is not on the active collection path and was deliberately left unchanged.

The official article response contains a naive `window.__NUXT__.data[0].data.create_time`. Its `serverTime` is the page-response server clock, not article publication time. No publication timezone evidence was found in the inspected official response; the repair does not assume Asia/Shanghai.

## Implementation and runtime

Only the collector and its focused test file changed. A successful article body read now records UTC `fetched_at`, linked to its URL and existing response-text SHA contract. Publication parsing is restricted to the URL/route-bound main article and retains raw source evidence; explicit offset/epoch values can be represented as aware time, while naive values remain `TIMEZONE_UNKNOWN`. No publication timestamp, file mtime, scheduler receipt time, or refresh time is substituted for historical capture time.

The actual scheduler owner was the independent `hk-auto-shared-20261011-r1` shared package, not the main scheduler app's bundled copy. The new immutable `morning-upstream-time-20261015-r2` package preserves 79 non-target inventory entries and changes only the collector. Activation changes only `V35_SHARED_PACKAGE_ROOT`; scheduler schedules/framework/app identity, API process/config, historical artifacts and safety gates stay unchanged. The live process argument was read back and matches the new owner.

## Acceptance

Independent Luna Max Reviewer: PASS with no P0/P1/P2 findings. Candidate tests: 18/18. A real official-site HTTP canary collected three articles during 06:53:48–06:53:54 UTC. Each `fetched_at` falls inside that observed interval. Publish/read in an isolated store and the actual gateway reader retain the exact article fields. This is a manual canary, not a natural morning run or a replacement for the historical production artifact.

Production latest pointer plus payload/manifest/receipt hashes remain unchanged. The exact-date API still returns the original 20261015 morning content, so its missing historical capture timestamps remain visible. Future new-date collections use the repaired owner. No existing slot was overwritten, and no timezone was invented. Natural scheduled verification remains NOT_RUN.

The remote research base did not contain these upstream paths; this branch adds only the changed collector/test and this bounded receipt, rather than uploading a full runtime copy. No raw HTML, article bodies, live artifacts, credentials, virtualenv, dependencies or compiled assets are included. See `receipt.json` for identities and verification boundaries.
