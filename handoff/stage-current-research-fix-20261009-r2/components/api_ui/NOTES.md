# R2 API／现有页面最小接续

本组件交付 6 个完整后像和对应增量 patch。当前 API `app.py` 与 `consumer.py` 的前像来自固定 `41a9242d400acec08af3934d1da314b1626a1bcd` 中的 `active_api_issue32` 源码切片，未使用 r5c 拆分候选。Reader 与三个 Vue／TypeScript 文件在 0fc3 R1 候选后像上继续修改；不把这些候选后像称为 Mac 当前源码。

## 实际修改

- `consumer.py` 保留原 SelectionStore，恢复原 R1 的 `selection_store=self.store` 接线，透传选股原始日期／阶段／市场、研究元数据和原始源码记录。研究来源未确认不会删除已保存选股行。
- `execution_evidence.py` 分别校验原 selection 三件套、owner immutable receipt、研究输入元数据、选股原始源码记录和当前调用源码记录。原结果来源必须与 SelectionStore manifest 相符；当前调用源码不同不会改写原结果来源。所有这些校验仍不构成自然运行或进程验收。
- A 股另将原选股三件套内的 `candidate_run_id`／`candidate_current_sha256` 来源标记与 owner 的 A 输入声明进行日期、run、字节 SHA、完整输入计数比对。成功标 `OWNER_DECLARED_INPUT_BOUND_TO_SELECTION`；未重新读取当前预选池，也不声称历史资格验证。错 SHA／run／日期／216 被截成 200、缺 owner history 或伪造投影标记均不能绑定，原 10 行结果继续可见。
- 当前 `app.py` 的 `_hk_display_mode` 增加显式 `CURRENT_DAY_RESEARCH_ONLY` 分支。研究结果显示选中数量及来源限制，不进入 FORMAL 分支；既有 STRICT 行为保持。原工作台投影透传这些字段，不拆 API。
- 原 `/api/v3/workbench/stage` 可选 `selection_run_id` 与 `market` 在已配置的原 SelectionStore 根内精确只读一个 run。它不接收路径、不更新 latest、不创建 producer、不与 `backfill_run_id` 混用。未知或不合法 run 返回 404，混用参数返回 422。
- 原 Vue 面板分别显示选中数、行情覆盖、run、名单日期、证券资料取得时间、实际选中股行情时间、资格不能确认、研究输入／源码／执行记录状态。`MANUAL_CURRENT_DAY_RESEARCH` 显示为“手动当日研究”，不会显示为 NATURAL。App 中候选栏也显示研究身份，并防止已有历史回补展示覆盖该研究结果。

## 测试范围

`tests/test_current_research_readback.py` 使用真实 SelectionStore、最终 R2 writer、当前 consumer、实际 API 路由函数源码和 Vue SFC。完整链用四个**合成输入文件**与合成外部行情边界：695 个输入、684 个行情、11 个缺失，原算法选出 10 个；不是读取用户 Mac 上四个文件，也不是实际访问 OpenD/PyTDX。最终 runner／算法／存储／同 run API／Vue 路径均执行。API fixture 在 FastAPI 中执行现有路由及投影函数的原 AST body，未启动完整应用的其余路由。Vue 使用真实编译和 SSR，未完成 Mac 浏览器验收。

完整 runner 测试使用 HK 组件已有 `raw_store_test_support.py` 的显式 False-only 适配：仅兼容归档 facade 多传的 `allow_temporal_false_observation=False`，True 拒绝，仍调用原严格 helper。该适配是测试支持，未加入业务后像或部署 patch；当前实际 raw helper 的前像仍需与总交付缺口表核对。

本次 Linux 参考复跑显式设置 `V4_RAW_SIGNATURE_SUPPORT=strict_false`；总包 Mac 独立复跑入口设置 `V4_RAW_SIGNATURE_SUPPORT=disabled`，从实际完整源码运行，不注入此适配。

测试环境由 `V4_API_TEST_RUNTIME` 指向组装的 Stage 候选根；默认 `runtime_after/actual_stage`。`STAGE_UI_RUNTIME` 指向已有含 Vue、@vue/compiler-sfc、@vue/server-renderer 的 Node 项目。运行：

```bash
python -m pytest -q components/api_ui/tests
node --test components/api_ui/tests/legacy_presentation.test.mjs
```

新增 API／reader／原算法／Vue 链用例 25 项通过（含 A 输入绑定 8 项 RED→GREEN）。旧 Reader 28 项与旧 Vue 23 项分别复跑，用于确认已有 owner history／canonical-vs-byte SHA／空值计数语义保留；这些数量不替代现役 API/UI 验收。

## 落地边界

先在隔离 canary 按完整清单组装后像，保持三类输出根与现役隔离；复跑本组件与 Stage 的定向测试。仅当当前 API `app.py`／`consumer.py` SHA 与清单 before 相符时应用其补丁。Reader 与 UI 须核对其当前前像；若还停在 R1 前，应先在隔离候选应用累计 R1+R2 差异。canonical 根已有 dirty，不使用此 actual API 后像覆盖 canonical。

API canary 使用既有 `stage_center_selection_root` 读取此次 Stage 的原 selection 根，并由 existing consumer 配置绑定对应 receipt 根；同 run GET 示例：`/api/v3/workbench/stage?date=20261009&stage=STAGE_1545_1555&market=HK_CONNECT&selection_run_id=<实际run>&limit=50`。现有页面按同日期／阶段普通入口读取该已配置根，与 API 中的 run、raw SHA、算法 SHA 及研究身份比对。完成独立复跑后再使用原发布链；没有修改旧 latest、正式池或发布门禁。

未知当前前像一次集中列于 `MISSING_CURRENT_PREIMAGES.json`。需要的是当前字节与 SHA 核对，不要求 Mac 编写新增业务逻辑。
