# PR20 R5 Mac isolated acceptance: FAIL; synthetic P2 boundaries PASS

This feedback records the original published candidate `993b1f7c85c6cc07318c148e5de3fcb8973fe9a3` only. It contains sanitized test outputs, source identity and reproduction commands, with no code fix, price rows, source-market files or machine-private configuration. The author's PR branch is unchanged.

## Result and boundary

- Service Python 3.14.6 on Mac. First target run started `2026-10-02T04:26:57.256311+00:00`, ended `2026-10-02T04:26:57.426755+00:00`, exit 1: **5 passed / 2 failed**.
- Three published patches were applied to separate inactive R3+R4 copies; all 10 candidate after SHAs matched. Active release/data were not changed by this acceptance.
- One first-run failure was the acceptance assembly's symlink resolving outside the explicit shared root. Replacing only that new symlink with a byte-identical physical shared copy corrected the harness layout; **only that affected qualification test was rerun, 1 passed, exit 0**. Candidate code and original assertions were unchanged. The initial output remains below. This is not a 7/7 suite claim.
- The candidate still fails at `preselection_app/ops/macos_research_panel_daily_collectors.py:218`: **NameError: name '_frame_records' is not defined**. The loaded file matched SHA `8a2a7b3ab905b58e1ac99ef8a50c3f64a653454cc75de617bed0158cdd284bad`.
- R9 P2: `natural_verified=false` positive accepted; the otherwise equal `true` negative rejected (`HK preselection eligibility as-of mismatch`).
- Stage P2: valid-date synthetic controls use source 20260929 / target 20260930. The controls differ only in `historical_provenance.eligibility_asof.natural_verified`: false accepted, true rejected (`HK D1 eligibility provenance identity mismatch`). Both dates were adapted together from the saved R4 20261007 / 20261008 fixture because its false positive violates the new R5 Connect calendar contract. The obsolete-date positive failure is retained locally and was not treated as a passing negative test.
- P2 PASS applies to these two isolated synthetic boundaries. Real membership/history recovery, deployed API/UI and natural operation were not executed or claimed by this acceptance. No collectors/providers/scheduler/selection/training or extra model calls were run. Existing 690 PyTDX rows and prior A/R4 acceptance were not rerun or altered.
- Wrappers guarded socket connect and subprocess launches for the target and P2 probes; their blocked-attempt arrays were empty. The single corrected-layout qualification recheck used direct pytest with injected synthetic callbacks.

## Latest deduplication readback

Before publishing this feedback, PR20 remained Draft/Open at `993b1f7c85c6cc07318c148e5de3fcb8973fe9a3`; its discussion had the R4 delivery and original R5 delivery, but no equivalent Mac NameError feedback and no published fixed head.

A separate original-owner local Mac delivery was observed read-only after this acceptance: at 05:02–05:10 UTC its `local_fix` collector after SHA was `222409f75d088181d59ea7f12376924b3e92847d20d05cf0cba6e329eb1c1449`, and its independent receipt reported 11 tests (7 original + 4 local recovery) passing. This is a different local revision, not proof that the PR20 published SHA passed or that the fix was uploaded. No local owner code or market artifact is included here.

## Original target stdout (sanitized paths)

```text
.FF....                                                                  [100%]
=================================== FAILURES ===================================
_ test_manual_membership_recovery_two_deltas_self_verifies_and_stays_non_natural _
preselection_app/stage_center/_live_collectors_parts/shared_module_loading.py:56: in __load_shared_module_body
    module_file.relative_to(package_root)
<SERVICE_STDLIB>/pathlib/__init__.py:490: in relative_to
    raise ValueError(f"{str(self)!r} is not in the subpath of {str(other)!r}")
E   ValueError: '<R5_ACCEPTANCE_ROOT>/shared_package/scripts/live_acquisition/universe.py' is not in the subpath of '<R5_ACCEPTANCE_ROOT>/preselection_app/upstreams/v3_shared_data'

The above exception was the direct cause of the following exception:
tests/test_hk_history_r5_target.py:79: in test_manual_membership_recovery_two_deltas_self_verifies_and_stays_non_natural
    reader=publisher._load_shared_universe_reader()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
preselection_app/stage_center/hk_universe_preflight.py:209: in _load_shared_universe_reader
    module = _load_shared_module(package_root, "scripts.live_acquisition.universe")
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
preselection_app/stage_center/live_collectors.py:166: in _load_shared_module
    return _v4_impl(globals(), shared_root, module_name)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
preselection_app/stage_center/_live_collectors_parts/shared_module_loading.py:58: in __load_shared_module_body
    raise _v4_global(_v4_scope, 'ValueError')(f"shared collector resolved outside explicit root: {module_file}") from error
E   ValueError: shared collector resolved outside explicit root: <R5_ACCEPTANCE_ROOT>/shared_package/scripts/live_acquisition/universe.py
___ test_history_reader_keeps_real_retrieval_time_and_no_historical_capture ____
tests/test_hk_history_r5_target.py:144: in test_history_reader_keeps_real_retrieval_time_and_no_historical_capture
    result=collect_hk_futu_history_rows('20260929',codes,names=names,
preselection_app/ops/macos_research_panel_daily_collectors.py:218: in collect_hk_futu_history_rows
    for item in _frame_records(frame):
                ^^^^^^^^^^^^^^
E   NameError: name '_frame_records' is not defined
=========================== short test summary info ============================
FAILED ../../../../../../../dev::test_manual_membership_recovery_two_deltas_self_verifies_and_stays_non_natural
FAILED ../../../../../../../dev::test_history_reader_keeps_real_retrieval_time_and_no_historical_capture
2 failed, 5 passed in 0.13s
```

