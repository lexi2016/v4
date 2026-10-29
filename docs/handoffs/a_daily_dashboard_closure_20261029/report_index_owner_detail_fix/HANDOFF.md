The original owner's three exact document details are READY and report
`SOURCE_PDF_AND_PAGE_HASHES_VERIFIED`, but deliberately return only a receipt
reference. They do not expose the three duplicated hash/size fields that the
derived adapter required. `REAL_OWNER_SHAPES.json` records the actual responses'
metadata without PDF/page contents.

The adapter still calls the same owner with `verify_pdf=True`. It now reads PDF
SHA/size from that exact verified latest engine artifact, then securely reads
the artifact's page bytes and compares their SHA before recording their exact
length. No owner/source/PDF/receipt validation was removed or fabricated.

Only `infrastructure/zsxq_pdf_search_index.py` changed; three focused tests were
added in `tests/test_pdf_search_index.py`. All three passed. Negative cases keep
PDF/page/source owner errors, post-verification page SHA drift, and incomplete
owner verification fail closed without a Bloom record. Previous 3P2 PASS was
reused. No shared index/source writes, OCR, download, services, deployment or Git
actions were performed by the Writer.

`RECEIPT.json` contains exact commands/hashes and the isolated pytest cleanup
exception from unrelated old pytest garbage. The dedicated local fixture root
was removed after PASS. `INCREMENTAL.diff` is the complete source delta.

Root owns the one real replay. Use the existing helper once with frozen
`report_index_0300/CANARY_INPUTS.json` and a fresh output directory such as
`report_index_0300/canary_after_owner_detail_fix`; do not reuse the original
canary's completed progress file. Require all three batch statuses READY and all
three per-document statuses INDEXED before the 608-batch run. The previous
failed canary remains unchanged. Writer's fixture PASS is not real replay PASS.

Independent incremental review and Root's real three-document canary remain
pending. No full library materialization or UI/report completeness is claimed.
