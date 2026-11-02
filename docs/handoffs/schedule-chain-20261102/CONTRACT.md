# Frozen schedule connection scope · 2026-11-02

GOAL: Establish remaining Main/Stage completion/consumer/API connections with bounded isolated artifacts, reuse matching prior PASS, and repair only a reproduced defect. No natural/deployment claim.
WRITER: /root/schedule_chain_writer, Sol High; baseline a67e81143f8a936df303356e532b6520850dfdb2.
REVIEWER: independent read-only identity assigned by controller after handoff.
ALLOWED_PATHS: ops/run_stage_center_milestone.py (persist the exact returned receipt, emit compact SHA reference); domains/task_status.py (verify only that versioned milestone reference against independently read receipt SHA and exact identity); tests/test_schedule_chain_connections.py; docs/handoffs/schedule-chain-20261102/{CONTRACT.md,RESULT.json,HANDOFF.md}; external evidence root /Users/lexi/Desktop/学习/agents调试/v4_schedule_chain_repair_20261102.
FORBIDDEN_PATHS: Terra's attestation/index/preparer/candidate files; existing reports; business data, selection/history receipts/manifests; research panel; PDF/WeChat processing; gates/ranking/BUY/orders; other worktrees; service/scheduler/plist changes.
PASS_SIGNAL: original evidence diagnosis plus real stored selection -> committed runner -> completion consumer -> dispatcher/ledger/registry -> milestone -> manager StageFeed/API connection checks; file SHA and exact commit for independent review and Terra integration.
STOP_RULE: owner conflict, CAS drift, shared-service action/new permission/raw data write; at most two evidence-backed repairs before stop.

Reused evidence: Batch2 source12/event4/wrapper7/rollback1/witness6/history3, original Main/Stage off/on/reuse/fault, r4 receipt guard narrow PASS. Unchanged areas are not rerun. New fixtures are artificial and confined to task-owned temporary roots; no natural data or market acquisition.

Reproduced defect: a successful milestone returns receipt_path and optional sidecar fields only after its atomic receipt write. The API's existing exact stdout-versus-receipt binding therefore returns CANNOT_CONFIRM despite a valid successful Stage/dispatch. Strengthened cross-chain API READY assertion reproduces failure. Fix the writer ordering; retain exact API verification. Deadline diagnosis is read-only until a current defect is demonstrated; September stderr is not a November failure.

First repair exposed the same boundary's 2048-character executor stdout cap: a full market receipt is truncated and no longer parseable JSON. Retain the common cap; emit a compact, versioned SHA reference from the milestone CLI and verify it only for the two declared milestone nodes against the independently read full receipt. All other stdout binding rules remain exact. Second implementation attempt must pass the frozen cross-chain oracle or stop.

Controller's narrow exception after second check: normal reference/API binding passed, but omitting failure_class/reason changed an upstream failure to CONTRACT. Writer stopped and reported. Controller explicitly authorized copying those original failure fields into the reference, preserving the original dispatcher classification policy. Only the affected failure/size/identity/legacy cases may be checked; another substantive failure stops business writes.
