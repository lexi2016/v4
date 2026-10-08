# Luna Max 落地与独立验收顺序

本包是冻结源对应的候选增量，不是完整可部署 app。Luna Max 负责 Mac Writer
适配；不同身份 Reviewer 在候选完成后独立复验。保留原失败目录、回执及冻结分支。

## 1. 精确前像与独立候选

先核本包清单，再分别核实际 API、Stage、池 scheduler 的前像和加载模块。
前像不匹配时停止该批应用并记录差异；不强行 patch、不复制 canonical 覆盖单文件
运行版。各批 `after/`、patch、完整前后 SHA 见对应目录。

竞价只有两种 builder 后像和共同 selector 后像。runner 与持久化 schema/codec
没有改动；构建时只更新确实改变字节的执行文件身份合同。不得复用 #23 旧 runner pin
或刷新未变更的其他 pin 来通过校验。

## 2. 发布工具先独立验收

执行 `release/` 内的原 26 项及新增故障用例，使用临时文件目录和受控服务探针。
确认 guard 的精确 SHA 同时绑定安装 scope、计划、恢复 identity 与 review，且加载的
正是已校验字节。验证双 link 失败后能凭结构化 claim/回执定位原字节；出现他人 active
文件时拒绝覆盖。详细命令和新合同字段以 `release/RELEASE_REPORT.md` 为准。

旧 finalplan 和旧审查 FAIL 保留，不执行。针对届时实际 API 准备新的完整候选及计划，
按新合同完成独立审查后再进入安装；离线测试通过不等于实际服务恢复或部署验收通过。

## 3. A 预选池与竞价分批验证

复用已有 A 池读取修复，保持最新经理台更新。完整候选运行 `pool/README.md` 的测试，
隔离 canary 验 10/8 的 178 唯一 A 与 100 独立 HK；hash 核对来源三件套未变。

竞价先用 `auction/` 中 100／105 与缺基准 fixture 走真实 adapter、selector、
SelectionStore、consumer，再执行完整 API 路由验收。百分比应为 5%；缺基准为 null
并有缺失原因。恢复真实基准可以改变竞价分数及排名，详见该批语义证据。
不重跑或覆盖已保存的 10/8 结果；需要观察新结果时使用原合同允许的新候选运行身份。

## 4. HK 补齐实际生产依赖后做一个 canary

先完成 `OPEN_ITEMS.md` 和 `hk/` 指出的 actual owner 文件、参数、SHA 与来源核对。
使用原 shared owner、两个真实日期及新隔离输出目录，生成并读回合法三件套；
原严格 validator 应接受合法输入，拒绝旧日／缺来源／取得时间不合格的输入。

精确 Stage 命令由 Luna Max 读取当前 `com.lexi.stage-center.scheduler` 实际入口后
按原单阶段调用合同执行；本包不猜测未提供的启动参数。先一个阶段，核输入与输出
run/artifact/SHA，再扩大日期／阶段。真实无候选与输入缺失分别验收。

## 5. 分开验 API、重载页面、自然时段

- API：原 8873 入口，核日期、阶段、A/HK 独立计数、昨收/涨幅/null 原因、同一 run/SHA。
- 重载页面：`http://127.0.0.1:8873/?date=20261008&stage=STAGE_0935_0940`，核选择不重置、
  结果及缺失态一致。页面操作不使用“强制重新物化”来代替只读核验。
- 自然时段：由原 scheduler 留存不可变输入/代码/配置/执行原件，独立证明真实时钟
  与自然触发。RECOVERY、手动 canary 和离线测试不计自然验收。

## 回退

尚未部署时丢弃新候选即可，保留源码和失败证据。已进入经审安装后，必须使用新
release 恢复合同核身份：active 属于预期候选时按其受保护路径回退；active 缺失且
存在本次可校验 claim 时按结构化回执恢复；active 被其他发布改变时拒绝覆盖并交协调。
不使用无条件复制 plist、强制替换 symlink 或旧 finalplan。

始终保持 `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false;
orders_sent=false`。不变更原业务数据、Vibe8910、模型或 BUY。
