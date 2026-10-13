---
name: baimao-feed
description: Capture and normalize public Baimao/白毛/Serenity signals from user-provided WeChat or X links, local archives, images, OCR, and outbound sources. For a WeChat link, the default route is local capture/OCR/package, grounded Drive-first article handoff with START_HERE, user-submitted Chat research, exact raw-byte return, Codex local archive and Drive mirror; a bounded direct-file handoff is only a fallback. Explicit LEGACY_FULL_RESEARCH is required for V3 publication or legacy API/UI verification. Do not perform chokepoint ranking.
---

# Baimao Feed

## Contract

- Capture public/read-only evidence; never post, react, modify accounts, copy credentials, inspect
  hidden browser state, send Chat messages, or operate a browser on the user's behalf.
- Start with the exact URL, local run, manifest, or archive named by the user.
- Preserve the last good archive when a refresh or handoff fails.
- Never invent inaccessible posts, missing images, OCR text, timestamps, entity mappings, Drive IDs,
  provider revisions, or download hashes.
- Reuse the existing fetch/OCR/package/import path. Do not create a second fetcher, OCR producer,
  research coverage producer, Drive client, or background monitor.
- Keep the public-account all-mentions pool, Chat research output, Baimao shortlist, and any formal
  pool as separate artifacts. Never replace one with another.
- New frozen packages bind `review_contract_version=wechat-event-dispositions-v1` into both
  `manifest.json` and `input_descriptor/input_digest`. For a trusted frozen ZIP, the importer
  requires the return summary to repeat that version and its `event_dispositions` object to map each coverage `EVENT` `source_index`
  exactly once to `PROMOTE`, `HOLD`, `REJECT`, or `CANNOT_CONFIRM`; `NO_EVENT`, `UNREADABLE`,
  duplicate, missing, or unknown indices fail this structural check. The receipt reports the check
  separately from semantic review. Older v2 packages without the field remain importable and report
  `NOT_RUN_LEGACY_PACKAGE`.
- The maintained commands and precise frozen/return receipt schema live in
  `WORKFLOW_公众号链接固定执行方案.md` sections 0.1, 0.2, 0.5 and 0.6 and in
  `templates/chat_research_prompt.md`. Keep this skill and its references at the responsibility and
  state level; do not add a second command, receipt schema or producer.

## Default WeChat route: local package → Drive-first handoff → user Chat → Codex archive + Drive mirror

For a raw WeChat URL, the default route is:

```text
resume/identity check → fetch → OCR canary → OCR only missing items
→ package(BODY/OCR_FULL/original manifest/original images/README/PROMPT/ZIP)
→ ground Drive root/article folder (01_资料包/02_Chat回传/03_本地复核)
→ START_HERE + short prompt → user submits Chat once
→ exact raw-byte return → local import/light checks → Drive mirror
→ V4 Stage A reference → exact article-date API/UI archive display
  (authorized, not automatic re-research)
```

Drive is the default handoff and return-mirror route. Direct files are a bounded fallback only when
the current Drive tool is unavailable or its bounded diagnosis fails; they are not the default and
the user is not asked to upload the frozen package again. This skill documents the route; it does
not imply that a Drive connector or an automatic transport system exists. If Chat has no Drive write
tool, Chat/the user returns the exact files to Codex, and Codex uploads them after obtaining real
metadata and byte receipts. No successful receipt means no claim of a Drive write.

After local and Drive archive receipts pass, an explicitly authorized research-archive-display step
registers the existing archive as a V4 Stage A reference and verifies the exact article-date API and
UI report. This is a controlled read-only reference, not `LEGACY_FULL_RESEARCH`, a candidate/score,
a formal pool, or a BUY gate; daily new articles do not require a restart.

For every default Drive/Chat handoff, also attach a separate prior-article performance appendix when
a trusted archived `mentions.csv` can be bound to its receipt. Select the article by timezone-aware
`published_at` and real article date; yesterday is the default, and a no-article-yesterday fallback
must show its actual older article date and must not be called yesterday. Before reading prices, record
the currently loaded scheduler configuration and resolve the configured pointer, exact-date rows, and
same-date receipt/manifest in that order. A directory name containing `v35` does not prove that
source is stale, and a file missing from an unrelated older directory does not prove global data
absence. For A/BJ, match the configured selector pointer target to the exact-date receipt SHA and
validate each listing's date, code, market type, close, pre_close, and pct_chg. A PARTIAL lane receipt
may still support individual reconciled rows; disclose its denominator and authority status, and mark
each missing or unreconciled code CANNOT_CONFIRM. For HK, read the configured asset panel through its
exact-date receipt and manifest, verify actual and linked panel SHAs, and derive the previous HK
session from the market calendar. Use the previous-session close only when it matches both the current
panel's pre_close and the parent panel's close. If corporate-action/adjustment evidence is absent,
describe the raw unadjusted price move, excluding dividends, and do not call it the official daily
change or total return. Include every unique `(market, listing_code)` from archived mentions, grouped
as A/BJ/HK; an intraday value must carry an exact timezone-aware `as_of` and source. The appendix
is descriptive price movement, not strategy return. Keep gaps as `CANNOT_CONFIRM`, retain source
receipts, and do not add another price producer or fallback data source. Keep the appendix outside
the frozen package and bind both the prior archive identity and current package/input_digest. Place
it after the Chapter 1 conclusion as an unnumbered subsection; do not change the nine-chapter report.
Use `scripts/wechat_yesterday_performance.py appendix`; keep the old V3 observation-pool command
inside the explicitly selected `LEGACY_FULL_RESEARCH` route.

