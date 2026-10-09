# Mac 落地与回滚

## 适用前像与发布关系

生产增量仅为 `apps/web/src/api/managerWorkspace.ts`。前像必须是 SHA256 `35a879624032cfffb1c3e4afba3c4ae6298df7d5dffb5db90d9ad42142f496ee` 的已集成候选；后像为 `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f`。`6bd208…` 是现役参考，不是本补丁前像。

经理与阶段仍共用 API 进程及页面发布入口。沿用已经核对的共享入口和 owner 绑定，在新的候选目录集成本单文件增量。保留旧失败候选及原回滚目录，以新的源码、构建产物和发布清单生成新的回执。

## 1. 准备新候选并核对

用本机现有准备工具从已集成候选构建新的可写隔离副本；本包不操作现役服务。以下 `REPAIR_APP` 是这个新副本的 `app` 根目录，不能填现役 `/Users/lexi/Desktop/学习/v4_app`。先把三个路径设置为本机实际位置：

```sh
REPAIR_PACKAGE="/absolute/path/manager-validator-restoration-20261009-r1"
REPAIR_APP="/absolute/path/new-validator-candidate/app"
REPAIR_RESULTS="/absolute/path/new-validator-review"
mkdir "$REPAIR_RESULTS" && \
python3 "$REPAIR_PACKAGE/tools/verify_delivery.py" --source-root "$REPAIR_APP" --expect before && \
git -C "$REPAIR_APP" apply --check "$REPAIR_PACKAGE/runtime.patch" && \
git -C "$REPAIR_APP" apply "$REPAIR_PACKAGE/runtime.patch" && \
python3 "$REPAIR_PACKAGE/tools/verify_delivery.py" --source-root "$REPAIR_APP" --expect after
```

任一步退出码非 0 即保留错误并停止本次应用。前像不符时，核对实际候选来源；不要把现役参考整文件覆盖回来，也不要对漂移源码强制重放补丁。

## 2. 测试资产和命令

`tests/` 下目录可覆盖到新隔离副本的 app 根目录。它只包含原 spec/fixture、测试辅助文件及本轮新增 8 项共存测试。原 76/25 测试必须与包内 SHA 一致。Python 辅助文件仍调用新候选的原 owner，在临时目录生成合成输入；不读写现役业务状态。

```sh
cp -R "$REPAIR_PACKAGE/tests/." "$REPAIR_APP/"
export V4_TEST_SOURCE_ROOT="$REPAIR_APP"
export V4_TEST_CACHE_DIR="$REPAIR_RESULTS/vite-cache"
export V4_TEST_PYTHON="/Users/lexi/Desktop/学习/v4_app/.venv/bin/python"
export PYTHONDONTWRITEBYTECODE=1
NODE_BIN="/Users/lexi/.local/node-v24.19.0/bin/node"
WEB_MODULES="/Users/lexi/Desktop/学习/v4_app/apps/web/node_modules"
cd "$REPAIR_APP/apps/web"
```

使用本机已经通过验收的 Node/Vitest 依赖；必要时将 `NODE_BIN`、`WEB_MODULES`、`V4_TEST_PYTHON` 改为实际路径。新副本中 `node_modules` 应由现有准备流程指向这套依赖。Python 需要 pandas、pyarrow、pytest；本包附测试源码，不要求重建本机环境。

原 76 项：

```sh
"$NODE_BIN" "$WEB_MODULES/vitest/vitest.mjs" run --config "$REPAIR_PACKAGE/tools/vitest.config.mjs" src/manager-selection/__tests__/issue8R2.spec.ts --reporter=verbose > "$REPAIR_RESULTS/issue8R2.log" 2>&1
```

原 25 项，两个 spec 必须同次执行：

```sh
"$NODE_BIN" "$WEB_MODULES/vitest/vitest.mjs" run --config "$REPAIR_PACKAGE/tools/vitest.config.mjs" src/api/managerWorkspace.threeChannel.spec.ts src/api/managerWorkspace.dailyAutomation.spec.ts --reporter=verbose > "$REPAIR_RESULTS/adjacent25.log" 2>&1
```

新增 8 项：

```sh
"$NODE_BIN" "$WEB_MODULES/vitest/vitest.mjs" run --config "$REPAIR_PACKAGE/tools/vitest.config.mjs" src/api/managerWorkspace.validatorRestoration.spec.ts --reporter=verbose > "$REPAIR_RESULTS/coexistence8.log" 2>&1
```

类型检查：

```sh
"$NODE_BIN" "$WEB_MODULES/typescript/bin/tsc" --noEmit --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM,DOM.Iterable --skipLibCheck src/api/managerWorkspace.ts src/manager-selection/researchAttention.ts > "$REPAIR_RESULTS/typecheck.log" 2>&1
```

四条命令应分别退出 0；结果分别是 76、25、8 项通过，以及类型检查无错误。保留每条原始日志及实际环境。需要复现失败对照时，另建前像副本，使用同一展示依赖和同一批测试，原 76 项应为 31 通过、45 失败。`test_support/researchAttention.active-api.ts` 仅用于解释/复现本轮 Linux 支撑，不覆盖 Mac 已集成的生产展示代码。

## 3. 共享入口发布前验收

在已有发布流程内完成新前端构建及清单，不沿用旧 dist 或旧 manifest 身份。重新核对共享 API 根、绑定、版本和页面产物；保持原 Stage 路径及选股算法，并从同一页面入口检查以下行为：

- 经理页正常读取日期绑定、三通道结果及入选理由；未知输入数量显示未知，真实已核空集仍可显示零。
- 公告独立观察和来源诊断正常可读，非法数据由原验证函数拒绝；“观察”身份、资格未核原因和 PIT 缺口继续可见。
- 阶段页面及日期/阶段导航仍读取预期接口和既有结果；不把三通道前端通过等同于阶段选股恢复或真实数据缺口关闭。
- Mac 对本轮最终源码、构建及共享入口独立复核通过后，按既有发布授权切换，读回实际 API/UI 身份；自然时段调度证据另外记录。

本轮 Linux 没有构建实际 Mac 发布副本，也没有执行这组发布/API/UI/自然运行验收。冻结 Mac 全矩阵的 14 项既存失败保持记录；本单文件修复没有宣称关闭它们。

## 4. 回滚

未切换时，保持当前现役服务，把新候选保留为返修证据即可。需在新候选上撤销本增量时：

```sh
python3 "$REPAIR_PACKAGE/tools/verify_delivery.py" --source-root "$REPAIR_APP" --expect after && \
git -C "$REPAIR_APP" apply --reverse --check "$REPAIR_PACKAGE/runtime.patch" && \
git -C "$REPAIR_APP" apply --reverse "$REPAIR_PACKAGE/runtime.patch" && \
python3 "$REPAIR_PACKAGE/tools/verify_delivery.py" --source-root "$REPAIR_APP" --expect before
```

这会恢复失败集成候选的精确前像，不能把它作为可上线版本。若此后已经部署，需要沿用本机现有的完整发布回滚机制，恢复原可用服务与相配套的页面产物，并重新读回版本；不在正在服务的源码/产物上单独逆补丁。
