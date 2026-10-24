# A-share daily sync component R3 source delta

Status: `REVIEWED_PASS_READY_TO_SYNC`; independent R3 review passed for the candidate scope.

This package contains only the two R3-changed files in the frozen allowlist. The installer wrapper is unchanged from the previously synced R2 commit and is intentionally omitted. The R3 change adds an explicit SHA-token-gated read of the controller-reviewed idle manifest. With no token, the R2 fail-closed idle path remains. With the exact token, install and rollback can recognize only the manifest-exact historical inactive A claim pairs and verified dispatch-only terminal records with no A workload; other claims remain. Runtime source count, dispatcher, and producer are unchanged.

The R3 READY record reports seven focused R3 tests passing (`7 passed, 22 deselected`), compilation of the three allowlisted Python files, and a read-only idle-gate check. The independent R3 review receipt reports its own three targeted tests passing (five cases), compilation of the three allowlisted Python files, and isolated synthetic gate/install/rollback probes. These checks support candidate review only; they do not establish actual activation or current live idle state. No tests were rerun during source-sync preparation.

The independent receipt is `future-binding/review/COMPONENT_REVIEW_R3.json`, SHA-256 `fd8140e3e35317826a3497bc5c35f516179f6d1883996559683cc0480aacaf01`. It records `REVIEWED/PASS` for the candidate only; deployment, API, UI, natural-period, end-to-end verification and controller activation release remain separate. The source-sync writer rechecked that `lexi2016/v4` branch `codex/a-panel-daily-binding-20261024` still pointed to `4084077f00c6e8919108e0e52c8f7d29599133ec` before constructing the delta. The remote ref update uses that exact expected SHA and `force=false`.

No runtime claimant inventory, raw ledger, data, path snapshots, logs, credentials, installer copy, or prior archive files are included here.