`package` is complete when the exact article identity, original image order/count/bytes and
non-empty OCR checkpoint are verified. A verified text-only article may omit OCR only when BODY is non-empty, the image manifest and directory both confirm zero images, and OCR is explicitly `OCR_NOT_APPLICABLE`; this exception does not relax the OCR gate for any image source. A local source-coverage ledger is not a default package
prerequisite. Chat owns research coverage after the user submits the package; a source that Chat
cannot open must be listed by source/image ID as `UNREADABLE` or `CANNOT_CONFIRM`. A Chat claim,
"已读" statement, OCR count, or report heading does not prove local semantic research.

Read `references/archive-contract.md` and
`references/drive-chat-handoff.md` before writing a durable archive or using the Drive route.

### Source identity and date

Persist the exact URL, title, account name, timezone-aware `published_at`, `biz`, article content or
intake hash, `article_publish_date/signal_date`, complete input_digest over BODY/OCR/original images/order, manifest SHA-256, external package ZIP SHA-256, and image
count before transport. A date, title, filename, or folder name is not an article identity. Keep
`article_publish_date/signal_date`, `selector_score_date`, and `effective_trade_date` separate;
the selector/V3 fields are not part of the default route.
For return recovery, read the report binding header and summary identity first and match
`package_id`, `input_digest`, `return_id`, URL, and article date to the frozen package. Do not pair by
the most recent Chat session or newest file. Resolve count conflicts such as 90 versus 58 by checking
identity before interpreting the difference. Obtain all five original return files; archive new
return IDs or changed bytes as immutable versions.

### OCR and package boundary

1. Inspect the exact URL and resumable local run before fetching again.
2. Capture the body and every source image only when missing. A cached successful canary is reusable; run only missing OCR
   items. Reuse matching successful OCR; do not restart it because Chat needs research coverage.
3. Check image order, count, original bytes/SHA-256, and non-empty OCR checkpoints. `OCR_FULL.md`
   is a machine transcript/index, not semantic verification.
4. Package the frozen artifacts through the existing package entry point. Preserve a package receipt
   with source binding and hashes. A package may be handed off without `coverage.csv` or a stock
   pool.

Do not treat image download, OCR success, a contact sheet, or a shortlist as research completion.
Do not silently publish a shortlist as an all-mentions pool.

### Drive and return boundary

Ground the intended Drive root, article folder, and exact `01_资料包`, `02_Chat回传`, and
`03_本地复核` folders with a recorded `grounding_id` and provider IDs. The currently known root
candidate is `1-PbGAtNO3Vu_b-YHjHlOfrKvrKiodNNG`; use it only as a metadata lookup hint, never as a
global article-folder identity. Use metadata-first bounded pagination and record
provider `file_id`, version/etag when exposed, `modifiedTime`, size, and provider MD5. Provider MD5
and local SHA-256 are different fields and are not directly comparable. Skip content only for the
same already verified provider revision; otherwise download exact non-native MD/CSV/JSON/ZIP bytes,
hash locally, and keep every changed version. A missing metadata field prevents a safe duplicate
skip. Do not share files or change permissions.

For transport, record `raw_bytes_obtained`, `observed_sha256`, `expected_sha256` and `hash_match` separately. Hash computation alone is not a comparison against a trusted source.
Give the user one verified Drive `START_HERE` link and the short research prompt. If a package ZIP
upload exceeds 60 seconds, first query the target for an existing result; only when absent use
independent small ZIPs (the current example succeeded at about 2–3.5 MB each), never a split-volume
ZIP and never a new OCR run. Record the original `input_digest` and package SHA plus each part's
`members_sha256`; a part hash never replaces the original package identity. A returned Chat
attachment is not evidence of a Drive byte round trip.

The lifecycle states are independent:

```text
UPLOADED_METADATA_VERIFIED
RAW_BYTES_OBTAINED
HASH_COMPUTED
TRUSTED_HASH_MATCH
# Compatibility state for older consumers; emit only when the two states above are true.
DOWNLOADED_HASH_VERIFIED
CHAT_READ_UNVERIFIED
LOCAL_ARCHIVED
REPORT_ONLY_ARCHIVED
REPORT_AND_STRUCTURED_ARCHIVED
RESEARCH_VERIFIED
```

