# 离线复现与来源核对

本文件不授权实际 owner capture/import、访问现役 8873、部署或服务操作。所有测试应在隔离源码副本和临时合成数据目录中执行；本轮实际命令见 `evidence/final-validation.json` 和 `evidence/final-command-records.json`。

## 源码装配

固定仓库 `lexi2016/v4`、基线 commit `c0fc35c7b39502f49e43c2e75139dad7822091cf`。本次测试不是一个完整 Mac checkout：使用固定 Git 的支持源码，覆盖输入 ZIP 中 25 个 `current_fused_app` 文件，再核对 identity reader 链与每个前像。缺失的 `existing_materials.py` 按报告 SHA 从该 commit 的 API 源码快照恢复。30 个导入辅助 `_namespace.py` 作为 **TEST_ONLY_IMPORT_ADAPTATION** 明列，不能作为 Mac 源码身份。

`support/TEST_SOURCE_INVENTORY.json` 给出测试前像的相对路径、SHA、固定 Git 路径或上传包路径；`support/FINAL_TEST_SOURCE_SHA.json` 记录最终实际测试集合。原 Issue8R2 spec 和 ownerObservations fixture 均按固定 Git 原字节恢复，引用见 `support/REGRESSION_REFERENCES.json`。4 个本轮新测试以相同字节加入两侧，候选额外有 1 个生产 helper，因此最终基线 1076 文件、候选 1077 文件。

`PATCH.diff` 只包含 9 个生产路径，不包含测试支持、Stage、BUY、服务或数据改动。`after/` 为这 9 个文件的完整源码，`regression/` 为 4 个新测试。不要把整个测试支持目录覆盖到 Mac canonical。

## 运行环境

实际 Linux Python 3.12.14，项目要求 >=3.14：**NOT_MET**。Python 的31个锁定依赖均与原 `uv.lock` 匹配，具体版本与锁文件 SHA 在 `environment/runtime.json`。原引用的旧虚拟环境 executable 已不存在；本轮实际使用任务专属 venv 和已保留的锁定依赖，见 `environment/runtime_setup.json`。不能称生产环境完全复现。

Node 24.19.0，Vitest4.1.10、Vue3.5.40、Vite7.3.6、TypeScript5.9.3、jsdom28.1.0。当前导出没有 package-lock.json；记录的是实际已安装版本，未补造 npm 锁文件。无需为复现更改全局环境或账号权限。

以下环境变量均由运行者指向**本机的隔离副本/已安装依赖/临时测试目录**：

```bash
export V4_CANDIDATE_ROOT=/path/to/isolated/candidate/app
export V4_HANDOFF_ROOT=/path/to/manager-live-ui-api-repair-20261010-r2
export V4_TEST_PYTHON=/path/to/test/python
export V4_TEST_NODE=/path/to/node
export V4_TEST_DEPENDENCIES_ROOT=/path/to/node_modules
export V4_TEST_EVIDENCE_ROOT=/path/to/temporary/test-evidence
```

候选 apps/web 必须能解析同一套依赖。`tools/vitest.handoff.config.mjs` 是最终实际 Vue-enabled 配置的可移植等价版：仅将硬编码依赖路径改为上述环境变量；不是应用配置或第二页面。

## 1. 只读文件核对

```bash
cd "$V4_HANDOFF_ROOT"
"$V4_TEST_PYTHON" -B tools/verify_handoff.py
"$V4_TEST_PYTHON" -B tools/verify_handoff.py --target-root "$V4_CANDIDATE_ROOT" --target-state after
```

在合并前可使用 `--target-state before`。尤其需要核对只有 fixed-Git 前像的 `archive_catalyst_inputs.py`，以及新增 helper 的目标位置是否已有并行文件。该脚本只读；任何不匹配都保留并交主控协调，不能盲目覆盖。

## 2. 后端56项与六个真实合成 DTO

```bash
cd "$V4_CANDIDATE_ROOT"
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$V4_CANDIDATE_ROOT" \
PLAN_AUDIT_APP_ROOT="$V4_CANDIDATE_ROOT" \
TASK1_BACKEND_FIXTURE_ROOT="$V4_TEST_EVIDENCE_ROOT/backend-ui-fixtures" \
"$V4_TEST_PYTHON" -B -m pytest tests/test_manager_semantic_identity_20261010.py \
  -vv --tb=short -p no:cacheprovider \
  --basetemp "$V4_TEST_EVIDENCE_ROOT/backend-focused-tmp"
```

