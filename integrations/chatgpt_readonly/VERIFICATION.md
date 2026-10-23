# Verification — local candidate, 2026-10-23

## Status and identity

- User goal: let the existing dot **嘻嘻** read saved V4 research, with no new/delegated Codex/Mac task, no business writes and separate approvals for deployment, credentials, permissions and consumer configuration.
- Candidate baseline: `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`; candidate branch `codex/v4-readonly-gateway-20261023`. This is an isolated sparse Git worktree, not a newly created Codex task.
- Delivery baseline: remote `lexi2016/v4` main `615d1ce5417ed65ca2c8b736435c5d4596b79b19`. Publish only the explicit new-path allowlist over that tree on `codex/v4-readonly-gateway-20261023-delivery`; do not publish unrelated canonical/local history. The ignored GitHub sync receipt records actual candidate/delivery commits and remote readback.
- Runtime checked: existing 8873 process PID 61639; loopback; release `hk-morning-history-observation-20261023-r2/app`. Gateway code does not run inside that process and imports no V4 application/store.
- Checks used the existing runtime: CPython 3.14.6, FastAPI 0.141.1, HTTPX 0.28.1, pytest 9.1.1, Uvicorn 0.52.1. No dependencies were installed.

| Acceptance layer | Result | Practical scope |
| --- | --- | --- |
| Implementation | IMPLEMENTED | Only the new isolated gateway, tests, schema and handoff files. |
| Author security checks | PASS: **52 passed in 0.22s** | Authentication/revocation, refused methods/routes/parameters/bodies/path encodings/duplicate headers, no reader call on refused requests, exact dates, race/hash/pending/symlink checks, read-only open flags, no secret/path echo, pagination, size, deadline, held timeout slot and concurrency bounds. |
| Author real-record check | PASS | In-process ASGI, original saved files, existing V4 health check. No listener, cloud task or deployment key. |
| Independent Reviewer / formal TESTED / BEHAVIOR_VERIFIED | **NOT_RUN** | The current task expressly prohibits creating/delegating another task. Author PASS is not relabeled independent acceptance. |
| Integrated into original V4 | NOT_RUN | Existing source/configuration/business data are unchanged by this batch. |
| Gateway socket / persistent service | NOT_RUN | Code fixes the host to loopback; no service was started. |
| External HTTPS / public access | NOT_RUN | No provider, domain, tunnel, certificate, network permission or paid resource selected. |
| 嘻嘻 consumer tool call | NOT_RUN / BLOCKED | Actual dot-plugin controls unverified; MCP transport and compatible auth are not configured. |
| Natural-time strategy/data semantics | NOT_RUN | This is a reader check; it does not validate formulas, PIT admission, market freshness or model acceptance. |

## Reproducible commands and raw-result locations

Run from this worktree root with the existing Python binary. The exact local Python/data roots and commands are recorded in ignored `local_only/operator_bindings.json`.

```sh
"$V4_READER_PYTHON" -B -m pytest -q -c /dev/null -p no:cacheprovider \
  --basetemp=integrations/chatgpt_readonly/local_only/pytest-release-check \
  integrations/chatgpt_readonly/tests/test_gateway.py

"$V4_READER_PYTHON" -B -m integrations.chatgpt_readonly.verify_saved \
  --pool-root "$V4_READER_POOL_ROOT" \
  --workbench-root "$V4_READER_WORKBENCH_ROOT" \
  --trade-date 20261022 --announcement-date 20261021

"$V4_READER_PYTHON" -B -m integrations.chatgpt_readonly.schema
```

- Unit raw stdout captured from the actual command: `local_only/unit_test_output.txt`; compact author receipt: `local_only/author_checks.json`.
- Real source comparison receipt: `local_only/real_saved_verification.json`; each touched file's source hash is retained there. No raw research response or source dataset is uploaded to GitHub.
- Necessary source/test/schema/document before/after hashes: `SOURCE_MANIFEST.json` (it excludes itself). Before state for every batch file is ABSENT; this is additive work.
- GitHub commit/push and fresh remote file-hash readback: `local_only/github_sync_receipt.json`. Absence or failure of that receipt means remote sync is not verified; a local commit alone is insufficient.

## Real-record evidence

| Saved source | Exact date | Compared | Source identity |
| --- | --- | --- | --- |
| A research recommendation pool | 20261022 | 251/251 rows, six pages | Artifact `59b2f44e70fe03cc23c40432315460bbd6a92aeb0d14200ab6120924ad053f72` |
| HK D-1 pool | 20261022 | 100/100 rows, two pages | Artifact `aa34c0eb38dffffa3669b6e956a90e7f68d4a686b6595b287e6896392d1f3783` |
| HK manager stock research | 20261022 INTRADAY | One real stock's saved identity/name/decision/reasons/risks/conditions, date, rules and hashes | Plan `622c0b49c9e44ed2ac78503e6999048b`, product `427e9e1b3cfd0c738e5fa15edb50e19f563f2417bae5f60333e91b107367b682` |
| HK saved announcement delivery | 20261021 | One saved stock, article identities/source/body hashes, name and reasons | Artifact `46aaa479e253c7ea3a8b152163f8e14a4ffefa13f30c0913d0476d72ec17b0f8` |
| Unknown date | 19000101 | 404 `unavailable`; no fallback | No source for that date was invented. |

All observed example payloads remain `unknown`, for missing authoritative source times and/or unconfirmed source/review states. These are successful faithful reads, not evidence that source semantics are valid. Missing source versions or timestamps remain null with reasons rather than being manufactured.

The final real-record run completed in **0.621 seconds**. Ten touched saved files had identical before/after bytes; the original 8873 listener PID remained the same. Its approximately 40 MiB manager snapshot motivated the default concurrency of one; the verification process peaked at about 551 MiB RSS on a 128 GiB Mac. The tests prove no write-capable file-open flags are used by the reader. This does not claim unrelated concurrently running tasks made no changes elsewhere on the Mac.

## Retained failures and limitations

1. The first real pool read returned `503 POOL_IDENTITY_OR_HASH_MISMATCH`: the initial gateway used the manager canonical JSON newline for pool hashes. Inspection of the actual pool receipt/raw bytes and `infrastructure.data_store._canonical_bytes` established the no-newline pool contract. The gateway was corrected; no source/manifest/receipt was changed. The subsequent real read and final run passed.
2. An initial pytest run had warnings from pytest trying to clean an unrelated pre-existing temporary garbage directory. No permission change or manual cleanup was attempted. Later runs used a new task-owned `--basetemp` and passed cleanly. The warnings are not treated as a V4 business failure.
3. This environment exposes no bot-profile reader. The app's native UI read was rejected: `Computer Use is not allowed to use the app 'com.openai.codex' for safety reasons.` No alternative desktop capture or settings access was attempted. The specific 嘻嘻 profile/plugins are **CANNOT_CONFIRM**.
4. General dot plugin support is documented by OpenAI; actual account/plugin availability is not established by those documents. REST Actions authentication is not automatically MCP/dot authentication.
5. The review-summary route has no real-record PASS; no saved manager review for the selected date was found. Other pool IDs beyond the two real-checked pools are schema-bound but have not each received a real-record acceptance run. A/HK scope is not expanded to A-share manager-stock research.
6. No real gateway socket, external TLS/auth check, MCP adapter, dot configuration or actual consumer call has been executed. No end-to-end completion is claimed.
