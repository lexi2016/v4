# 精确装配与执行前置

本页以原 ZIP 实际成员和 consumer 的 FIXED_CLOSURE.json 为准，不使用此前回复猜出的解压根。这里只记录建议的产品测试命令；本次交接没有执行它们。

## 1. 自动静态装配

在完整交接目录中：

```sh
python3 verify_and_assemble.py
python3 verify_and_assemble.py --destination /绝对路径/新的M13材料目录
```

工具只用 Python 标准库，先核 4 ZIP 的 bytes、SHA-256、Git blob、CRC，以及 301 成员身份，拒绝危险 ZIP 路径与 symlink。目的目录必须全新。解压后把 consumer 的 93 个增补路径复制进原 SOURCE 同一树，保留原 121 个文件字节；最终 SOURCE 214 个文件。再核 consumer 111 件闭包的 bytes/SHA-256/Git blob。结果写入目的目录 ASSEMBLY_RESULT.json。该动作不会导入任何产品模块或运行原 fixture assembler。

若手动装配：将 consumer `v5-m13-readonly-consumer-deps-20261010/overlay/V5` 按相同相对路径并入 `v5-module13-source-20261010/V5`。93 路径在原 SOURCE 均不存在；若实际目录已有同名不同字节必须停，不覆盖。最终 `V5/vendor/manager_plan_baseline/contracts/stages.py` 必须存在。完整映射见 verification/CONSUMER_111_SOURCE_MAP_VERIFIED.json。

## 2. 三个路径各司其职

令 ROOT 为上一步新目录的实际绝对路径：

```sh
ROOT='/绝对路径/新的M13材料目录'
SOURCE_ROOT="$ROOT/unpacked/v5-module13-source-20261010"
REVISION_ROOT="$ROOT/unpacked/v5-m13-fixture-supplement-20261010/e06d-original-fixture"
OFFLINE_ROOT="$ROOT/unpacked/v5-m13-original-offline-fixture-20261010/1a699a0-original-fixture"
export V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE="$REVISION_ROOT"
export V5_ANNOUNCEMENT_OFFLINE_TEST_BUNDLE="$OFFLINE_ROOT"
```

revision 必须是原 e06d fixture，其 owner manifest 为 `da392a57bf93dd9a5b4355d934e267a7c5c4fe495e90779364627e8a8f118d8a`。
offline 必须是原 1a699a0 fixture，其 owner manifest 为 `0ff96e3c5bc48c67fada2b979a9862b7778c9a33c1983cdc0ab180ea85125ab5`。
它们必须独立，不混装 candidate/owner_dependencies 到 V5/vendor，不同时指向 e06d，不改 PIN/manifest 放行。

V5_ANNOUNCEMENT_REQUEST_PATH 是另一类输入，须指向真实已有 request JSON 及其全量绑定原件。它不是代码目录，也不是给本次 22 项分组新造一个 JSON。见 MISSING_REAL_INPUTS.md。

## 3. 原 22 项合成工程分组（NOT_RUN）

原环境合同：Python >=3.14、pandas >=2.3,<3、pyarrow >=21,<25。先记录实际解释器与依赖。此前回复自报 Python 3.13.5 不满足该合同，不能改合同放行。

在既有授权的受支持测试环境中：

```sh
cd "$SOURCE_ROOT/V5"
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python -m pytest \
  tests/test_announcement_analysis_api.py \
  tests/test_manager_announcement_binding.py::ManagerAnnouncementLimitTests \
  tests/test_manager_offline_announcement.py \
  tests/test_daily_revision_chain.py -q
```

22 项 = API 4 + manager 大小边界 3 + transport 6 + offline 原合成 chain 6 + revision 原合成 chain 3。两个原合成 chain 使用真实原 owner 实现处理合成数据，仍不是真实业务验收。

另 20 项 = AnnouncementBridgeTests 17 + ManagerAnnouncementRealOwnerTests 3，使用旧 08/07 的真实 request 与 758 件原件；该输入已在后续独立原件包找到并核验，但未纳入本工程 commit。整五文件共 42 项，不能把整套自报结果当作上述 22 项已正确执行。缺变量导致 skip/error 不算通过。

此前回复自报 `18 failed / 12 passed / 6 skipped / 6 errors`，没有提供完整原始日志；已识别的装配问题是未设置 REVISION_TEST_BUNDLE、未把 consumer overlay 装入同一 SOURCE。这里只核实材料事实，没有复现该自报测试结果，也不预判修正装配后一定通过。

## 4. 回交要求

每次执行都交完整 cwd、Python/依赖版本、两个 fixture 实际绝对路径、源包/候选 SHA、命令、exit、完整 stdout/stderr。缺件时保留实际异常栈和路径；区分装配错误、源代码缺陷、真实输入未取得。若产品失败才按精确 before 做最小改动，保留完整 after、正反 diff、前后 SHA、测试和 Mac 验收/回滚步骤。真实 10/12 owner/API/UI/自然运行仍单列 NOT_RUN，不能由合成工程结果替代。