测试通过实际 `ManagerResearchJobService` 和 manager router/TestClient 生成完整 DTO，原始 reader 在临时合成 owner roots 上读文件；网络连接被禁止。不是完整 `create_app` 或实际 Mac owner。fixture 中 `available_at` 非法扩展被原 schema 拒绝的情形明确保持拒绝，未改字段合同。

生成6个文件：`manifest_only_match.json`、`materialized_catalyst_manifest_only_match.json`、`consumed_content_changed.json`、`consumed_availability_rejected.json`、`legacy_missing_components.json`、`date_bindings_changed.json`。它们由测试重新生成，不在 Git 中重复上传大体积响应。未设置下一节的 fixture 环境变量时，前端跨语言用例会明确 skip；不能把 skip 称作通过。

## 3. 前端44项与原76项安全回归

```bash
cd "$V4_CANDIDATE_ROOT/apps/web"
V4_TEST_SOURCE_ROOT="$V4_CANDIDATE_ROOT" \
V4_TEST_CACHE_DIR="$V4_TEST_EVIDENCE_ROOT/vite-focused-cache" \
V4_BACKEND_UI_FIXTURE_ROOT="$V4_TEST_EVIDENCE_ROOT/backend-ui-fixtures" \
"$V4_TEST_NODE" "$V4_TEST_DEPENDENCIES_ROOT/vitest/vitest.mjs" run \
  --config "$V4_HANDOFF_ROOT/tools/vitest.handoff.config.mjs" \
  src/api/managerWorkspace.identityDiagnostic.spec.ts \
  src/manager-selection/catalystObservationPanel.liveRepair.runtime.spec.ts \
  src/manager-selection/catalystObservationPanel.backendDto.runtime.spec.ts \
  src/manager-selection/__tests__/issue8R2.spec.ts
```

当全部旧 fixture 按清单在位时，本轮最终候选上述44+76用例全部通过。原76文件没有修改；它不能用同名新写的安全测试替代。实际 panel mount 测试验证三路卡片、三种日期、来源显示、US局部范围、201行完整审计、取消/过期响应和 canonical GET；jsdom 不等同真实浏览器视觉验收。

## 4. 全套测试、类型检查与构建

后端实际执行完整 testpaths，并使用 `--continue-on-collection-errors` 展开未被缺失模块阻断的测试：

```bash
cd "$V4_CANDIDATE_ROOT"
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$V4_CANDIDATE_ROOT" \
PLAN_AUDIT_APP_ROOT="$V4_CANDIDATE_ROOT" \
"$V4_TEST_PYTHON" -B -m pytest --continue-on-collection-errors \
  -p no:cacheprovider --basetemp "$V4_TEST_EVIDENCE_ROOT/full-pytest-tmp"
```

前端实际执行 `npm test -- --config ...`，使用相同 Vue 配置、Python runtime 和六个 DTO 的环境变量；随后分别执行 `npm run typecheck`、`npm run build`。基线与候选命令完整列在 final-validation 证据中；更换为基线源码根即可对照，不能混入候选生产代码。

完整项目仍有失败。缺失的 `stage_center.research_read_binding` 等源码、Mac owner fixture 和完整前端入口没有临时伪造。裸 pytest 的8个 collection errors、继续运行后的全部失败标识、4个前端 load failures、3项类型错误和实际 build错误均保留。修改范围单独严格 tsc 通过，不代替全项目结果。

## 5. 独立探针

`independent_checks/test_independent_catalyst_registry_only.py` 是初次审查发现额外 P2 的原探针，未改断言；候选修正后通过。`test_final_review_bound_late_input.py` 通过原 reader 验证真实合成材料变化后的 catch-up，避免仅依赖直接改身份的旧夹具。

设置 `PLAN_AUDIT_APP_ROOT`、`PYTHONPATH` 为隔离候选，使用上述 Python、独立 `--basetemp` 执行这两个文件即可。第二探针在基线和候选各1PASS；它不等于非空催化/PIT或自然运行验收。

本包保留 full-suite 旧 late-input 夹具的 FAIL：它只改最终 `input_identity`，未更新新分量元数据。独立绑定输入对照证明原 catch-up 在有效输入下仍生成新计划、CURRENT读回并保留旧盘前字节。缓存15ms TTL在并行全套中失败、顺序复核通过，两个结果均保留。旧POST响应复用与缺省日期二次GET断言也未改写；当前页面按显式日期读取所选canonical响应。