`RAW_BYTES_OBTAINED` means the exact returned bytes were obtained and retained. `HASH_COMPUTED`
means a local SHA-256 was computed and recorded; it does not establish provenance. Set
`TRUSTED_HASH_MATCH` only when the expected hash is bound to a trusted provider file identity or
revision and the observed bytes match that expected hash. For consumers that still read the older
`DOWNLOADED_HASH_VERIFIED` state, map it only from `TRUSTED_HASH_MATCH` plus the provider identity
and expected-hash binding. A locally computed hash without that binding must never be promoted to
`DOWNLOADED_HASH_VERIFIED`.

Metadata, bytes, hash, Chat reading, structure, and semantic review are independent acceptance
layers; one receipt never upgrades another. `UPLOADED_METADATA_VERIFIED` proves provider metadata
only, while `REPORT_AND_STRUCTURED_ARCHIVED` is a structure state and not semantic research.

`REPORT_ONLY_ARCHIVED` is valid when the report bytes are present and named structured returns are
missing; list each missing file and never fabricate it. Non-empty invalid returns remain archived
as bytes with a weaker partial/invalid state. A remote source-binding or provider-revision mismatch
is `REMOTE_BINDING_MISMATCH`, not a canonical result. The Drive reference defines the runtime
`file_uri` schema gap, bounded checkpoint retries, no blind duplicate upload, and the Codex exact-file
return fallback. It never pretends that a connector exists or that a 403 download succeeded.

`REPORT_AND_STRUCTURED_ARCHIVED` means the report and all four named structured returns were archived
as original bytes and passed bounded syntax/identity checks. It is a structure-archive state, not a
research pass or proof of complete visual coverage.

For future new articles, run the existing importer with `--archive-frozen-input`; after trusted ZIP
identity verification it preserves every original ZIP member byte-for-byte, in original order, under
that return's `frozen_input/` directory and emits an extraction receipt plus explicit import-receipt
references. A failed trust, source, or structure check keeps the returned raw bytes and a blocker and
cannot claim the complete standard. `IMPORT_RECEIPT.binding` also carries `account`, `biz`,
`published_at`, and the observed SHA-256 of the original `manifest.json` member. Register those new
receipts with V4 `--require-frozen-input`; V4 verifies the explicit receipt references and every
descriptor source before writing an index record. The optional `--manifest` path remains a legacy
compatibility input and cannot bypass strict receipt binding. `PARTIAL` research may be archived and
displayed when its files and bindings pass, but it stays semantically unaccepted and `available_at`
remains unknown. Exact commands and receipt fields remain in the workflow and prompt template above.

## Explicit `LEGACY_FULL_RESEARCH` route only

Only an explicit choice of LEGACY_FULL_RESEARCH enables the old local chain; asking for a complete report does not. Publication/API/UI additionally requires separate authorization:

1. Verify identity and full source capture.
2. Reconcile every body/image source with a one-to-one `EVENT`/`NO_EVENT` ledger; retry only known
   OCR failures and preserve checkpoints.
3. Extract all A/BJ/HK mentions separately from the Baimao research pool.
4. Build and date-match the public-account V3 artifact using the article date, then perform the
   separately authorized API/UI checks.
5. Hand the ordered source and coverage ledger to `baimao-method` for the full nine-chapter report.

The legacy route must retain `RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE`; it never authorizes a BUY
gate, order, trading account action, service restart, or scheduled task change. Exact-date V3/page
fallback to `latest` is forbidden. If the article-day selector is missing, keep V3/API/UI
`CANNOT_CONFIRM`.

## Acceptance layers and states

Report `ARTIFACT_VALIDATED`, `LATEST_POINTER_VALIDATED`, `API_VALIDATED`, `UI_VERIFIED`, and
`NATURAL_VERIFIED` independently. In the default route, the package and local return states are
the relevant artifacts. Legacy latest/V3/API/UI and NATURAL remain `CANNOT_CONFIRM` unless the
separate explicitly authorized legacy workflow proves them. After the authorized V4 Stage A
registration, `V4_STAGE_A_API_VERIFIED` and `V4_STAGE_A_UI_VERIFIED` require the exact article-date
API query and a reloaded page showing the matching article context, report bytes and semantics;
HTTP 200, a file, a Drive upload, or a focused test is not enough.

Capture states for source records remain:

- `COMPLETE`: required local text/media/source fields captured.
- `PARTIAL`: usable record with known missing fields.
- `ACCESS_BLOCKED`: content requires access not currently available.
- `TIMEOUT_RETRYABLE`: a bounded safe retry remains.
- `FAILED_FINAL`: retry budget exhausted or source is invalid.

## Handoff to method

Return the normalized package binding, completeness metrics, OCR gaps, Drive/return receipts, and
the exact local archive paths. Archive first; hand a return to `baimao-method` only for an explicitly requested bounded review or new research. Do not re-run the full method after every import. Preserve `CHAT_READ_UNVERIFIED` until that declared review scope is actually verified. Do not decide whether a stock is a
chokepoint candidate.
