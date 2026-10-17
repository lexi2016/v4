GOAL: One-pass read-only audit of PDFs newly ingested on 2026-10-17 and 2026-10-18 Asia/Shanghai, with older backlog separately stated; verify automatic long-PDF batch continuation, failures and accumulation using existing results.
WRITER: None for business code. Root owns evidence handoff and authorized private GitHub evidence-only sync if abnormalities exist.
REVIEWER: Independent Luna Max reviewer; owns bounded read-only operational diagnosis and sanitized evidence receipt.
ALLOWED_PATHS: This evidence directory only for audit scripts, frozen metadata snapshots, receipts and repair prompt. Existing runtime/source/data/API/logs read-only.
FORBIDDEN_PATHS: No business source/config edits, no OCR/download/producer/queue triggering, no service changes, no live index/artifact edits, no repeated status polling, no raw PDF/OCR/auth/account data upload.
PASS_SIGNAL: Single captured dated inventory reconciled against existing source-run references; status/age summary and long-document continuation evidence; API/UI corroboration; abnormalities isolated and private GitHub evidence+repair prompt if needed.
STOP_RULE: Reuse unchanged prior 89-page acceptance. Missing/unbound evidence is CANNOT_CONFIRM. Healthy backlog not automatically called failed. No repair in this audit.
