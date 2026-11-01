# R2.2 独立验收反馈

ENGINEERING_SCOPE_FAIL，P0=0/P1=1/P2=0。REAL_AUTHORITY为BLOCKED_OWNER_PENDING，natural_sample_count=0；owner pending不是此次FAIL理由。未自行修复新问题。

## 唯一P1：provenance父目录symlink破坏本地封存边界
合同明确Do not symlink，完整性范围LOCAL_FROZEN_AND_SEALED_PROVENANCE。
_freeze_snapshot_internal约1921-1938只查date_root/run_root本身；_immutable_bytes约758-780对parent mkdir(exist_ok=True)仅检查最终文件；_read_frozen约2175-2186也只检查最终文件is_symlink，未检查父目录provenance。
独立Reviewer在临时目录实际执行：
(stage / 'provenance').symlink_to(outside, target_is_directory=True)
capture_selector_snapshot(payload, output)
结果capture=ENGINEERING_ONLY、localverify=PASS，但production_source.bin、production_rule.bin、d1_manifest.bin、formula_state.bin、formula_rule.bin写入outside。
随后修改outside/production_source.bin，本地verify变为ShadowInvalid: sealed provenance production_source hash mismatch。
所以封存仍依赖run_root外目标，不符合合同。这不是要扩成恶意Python/无限供应链，只需要真正落实既定run-root内、无symlink封存边界。

## 其余通过
实际selector返回run/artifact/algorithm identity进入v2receipt；callback/returned/baseline三方Top10一致；sourceSHA显式且raw/source相等；directfreeze不能伪称COMPLETED；正常封存bytes/selector_result校验通过；外部原source漂移或删除仅external状态DRIFTED/MISSING，本地sealed仍PASS。REAL与自然计数继续blocked。selection.py/ops未变，allowed三文件diff。

## 独立复跑
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_formula_margin_shadow.py stage_center/tests/test_selection_consumer_batch3.py tests/test_stage_scoring.py tests/test_stage_name_read_overlay.py -q --basetemp=/tmp/formula-shadow-r22-review-final --tb=short
62 passed in1.08s。
py_compile core/tests/ops通过。

测试通过不覆盖上述独立反例，所以本批工程FAIL，不宣称自然实验PASS或命中率提升。
