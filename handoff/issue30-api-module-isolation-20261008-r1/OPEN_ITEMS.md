# 未闭环事项与证据层级

以下事实来自 Issue #30 固定交接及本次实际源码验证。时间不同、owner 不同和验收层级不同的结果不能互相替代。表内“需求 R1–R6”沿用原问题包的需求编号，与独立审查报告的发现 R1–R7 分别记录。

| 项目 | 已完成或已知 | 当前尚缺的闭环 |
| --- | --- | --- |
| 需求 R1-R3 模块覆盖/旧包自洽/基线漂移 | active + module delta、严格 ownership、文件及目录保留、build/prepare/actual 写前验证的源码候选；最终审查和测试见本包 | Mac 完整 active 闭包集成、真实 candidate 构建、安装与实际切换 |
| 需求 R4 共享发布锁 | 所提供实际 R2 入口及其 execute/rollback/恢复代码持同一 API 指针锁；guard 固定路径/SHA | 全机所有其他 publisher 的实际接管/退役，不遵守 flock 的旧写者不会自动被阻止 |
| 需求 R5 联合验收与身份 | 精确 R2 app 单文件前像、非预选 statement/经理装配字节证明；聚焦 API 测试 | 完整当前 create_app、经理公告/日期/workspace行为、A178/HK100真实源 canary、真实加载身份 |
| 需求 R6 owner 与临时发布者 | 模块/共享装配/发布工具/实际入口归属表与受保护接口 | 当前其他入口安装状态及新恢复 release 的具体 plan/pins；原 R2 脚本不能直接发布新版本 |
| 预选池读取回归 | 来源参数、空本地池修复，router/service 提取及限定旧 SHA 错误隔离；源字节保持的合成回归 | 真实源根和最新实际依赖版本；页面尚未由本环境证明恢复 |
| HK 10/8 阶段输入 | Issue #30 仍报告 signal_date 9/30，缺合格 10/7 价格信号与 9/30资格分日期绑定 | 找回合法源并按真实日期/来源验证，不能改日期标签或删 validator；Stage实际恢复未执行 |
| HK 来源 trio | 上游 artifact/manifest/receipt 已找回；后续 Mac 两 owner 各15/15为合成闭包验证 | 目标 payload 上游 SHA 绑定、合法日期证据，以及 10/7 close 指向的独立底层来源缺口 |
| A09:25昨收/涨幅 | #28 上午 raw171行有昨收，adapter/schema缺字段；已有修复候选属于此前交付 | 未取得后续 Mac 发布/API验收；100→105持久化回读必须为5%，缺基准保持null；不称本轮晚间已复现 |
| A覆盖/研究字段 | 上午178请求缺6–7行情行；研究/新闻与quality合同尚未闭环 | 明确逐行来源与权威字段owner，缺值不填0、不擅自alias评分 |
| 历史两项P2 | 用户已报告 canonical Mac集成、独立38/38；固定记录4c921878 | 部署与实际运行验收未执行；不能重复称这两项未实现 |
| 嵌套历史P2/历史重建 | 嵌套未知字段约束未解决，历史数据未重建 | 独立修复与历史/PIT验收；本包不修改历史文件 |
| 自然时段/不可变身份 | 个别结果与NATURAL声明、10/7 HK10/100局部观察存在 | 独立自然验收和逐run不可变manifest/代码身份；手工/离线不能替代 |
| 旧UI与其他Issue | #21深链接当天已可选日期/阶段；#10/#11/#23有各自时间范围 | 未重验项保持未重验，不全部计作本次现象 |

来源：[Issue #30](https://github.com/lexi2016/v4/issues/30)；[原冻结交接](https://github.com/lexi2016/v4/tree/a0a0b88dc133d14ee5763569272c174bcd7cc445/handoff/api-module-release-20261008)；[历史 P2 Mac 交付](https://github.com/lexi2016/v4/blob/4c9218789fe320dd42c1946e5dfb5161d8f8ed2a/handoff/issue28-historical-p2-mac-20261008/README.md)；[HK trio Mac 交付](https://github.com/lexi2016/v4/blob/66ed06937c3c6235c3b978a2abdfe6607543a798/handoff/issue28-hk-trio-mac-20261008/README.zh-CN.md)。

本轮无部署、真实API/UI、自然时段、producer或历史数据改写。所有安全 flags 和 Vibe8910 边界保持。
