# 实际验证命令与结果

解释器统一 `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`，业务 Python 使用 `-B`。以下 Python 命令均在隔离 worktree 根执行；前端命令在该 worktree 的 `apps/web` 执行。无部署、服务启停、提交或推送命令。

```sh
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m pytest -q -p no:cacheprovider --basetemp /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/pytest-final-tmp tests/test_ui_six_fixes.py
```

该早期日志前七项通过，第八项测试 fixture 初始缺字段；保留原失败。后续只增量检查受影响部分，不重复已通过范围：

```sh
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m pytest -q -p no:cacheprovider --basetemp /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/pytest-pool-tmp-r3 tests/test_ui_six_fixes.py::test_bad_pool_isolated_and_wrong_pool_date_sha_never_create_names
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m pytest -q -p no:cacheprovider --basetemp /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/pytest-router-tmp tests/test_ui_six_fixes.py::test_runtime_router_binds_optional_us_reader_without_rebinding_main
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m pytest -q -p no:cacheprovider --basetemp /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/pytest-idempotent-tmp tests/test_ui_six_fixes.py::test_display_registry_is_separate_exact_date_verified_and_immutable
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m pytest -q -p no:cacheprovider --basetemp /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/pytest-authority-repair-tmp tests/test_ui_six_fixes.py::test_missing_corrupt_or_wrong_date_display_registry_never_blocks_pool_projection
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m pytest -q -p no:cacheprovider --basetemp /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/pytest-shape-final-tmp tests/test_ui_six_fixes.py::test_nonobject_registry_shapes_are_store_errors_with_hash_pins_and_nonblocking_projection tests/test_ui_six_fixes.py::test_malformed_row_text_fields_fail_before_projection
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B -m pytest -q -p no:cacheprovider --basetemp /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/pdf_night/pytest-tmp tests/test_pdf_night_window.py
```

分别 PASS 1、1、1、3、20、13；结合复用的原检查，业务 Python 为 32 + PDF13 个唯一测试。

```sh
npm test -- tests/ui-six-fixes.spec.ts src/api/pool_stage.spec.ts src/components/research/ResearchFeedCard.spec.ts
npm run typecheck
npm run build
```

最终 actualAPI 前端基线：19 tests PASS，Vite build PASS；typecheck FAIL30，全部是未改动实际基线来源，逐项原文件 SHA 已保存。

```sh
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B /Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027/verify_candidate_read.py
```

原有效只读回放 PASS90/90、200/200/82、零非显示差异；首个 StoreError 修复及最终 loader 形状修复只改变损坏路径，该成功路径证据复用，没有重采或重复业务回放。原 SDK/BSE/网络错误与 superseded 前端构建均保留。
