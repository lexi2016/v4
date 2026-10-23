# Frozen scope · 2026-10-23

- GOAL: provide a local, authenticated, read-only projection of saved V4 research; distinguish HTTP availability from actual ChatGPT tool integration.
- WRITER: this user-started Codex chat, sole writer. The latest task prohibits creating, resuming, or delegating other tasks; it takes precedence over the usual controller/Writer split for this batch.
- REVIEWER: NOT_RUN. No independent agent is created under that instruction; author checks do not constitute independent acceptance.
- ALLOWED_PATHS: `integrations/chatgpt_readonly/**` in this isolated sparse worktree and the same new directory in the canonical source for delivery. Branch metadata and this batch's explicit GitHub sync are included.
- FORBIDDEN_PATHS: existing V4 source/configuration, saved research/business data, V5/Vibe, credentials/session files, launch agents, global settings, network permissions and services.
- BASELINE: `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`; branch `codex/v4-readonly-gateway-20261023`. Canonical working edits are not copied into this worktree.
- DELIVERY: GitHub `main` was read as `615d1ce5417ed65ca2c8b736435c5d4596b79b19`. The source-only delivery branch `codex/v4-readonly-gateway-20261023-delivery` is built over that remote baseline using only this directory's explicit file allowlist, so unrelated local history/files are not published. Candidate and delivery commits have different parents; compare the delivered file hashes, not their commit identities.
- PASS_SIGNAL: author security tests and real saved-data comparison pass, source bytes/listener remain unchanged, and the five requested handoff documents are present. This supports local implementation only; independent review, deployment, external HTTPS and actual consumer calls remain separately NOT_RUN/BLOCKED.
- STOP_RULE: no publication, new deployment secret, installation, persistent process, permission change, connector/GPT configuration, business repair, or data fallback without the task's separate explicit approval. Broken/incomplete sources fail closed.
- SAFETY: `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.

The preselection HTTP reader can reconcile pending commits. This gateway therefore imports no V4 application/store code and calls no V4 business endpoint. It opens only fixed saved-artifact families using read-only file descriptors and verifies the existing hashes. A pending commit is rejected, never repaired.
