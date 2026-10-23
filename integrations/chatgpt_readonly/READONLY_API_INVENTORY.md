# Saved V4 read-only inventory

Audit date: 2026-10-23, Asia/Shanghai. Consumer identified by the user: the dot named **嘻嘻** in the desktop app. Its actual plugin permissions have not been read or changed. A custom GPT Action is a different consumer.

## Runtime and sources

The existing listener was PID 61639 on `127.0.0.1:8873`. Its working release was `hk-morning-history-observation-20261023-r2/app`, not the canonical working tree. The latter had 734 pre-existing changes at the initial check. Existing source and data were not modified.

Only selected non-secret data-root fields were inspected in the existing LaunchAgent/operator binding. Exact local roots are recorded in the ignored `local_only/operator_bindings.json`. In particular the workbench root includes the extra `manager_workbench` directory appended by `WorkbenchStore`; a parent directory is not interchangeable with that root.

| Existing HTTP route | Actual chain / finding | Gateway use |
| --- | --- | --- |
| `GET /healthz` | Returns the existing API liveness object; no producer/store operation. | The only upstream HTTP request; fixed host, port and path, no redirects or proxy environment. |
| `GET /api/v3/preselection-pools` | `PreselectionPoolService.read` → domain assembly → source resolver → native pool reader. `read_pool_snapshot` / `read_all` can reconcile a pending commit and acquire write-capable locks. | **BLOCKED as an upstream**. Read existing artifact/manifest/receipt directly; reject pending commits. |
| `GET /api/v4/manager-workbench/stocks/{symbol}` | Saved pointer/plan reads plus display projections. Constructing its service/store would create directories; importing or constructing the full application is unnecessary. | No upstream call or application import. Read the already-saved plan with its original product hash and explicit phase. |
| `GET /api/v4/manager-workbench/announcement-flash` | Saved deliveries mixed with membership, job and resume/transport eligibility projections. This is a larger dependency surface than a saved-summary reader needs. | **Not admitted as an upstream**. Read the existing delivery index and SHA-bound saved delivery, preserving unknown/review status. |
| `GET /api/v3/review` | Cross-market composition with multiple bindings and evidence layers. | Not exposed. The gateway only has a narrow saved **manager-plan review summary** projection; it is not the whole V4 review page. |
| Existing `ensure`, `runs`, `retry`, update, repair, collection or generation routes | Trigger or control business execution. | No gateway mapping, no generic upstream proxy, and no non-GET method. |

## Implemented local contract

| Gateway route | Required parameters | Bound saved source | Real-record check |
| --- | --- | --- | --- |
| `GET /health` | none | Gateway liveness only | Author check; no data availability claim. |
| `GET /v1/pools` | `trade_date`, `market`, `pool_id`; optional `limit`, `offset` | `preselection_pools/YYYYMMDD/{approved_pool}.json`, shared manifest and exact receipt | 20261022 A research pool: 251/251 rows; HK D-1 pool: 100/100 rows, including pagination. |
| `GET /v1/stocks/{code}/research` | HK code, `trade_date`, `market=HK`, explicit `phase` | Exact-date phase pointer → saved manager snapshot | One real 20261022 INTRADAY stock; identity, name, decision, reasons, risks, conditions, date, version and hashes compared. |
| `GET /v1/announcements` | `trade_date`, `market=HK`; optional `limit`, `offset` | Exact-date delivery index → validated `latest.json` → SHA-named immutable delivery | 20261021 saved delivery: one stock summary; article identities and source/body hashes compared. |
| `GET /v1/reviews` | `trade_date`, `market=HK`, explicit `phase` | Saved manager plan → same-date same-plan review | **NOT_RUN with a real review**. No 20261022 manager review was found. This route returns unavailable when no saved review exists. |

Only the seven existing pool IDs in `saved_reader.POOLS` are permitted. Each pool is read independently; a missing optional pool never blocks another requested pool. Pool choice and A/HK boundaries are explicit. There is no aggregate selector, replacement producer, quote acquisition or formula calculation.

## Projection and integrity boundaries

- Descriptor-based `O_RDONLY`, `O_NOFOLLOW` reads; every directory component is checked by opening it. Non-regular files, symlinks, oversized files and read races fail closed. No business directory, lock, cache or record is created.
- Pool canonical JSON has **no trailing newline**. Manager snapshot canonical JSON **includes a trailing newline**. These existing contracts are kept separate. The first real-data check caught that distinction; the gateway was corrected, with source records unchanged.
- Pool manifest + receipt + identity are checked, with the manifest and pending-commit state checked again. Manager product hashes, pointer/date/phase/run identity and pointer stability are checked. Announcement byte hash, exact reference/job/date and index/binding stability are checked.
- Responses include only stock identity/name, original research decisions/statuses, necessary reasons/risks/conditions, selected numeric pool fields, and announcement article metadata/short reasoning. No full report/body, queue, config, raw log, local path, account or holding is returned. Unsafe or oversized summary strings are omitted and stock summary omission is explicitly marked.
- `as_of` means a timestamp recorded in the source, with a timezone. It is **null** with a missing reason if the source has none. `observed_at` is a separate reader time. Current saved pool/delivery examples lack an authoritative saved-at timestamp; they remain `unknown`. Hash agreement does not certify model semantics, PIT safety, recommendations or strategy performance.
- Offsets paginate the entire requested pool; no 200-row display limit is applied to selection inputs. Source counts, returned counts and `next_offset` prevent a page being presented as a complete dataset. Oversized responses return 413 rather than silently shortening a success.
- Every business endpoint requires the new dedicated Bearer credential. Missing/incorrect/revoked credentials return 401. Methods other than GET, unknown routes/parameters, duplicate query/auth values, GET bodies and path encodings are refused before reading saved data.

No MCP transport is implemented in this batch. MCP JSON-RPC normally uses POST for read tool calls; that is a protocol operation, but adding it would require explicitly revising this batch's GET-only network contract and selecting the dot's supported authentication. The REST Bearer key must not be assumed to be a supported dot-plugin login.
