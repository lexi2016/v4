# M17验收与回滚

本清单待执行。状态统一为：代码接入、真实数据通过、页面可用、自动接续、完整验收。工程测试单列证据，不替代真实数据、页面或自然接续。

## 原回归

完整隔离原闭包内保留以下测试；本包只读，未运行：
- tests/test_manager_materializer_rework.py：单原bridge调用、真实artifact与ASGI读回、失败非零候选成功、late不抓不回填、迟返回不当1530、错日拒绝、mandatory root/origin、prior完整B1验证
- tests/test_manager_r2_rework.py：币种单位不猜、原amount严格边界、snapshot/universe/hash绑定、重复quote、原新催化PIT、旧时间不充新催化、弱prior拒绝、新失败/运行不显示旧卡片、数值bool不冒predicate
- tests/test_manager_workbench_research_router.py：exact date/market/slot、pending/not-run/input-missing不同、future/nested/safety/schema拒绝、全predicate真才qualified、显式null保留、读路由零写
- tests/test_manager_close_executor_rework.py：1500前置、1530超时不越过15:32排他截止、late PyTDX不写1530
- tests/test_stage_jobs_manager_close_recapture.py：1555原recapture及store读回、Stage失败不妨碍独立late尝试且不升级Stage、late模式不启1530/1500
- 1530 V3 rebound及持续跟踪的额外原回归按完整闭包找齐；不把M14两门测试当本模块全覆盖。

新增V5 test_close_discovery_daily.py：同身份并发/重试、snapshot/history/receipt任一漂移、错mode、late/current/previous session边界、前成功保留、请求发生真实时点、纯GET零写、跨日prior更新/缺失、M14/Stage身份与输出根不混。测试命令、解释器、fixture与真实输入分别标注；旧总测试数字不得替当前固定回归。

## Mac真实业务与页面

1. 核实际运行mode、唯一采集owner、固定源码SHA、真实root/日历/资格/历史/新闻binding，保存V4及M14/M16/M18摘要。不得凭源码默认值启用另一mode。
2. 若现场模式，用真实1530输入且actual available<15:32，原pre-capture history及资格当时可用，计算→receipt→独立readback同run/SHA。无历史窗口则NOT_RUN/错过，不改clock补。
3. 若late模式，保留15:45—15:55原窗口、source_trade_date、next plan_trade_date、actual captured_at、received_not_historical_1530，1530根字节不变。100条覆盖是原合同要求，不可用默认100伪装实际完整；缺量纲/最终收盘仍明确。
4. 对下一适用日持续跟踪，原verified prior链保持、首次时间不重置、原新增催化/失效规则生效。缺上游正确阻断，旧成功只作为明确历史。源/产物/前后跟踪SHA均记录。
5. 真实V5浏览器查看经理尾盘/持续跟踪区，切日、1530/recapture区别、展开理由/缺口/失效条件、刷新、返回与重复动作。页面与API同identity；普通GET零collector/zero write。记录实际URL、代码/生成版本、截图。
6. 按当前原合同自然触发与跨日自动更新，人工恢复不冒自然。P5连续适用日要求仍保留；周末/缺窗口不能即时签全完成。共享回归与预览发布由唯一集成者执行。

## 回滚及反馈

仅发布M17自己的代码/worker与generation；预存旧指针并用平台expected-generation/CAS，先核进程真实身份。失败只恢复M17旧binding/引用，保留所有snapshot/history/attempt/成功/跟踪证据；不删除窗口文件、不回滚Stage/M14、不触动V4。不让新旧两个worker同写运行根。

回同一Chat：固定commit/patch SHA、mode、source/plan日期、window/capture/available时间、输入/历史/产物/prior SHA、原错误码与完整非秘密日志、API/UI和其他模块不变量、回滚状态。真实证据或活动绑定缺少明确BLOCKED，不能以文件存在或HTTP200算完成。
