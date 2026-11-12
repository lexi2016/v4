# Byte-preserving daily storage maintenance · 2026-11-12

Candidate only. Original D12 data was read for dry-run, never changed by Writer. Source and identity review, actual compaction, installation and next-day natural behavior remain separate gates.

## Scope and measurements

One existing Main owner, existing registry writer + completion/A_LONG/qfq locks; no collector, polling, daemon, timer, model/formula/BUY/PIT or API reader changes. Original path/content SHA/mtime/link-count and semantic observation time remain. APFS transparent native compression, with SHA-exact COW clone for the two duplicate contents if metadata is compatible; never hardlinks. Creation inode necessarily changes at atomic replacement. Original `.day`, official ZIP, D11 blocks, other dates/projects and failed evidence are excluded.

Read-only D12 closure (`STORAGE_D12_DRY_RUN.json` in `/Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112`):

| Explicit current-date root | Logical bytes |
| --- | ---: |
| P/checkpoints/20261112/37aaffcb… | 681,010,582 |
| P/f10/20261112/953ab5bd32f7de0d | 110,764,704 |
| One pinned fea54133… adjustment snapshot | 113,167,846 |
| S/receipts/a_sync_authority/20261112 | 183,029,114 |
| S/receipts/a-20261112.json | 180,406,996 |
| P/versions/20261112 | 21,524,162 |
| P/continuations/20261112 | 9,692,631 |
| P/top200/20261112 | 9,101,410 |

P = existing dated A product root; S = existing research_panel_daily state root. The last three roots were expressly authorized same-D12 derivative references, adding exactly 40,318,203 B to the initial five roots; no prior date scanned. Total **29,629 files, 1,308,697,445 logical B, 1,368,731,648 file allocated B**; 10,753 JSON/CSV files eligible (>=8 KiB); 18,876 excluded files retained (including 341 existing gzip images and small text). Two exact duplicate eligible files total 10,756,179 logical B. Do not count those bytes again as measured reclaimed space.

Full path/size/content-SHA digest `ff5cd429d5a9e50eddd44be5b2cecbb1e2b36937c34f84f4eeae4faddf48a411`; plan metadata stamp digest is separate. Dry-run took 6.08 s with measured 18 cores/128 GiB/free86%, 14 workers/28 pending and 24 GiB foreground reserve. Default native work budget20 s is an initial bounded completion-event choice supported by that scan and the existing three-sample native canary; wall time includes safe drain and full verification and can exceed20 s. No deadline cancels an in-flight native process.

`st_blocks*512` is file allocation accounting, not APFS exclusive space. Runtime receipt separately reports compressed/clone operations, block-accounting drop, clone logical shared bytes, and `clone_exclusive_savings=CANNOT_CONFIRM`. Existing governance `billing_bytes` and reservation accounting use `st_size`: this change does not release or reinterpret those logical limits/reservations.

## Implementation and checks

- `ops/research_storage_compaction.py`: no writes in dry-run; all source/parent paths reject symlinks; nlink1, same device, original mode/uid/gid/mtime, exact source stamp + content before commit, native temp full SHA, atomic same-parent replace, directory fsync, complete before/after content digest. Failure before commit retains original; own temp is removed. Clones require identical user metadata/provenance and exclude unknown resource forks. Three native failures stop new submissions and bound failure records. Busy owners defer rather than poison the closure. The real inherited A_LONG helper validates the executing event date/slot/inode, separately from an older pending job day. Invalid current leases retain failure evidence without permanently blocking closed data. A sparse private no-benefit cache binds path/stamp/content/algorithm SHA, so budget passes and new F10 files skip previously terminal unchanged cases; no per-file success ledger is produced.
- `ops/research_storage_governance.py`: original `claim.finish` and numeric/index publication occur first; independent hook runs while the original registry writer remains held. It cannot change business result/manifest, partial status or delivery eligibility. Private pending JSON holds only already registered closed day/generation/input references; subsequent original completion events resume them with fair current/old budgets. No undeclared history walk. PASS+same closure stamps reuses without hashing; compressed files skip native rewriting. New closed F10/files cause changed scope detection on the next original completion event.
- SOP: copied current canonical valid text SHA `71b108056c3f5e0fc38ca07a092a39463362ac46402f5832c365cc931b1961d9` byte-for-byte as prefix; append section7 only. No automation17 prompt overwrite. Details in `SOP_ADOPTION.json`.
- Tests: `STORAGE_TEST_R1.txt` **11 passed**; following the narrow metadata/busy deferral fix, `STORAGE_TEST_INCREMENT.txt` **2 passed / 10 deselected**, covering the affected native clone and new busy-owner recovery. The first independent source review then reproduced two missing relationships (old-day pending under a new-day real lease; no-benefit prefix starvation). Both red cases are preserved in `STORAGE_REVIEW_RED.txt`. Only those direct defects were revised. Final affected regression `STORAGE_REVIEW_FINAL.txt`: **6 passed / 9 deselected**, covering the unchanged real helper under a held current-day lease, retained original lock, no-benefit progress across5 budgets/new F10/changed file, zero-budget continuation, fair pending, busy and invalid-lease recovery. Total current suite has15 cases; prior unaffected checks reused. `STORAGE_REVIEW_GREEN.txt` preserves the first repair attempt's test-harness missing `fcntl` global; corrected without changing production helper code. Checks include native scratch compression+clone ordinary JSON readers/bytes/dates/nlink1/flags; symlink/hardlink/unclosed/raw rejection; source/CAS and native failure preservation; owner busy; zero-budget deferral and later F10; bounded repeated failures; persistent fair pending; maintenance failure leaves business result unchanged. Only tiny test-owned scratch files were transformed, no original D12 files.

