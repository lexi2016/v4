The related-report reader and cursor already require verified PDF SHA/size and
page byte size, but the original owner omitted them from its public detail.
Root authorized the exact canonical return-value addition in
`report_index_0300/RELATED_API_REPAIR_SCOPE.json`.

Only three owner lines were added: processing verified PDF size, processing
verified page byte size, and receipt verified PDF SHA. Values are produced only
after the unchanged owner verifier has checked source binding, receipt fields,
PDF bytes/size, page file SHA, per-page text SHA, coverage, and safety flags.
`verify_pdf=False` returns null for both PDF fields; page size is the exact
already-read and hash-verified byte length. No consumer, cursor, or index code
was changed. Prior independent PASS scopes remain intact.

`OWNER_THREE_FIELDS.patch` contains exactly those three inserted lines relative
to this round's prior dirty owner bytes. It was actually applied to an isolated
copy of that preimage and produced byte-for-byte equality with the final owner.
Use this patch for recovery/source backup; do not stage the unrelated whole
dirty ingestion diff. `RECOVERY.json` contains pre/post/patch SHA and commands.

Five targeted test methods were executed incrementally. The initial four
passed with six subtests; adding metadata mismatch and a prior-receipt-change
case required only the two affected methods, which passed with seven subtests.
Temporary synthetic fixtures execute the real owner verifier and public reader;
only inventory loading and the upstream source resolver are isolated. PDF/page
tampering, source failures, index metadata mismatch, prior receipt/PDF/page/source
changes, and unverified PDF metadata remain rejected. Normal first/next pages
retain true text evidence and revalidate prior sources.

`probe_one_real_detail.py` read one exact already-indexed document from Root's
failed API page through the real public owner, checked its metadata against its
existing derived entry, then passed that detail to the unchanged relation
reader. It verified one document with no contract error. This specific document
has no matching text for any of the three requested stock names/codes, so the
result honestly contains no reports. See `ONE_REAL_DETAIL_RESULT.json`; it is a
bounded candidate probe, not Root's full three-stock API acceptance.

No raw/source/derived index writes, 237-source repair or retry, services, GUI,
reindex, deployment, commit or push occurred. Independent hunk review and Root's
real three-stock API acceptance are pending.