Target stderr: empty.

## Corrected-layout qualification recheck stdout

```text
.                                                                        [100%]
1 passed in 0.17s
```

Recheck stderr: empty.

## P2 receipts, compact

```json
{
  "R9": {
    "verdict": "PASS",
    "positive_false": "ACCEPTED",
    "negative_true": "REJECTED",
    "rejection": "HK preselection eligibility as-of mismatch",
    "checked_at": "2026-10-02T04:30:55.830707+00:00"
  },
  "Stage": {
    "verdict": "PASS_STAGE_P2",
    "positive_false": "ACCEPTED",
    "negative_true": "REJECTED",
    "rejection": "HK D1 eligibility provenance identity mismatch",
    "source_date": "20260929",
    "target_date": "20260930",
    "checked_at": "2026-10-02T04:32:45.874403+00:00"
  }
}
```

## Pinned file identities

| Isolated root / relative file | SHA256 |
|---|---|
| `preselection_app/stage_center/hk_universe_preflight.py` | `20f5ff51562907c09334f66eed9c488036698b4ae369111e79b049f91b7281a8` |
| `preselection_app/ops/macos_research_panel_daily_collectors.py` | `8a2a7b3ab905b58e1ac99ef8a50c3f64a653454cc75de617bed0158cdd284bad` |
| `preselection_app/ops/macos_research_panel_daily_gate.py` | `f9fc415e8fcdb93daad70f55f08e548f4a059380d1f692551e2dcf755b5e3d68` |
| `preselection_app/domains/preselection_materializer.py` | `b5692e2229b5c844a1674e77aa04e7beb7648bd4cad18022f9456c17c1fcf283` |
| `preselection_app/infrastructure/scheduling/executor_registry_preselection.py` | `589219ae5539137dd45f4de2971ae820e16bf7c2c457e38f2d40607678920674` |
| `preselection_app/infrastructure/preselection_pool_store.py` | `19d040c5e785ead8a670d593446b0b786369de445ff75a54693978ecc1f28d57` |
| `shared_package/scripts/live_acquisition/universe.py` | `05bf0c0b0be74ef31c969400bbd7ffabea157db899e5380d86f205ba53d0e427` |
| `shared_package/shared_data/hk_security_master.py` | `32e5b9b0bbd3442e3f13f577af3e4db3a3fe0b97f17440dd904cecd4c0c87fc0` |
| `shared_package/shared_data/hk_0_2.py` | `3e57bfed43b570c4f8df7483ebaa6f44b6dfc79ec267531384312af01fca1de7` |
| `stage_app/stage_center/_runner_parts/hk_input_validation.py` | `3270d4e4a1b66e7a1d843b6a52e0d4c1fd3be70b054ab6b16f7655ace306928f` |


Original target test SHA256: `e35d0af682942d830cdb305393f3f300230fd3e870ba7a271af116eada51cbec`. Final local read-only checks found all 10 after SHAs and the original test SHA unchanged.

Actually loaded key modules (paths relative to isolated acceptance root):

```json
[
  {
    "module": "infrastructure.preselection_pool_store",
    "path": "preselection_app/infrastructure/preselection_pool_store.py",
    "sha256": "19d040c5e785ead8a670d593446b0b786369de445ff75a54693978ecc1f28d57"
  },
  {
    "module": "stage_center.hk_universe_preflight",
    "path": "preselection_app/stage_center/hk_universe_preflight.py",
    "sha256": "20f5ff51562907c09334f66eed9c488036698b4ae369111e79b049f91b7281a8"
  },
  {
    "module": "ops.macos_research_panel_daily_collectors",
    "path": "preselection_app/ops/macos_research_panel_daily_collectors.py",
    "sha256": "8a2a7b3ab905b58e1ac99ef8a50c3f64a653454cc75de617bed0158cdd284bad"
  },
  {
    "module": "domains.preselection_materializer",
    "path": "preselection_app/domains/preselection_materializer.py",
    "sha256": "b5692e2229b5c844a1674e77aa04e7beb7648bd4cad18022f9456c17c1fcf283"
  },
  {
    "module": "test_hk_history_r5_target",
    "path": "tests/test_hk_history_r5_target.py",
    "sha256": "e35d0af682942d830cdb305393f3f300230fd3e870ba7a271af116eada51cbec"
  },
  {
    "module": "stage_center._runner_parts.hk_input_validation",
    "path": "stage_app/stage_center/_runner_parts/hk_input_validation.py",
    "sha256": "3270d4e4a1b66e7a1d843b6a52e0d4c1fd3be70b054ab6b16f7655ace306928f"
  }
]
```

