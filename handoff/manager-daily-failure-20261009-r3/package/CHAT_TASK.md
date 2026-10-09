# Chat 任务：修复经理每日研究计划 owner 路径

请以本包分支父提交 `66bb05a2e12976775ccb997191ce943bae8cc9a5` 及实际最新共享 owner 变更为输入，在隔离代码分支完成最小代码修复、针对性测试和 Mac 交接。目标是恢复原有每日运行路径，不新增 producer、scheduler、automation、面板或数据底板。

## 已确认的输入和代码边界

- 两次顺序只读 API 响应：20261008 选股/公告日绑定与 20261009 plan date；以及 20261009 当日绑定。两者均 `plan_product=NOT_MATERIALIZED`、`run_id=null`，`us_mapping_research.daily_run=NOT_RUN`。见 `../evidence/live_get_projection_20261009.json`。
- 当前 scheduler binding `c0fbff52449eb5dbf5c1655f17cf08915bea1214f9499cc8a4df1176d9625951` 为 enabled plan-only，`plan_material_refresh.enabled=true`。bound worker root 为 `manager-us-mapping-daily-20261006-r2/app`，cycle SHA 与 plist pin 一致。activation canary 是 `hook_executed=false`，不代表 10/9 已运行。
- 现役 API 的 `V4_MANAGER_PLAN_OWNER_BINDING_PATH` 指向 C1 binding，SHA `f3b7cbfa1709b2b27816d294e599cb1ae82ff918ba41ec148644f1a1751f5fd6`，`enabled=false`，app root 不是现役 Issue32 API root。worker cycle 通过 `request_bound_plan_cycle` 把调度 binding SHA 发到 8873；API 先比较 SHA，再验证 app root 与 enabled。静态首个门是 `PLAN_OWNER_BINDING_SHA_MISMATCH`，但实际 dispatch 状态 `CANNOT_CONFIRM`。
- US 10/8、10/9 04:15 源采集成功与 daily mapping/product 分开；当前 daily run 仍 `NOT_RUN`。公告 `NOT_IMPORTED`/`NOT_RUN`；HK authority diagnostic 为 `HK_UNIVERSE_V2_ARTIFACT_MISSING`。超跌 `StoreError` 是 10:53 用户现场报告，11:00 投影只确认 `market_screen=CANNOT_CONFIRM`。不得把不同输入阻断统称为一个 R2 逻辑缺陷。
- R1/R2 候选已有独立 PASS，仅覆盖隔离 API/web 与合成/本机行为；HK supplement 行为测试有一个 P2 `CANNOT_CONFIRM`。现场 API 经理路径仍是 R1 before。
- Issue32 保护路径：`apps/api/v35_api/app.py` SHA `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`、`preselection_router.py` SHA `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae`、`preselection_service.py` SHA `cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044`。不得用旧整包覆盖。

## 目标行为

1. 对 20261008 事后计划：只有合法输入齐备且原 owner 实际保存了产物时，才要求可追溯的日期、市场、输入来源/SHA、cutoff、owner、run_id 与 product SHA；用显式 `view=dynamic` 读取该事后产物。保留普通 `view=auto` 既有的历史资格和读回规则，不要求它切换或消费这次事后 run。
2. 对 20261009 当日计划：若当日计划已保存，正常 `view=auto` 必须读回同日期、同 run_id、同 product SHA 与同输入身份；不能临时重算成另一个 run，也不能以 HTTP 200 代替语义成功。
3. 每个日期的产物都以合法输入可用为条件。缺少合法输入时，保留 `CANNOT_CONFIRM` 与具体缺失原因，不强制生成 run_id、product SHA 或股票名单，不造零结果、旧日期 fallback 或虚构名单。输入完整且实际合法筛选得到零只股票时，允许保存可追溯的空结果，记录输入、cutoff、owner、run_id、product SHA 和筛选原因。
4. 对实际入选股票，显示来自已验证合法研究通道、并绑定到同日期/source/run/证据的逐股理由；无证据的通道独立显示 `NOT_RUN`、`NOT_IMPORTED`、`CANNOT_CONFIRM` 等真实状态。不得把源采集成功等同于 daily mapping、计划或选股结果。
5. 修复配置身份/owner 调用路径的代码与契约，使 scheduler 传入的 binding、API 侧校验根和 owner binding 同一版本，并能安全区分未触发、输入未就绪、门禁拒绝与 owner 失败。继续沿用共享发布 owner。

## 实施与交接边界

- 只提交隔离分支代码与有意义的回归测试；用合成 fixture 验证 SHA/root/enabled 门禁、调用失败路径、20261008 事后产物的显式 dynamic 读回与 auto 历史资格、以及 20261009 已保存计划的普通 auto 同 run 回读；覆盖缺失合法输入与合法空结果。fixture 只证明合同，不代表真实两日产品已生成；真实产品待 Mac 执行验收。保存现存失败和 CANNOT_CONFIRM，不扩成全仓测试。
- 不触发真实 owner POST，不补采，不生成 live plan，不读写实际 plan/state，不重载、重启或发布服务，不改 LaunchAgent、automation 或生产配置；不发真实交易。
- 不迁移 V3/V3.5，不引入新来源/producer/前端，不重写整个 API 包。保留 Issue32 三个保护文件 SHA；必要共享路径按原 owner 最新 before SHA 做最小增量。
- 回交：最小 diff、文件前后 SHA、复现命令/实际结果、测试环境、全部研究安全 flags，以及 Mac 集成 owner 可执行的安全交接说明。区分 `IMPLEMENTED`、`TESTED` 与未执行的 `INTEGRATED/DEPLOYED/API/UI/NATURAL`。

## Chat 分支验收（代码与合成 fixture 合同）

- 合成 fixture 只证明合同：10/8 保存的事后产物由显式 `view=dynamic` 读回，普通 `view=auto` 保持原历史资格；10/9 只有在当日计划保存后才要求普通 `view=auto` 读回同 run/SHA/输入身份。
- 合成 fixture 覆盖合法输入缺失时 `CANNOT_CONFIRM` + 原因且不要求 run/SHA/股票，以及合法完整输入经筛选得到零只股票时可保存可追溯空结果；逐股理由与独立通道状态也有针对性检查。
- 模拟 binding SHA、API root 或 enabled 不一致时，owner 调用以稳定原因拒绝且不会保存成功计划；调度与 API 对同一 binding 身份契约有正向测试。
- Issue32 三个文件 SHA 不变；安全 flags 全部保持研究模式。
- 这些 fixture 和代码测试不证明真实的 20261008/20261009 计划已生成或被 API 读回；不触发真实 owner POST 或生成 live plan。

## Mac 实际业务验收（待共享 owner 执行）

- 对 20261008，若合法输入可用并已保存事后产物，使用显式 `view=dynamic` 验证其来源、run、product SHA 与理由；不要求普通 `view=auto` 消费该事后 run，原历史读回资格保持不变。
- 对 20261009，若当日计划已保存，验证普通 `view=auto` 返回相同日期、run_id、product SHA 和输入身份。若任一日期缺合法输入，保留 `CANNOT_CONFIRM` 与缺失原因；若输入完整且实际筛选结果合法为空，接受可追溯空结果。
- Mac 集成、实际 API/UI 与自然时段结果由共享发布 owner 分别验收，并单独报告 `INTEGRATED/DEPLOYED/API/UI/NATURAL`；不以合成 fixture、HTTP 200 或文档代替。