Commands (cwd worktree):

```sh
"$PANEL_PYTHON" -m pytest -q tests/test_research_storage_compaction.py --basetemp=/Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112/pytest-storage-r1
"$PANEL_PYTHON" -m pytest -q tests/test_research_storage_compaction.py -k 'native_compression_clone or busy_pending_owner' --basetemp=/Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112/pytest-storage-increment
"$PANEL_PYTHON" -m pytest -q tests/test_research_storage_compaction.py -k 'real_inherited_owner or no_benefit_prefix or zero_budget or pending_queue or busy_pending_owner' --basetemp=/Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112/pytest-storage-review-final
```

## Controller execution recipe (NOT RUN by Writer)

Use the exact reviewed `STORAGE_D12_DRY_RUN.json`, its recorded SHA and source binding. Load compaction module from the reviewed committed worktree before installation, or installed active Main afterward. For pre-install maintenance, use `spec_from_file_location('ops.research_storage_compaction', reviewed_path)` only after pinning actual Main as `sys.path[0]` / `PYTHONPATH`, validating Main manifest and imported governance/retention `module.__file__`+SHA. Do not inherit an old alias before active Main; stage1's original failed import attempt remains evidence. The concrete runner `execute_storage_plan.py` defaults to read-only preflight, verifies actual Main manifest/module paths and byte SHAs, and preserves current Main plist environment and exact current policy SHA. No changes to policy limits, registry task rows, permit or scope gate are needed.

Concrete pre-install command (add `--execute` only after independent acceptance; use a fresh execution receipt filename). After installing the candidate, substitute the actual new Main manifest SHA rather than the old one:

```sh
"$PANEL_PYTHON" docs/operations/storage_compaction_20261112/execute_storage_plan.py \
  --plan /Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112/STORAGE_D12_DRY_RUN.json \
  --expected-plan-sha256 09b48854871529863e851754c8fbc704e88a31eac278cfb6f071d9dba6ee8e73 \
  --expected-main-manifest-sha256 1ecc6373c11eb36ff09881d925be20607e612ce2eab8a2c19961f16513b99643 \
  --output /Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112/STORAGE_D12_PREFLIGHT.json
```

```python
# Existing owner environment; active Main module paths and every SHA checked first.
plan_path = N / 'STORAGE_D12_DRY_RUN.json'
assert sha(plan_path) == EXPECTED_REVIEWED_PLAN_SHA
plan = json.loads(plan_path.read_bytes())
assert plan['status'] == 'DRY_RUN_NO_DATA_WRITES'
# policy_path/hash come from the actual current Main plist, not a copied old alias.
assert sha(policy_path) == expected_policy_sha
policy = json.loads(policy_path.read_bytes())
result = compaction.execute_plan(plan, policy=policy, output=N/'STORAGE_D12_EXECUTION.json')
# This obtains the existing registry writer and three original owner locks.
# Expected plan stamps/content are checked under those locks before mutation.
```

The controller must record actual full content digest equality, retained logical bytes, block-accounting change, separate clone counters, unchanged semantic readers and excluded original data boundaries. A plan-CAS failure requires a new read-only plan plus affected evidence review, never blind retries or a changed expected SHA. A native failure preserves originals; identical failed scopes are blocked from automatic retry. Busy owners and budget DEFERRED are kept pending for original completion events.

Physical compression reversal, if explicitly needed, uses an ordinary uncompressed same-byte temp copy then the same SHA/stamp/owner locks and atomic replacement; no data backup/restore or deletion is necessary to recover the original readable content because it never changed. Software rollback uses the previous actual Main/Stage identity pair and original owner transition; do not reverse code files in place after activation.

`prepare_storage_candidate.py` reuses the prior clone/inventory/attestation helpers, requires actual stage1 Main `1ecc637…` and Stage `6fd32…`, copies only the three Main source/SOP delta paths, preserves the prepool repair, and repins Stage current owner/history11→12 with transition/code unchanged. It requires exact committed bytes and writes only a new inactive candidate. Independent review and controller coordinated activation remain required. No raw data/runtime trees/plists/policies/private registry are to be uploaded to Git.