## Reproduce the candidate failure without live acquisition

Prepare the published three-root patches on their SHA-matched inactive before images; use a physical copy of patched shared package at `preselection_app/upstreams/v3_shared_data`. Set the following variables to your local isolated root, service Python and a fresh output directory. This is the direct pytest equivalent for the unchanged failing target case; it was not additionally run during this feedback preparation.

```sh
# R5_ACCEPTANCE_ROOT=<isolated prepared root>
# SERVICE_PYTHON=<existing Mac service Python 3.14.6>
# REPRO_OUTPUT_ROOT=<new isolated output directory>
env PYTHONPATH="$R5_ACCEPTANCE_ROOT/preselection_app" \
  HK_R5_SHARED_PACKAGE_ROOT="$R5_ACCEPTANCE_ROOT/shared_package" \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  "$SERVICE_PYTHON" -B -m pytest -q --tb=short -p no:cacheprovider -c /dev/null \
  --basetemp="$REPRO_OUTPUT_ROOT/tmp" \
  --junitxml="$REPRO_OUTPUT_ROOT/junit.xml" \
  "$R5_ACCEPTANCE_ROOT/tests/test_hk_history_r5_target.py::test_history_reader_keeps_real_retrieval_time_and_no_historical_capture"
```

## Executed command record (paths sanitized)

The following records commands already executed; the root and interpreter placeholders are substitutions for private local paths. P2 wrapper names identify the local acceptance adapters, not author tests. No new execution is requested by publication.

已执行命令记录；不要据此重复运行。工作目录：<ACCEPTANCE_WORKDIR>。

首轮目标测试；exit 1，5 passed / 2 failed

```sh
env PYTHONPATH=<R5_ACCEPTANCE_ROOT>/preselection_app HK_R5_SHARED_PACKAGE_ROOT=<R5_ACCEPTANCE_ROOT>/shared_package PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 '<SERVICE_PYTHON>' -B <R5_ACCEPTANCE_ROOT>/run_target_acceptance.py > <R5_ACCEPTANCE_ROOT>/target_stdout.txt 2> <R5_ACCEPTANCE_ROOT>/target_stderr.txt
```

布局修正后，仅资格恢复失败项复验；exit 0，1 passed

```sh
env PYTHONPATH=<R5_ACCEPTANCE_ROOT>/preselection_app HK_R5_SHARED_PACKAGE_ROOT=<R5_ACCEPTANCE_ROOT>/shared_package PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 '<SERVICE_PYTHON>' -B -m pytest -q --tb=short -p no:cacheprovider -c /dev/null --basetemp=<R5_ACCEPTANCE_ROOT>/qualification_recheck_tmp --junitxml=<R5_ACCEPTANCE_ROOT>/qualification_recheck_junit.xml <R5_ACCEPTANCE_ROOT>/tests/test_hk_history_r5_target.py::test_manual_membership_recovery_two_deltas_self_verifies_and_stays_non_natural > <R5_ACCEPTANCE_ROOT>/qualification_recheck_stdout.txt 2> <R5_ACCEPTANCE_ROOT>/qualification_recheck_stderr.txt
```

R9 P2 正负例；exit 0

```sh
env PYTHONPATH=<R5_ACCEPTANCE_ROOT>/preselection_app PYTHONDONTWRITEBYTECODE=1 '<SERVICE_PYTHON>' -B <R5_ACCEPTANCE_ROOT>/run_native_p2.py store > <R5_ACCEPTANCE_ROOT>/store_p2_stdout.txt 2> <R5_ACCEPTANCE_ROOT>/store_p2_stderr.txt
```

Stage P2 合法日期正负例；exit 0

```sh
env PYTHONPATH=<R5_ACCEPTANCE_ROOT>/stage_app PYTHONDONTWRITEBYTECODE=1 '<SERVICE_PYTHON>' -B <R5_ACCEPTANCE_ROOT>/run_stage_p2_valid_dates.py > <R5_ACCEPTANCE_ROOT>/stage_p2_valid_stdout.txt 2> <R5_ACCEPTANCE_ROOT>/stage_p2_valid_stderr.txt
```

首轮 shared symlink 引起显式 root 拒绝，后替换为同 SHA 的物理副本。原始测试未改。早期 P2 跨包 loader 拒绝及旧日期正例失败分别保存在 p2_stderr.txt / stage_p2_stderr.txt；最终用原生隔离 Stage 导入及合法日期对照，未关闭 loader 策略。


## Follow-up

Reconcile the existing local-owner fixed revision with the author before doing another repair. Publish/review its exact fixed SHA through the authorized development task, then run only the affected acceptance if needed. Preserve this original FAIL receipt and do not replace it with Linux10, prior Mac27, or the separate local11 results. No merge or deployment is requested.
