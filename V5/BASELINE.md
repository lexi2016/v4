# V5 来源与状态基线

日期：2026年10月8日。范围是独立分支上的V5文档与后续经审阅的首轮迁移，非活动V4完整克隆。

## GitHub 目标

- 仓库：lexi2016/v4；本轮只读API确认private=true，保持私有
- 已创建新分支：v5/module-isolation-20261008
- 选定父commit：c563adc067fcd6a6b95fe756c7618f46d2f4389e
- 父tree：6ff3093e9abae18c2a6637716d92fa3df2166b0b
- 选择理由：已审HK10月8日准备快照，固定且现有根目录没有V5；作为独立开发分支容器，不宣称它包含最新全套活动源码
- 本轮允许新增：V5/README.md、V5/BASELINE.md、V5/SPEC.md、V5/PLAN.md；V5之外无变更

首次创建分支调用返回取消，复查ref为空后停止。用户明确继续后，同参数重试一次成功；远端已读回该分支指向上述父commit。本次文档提交仅新增V5/README.md、BASELINE.md、SPEC.md、PLAN.md，不修改基线已有文件或其他分支。

## 固定来源索引

| 范围 | commit | 使用边界 |
| --- | --- | --- |
| Stage/收盘10月8日准备 | c563adc067fcd6a6b95fe756c7618f46d2f4389e | 候选与现役证据，不能视为已自然运行 |
| 超跌reader和经理快照 | 9dfa50346357b6dc4b2463a30dcbf3718fce2f03 | 首轮原reader候选来源，按api variant manifest闭包核字节 |
| US每日映射 | 840b9538c45c9ba8fd56f8e89048aff230df0f0f | 后续模块参考，仅该次release delta |
| 公告修复 | a7732310a5262b59c95a30fdf5d7bedc9910939f | 后续模块参考，手动exact-date不等于自动完成 |

超跌主入口：handoff/v4-running-source-20261005/api/v4/manager_research/workspace_plan.py @ 9dfa50346357b6dc4b2463a30dcbf3718fce2f03；Git blob=10abaf491648f20b3618fbf3404c440a7ca77dc7。该blob不是SHA256，也不是本机当前加载字节证明。

合同锚点：REBOUND_SCREEN_SCHEMA=v4.manager_research.rebound_v3_screen.v1，REBOUND_SCREEN_RULE=20260923_REBOUND_TWO_GATE_V1。真实read_rebound_screen使用价格超跌与5日量比两门；同文件四门helper不可替代它。

快照总manifest在同commit的handoff/v4-running-source-20261005/MANIFEST.json；必须按各variant manifest内snapshot_path逐文件选字节，不把canonical整树当api。

## 现役与数据缺项

此前只读审计确认API/scheduler为hk-research-calendar-all-r1-20261007，Stage注册为20261003-hk-binding-wrapper-r3；本文件不是10月8日晨最新现场核验。

此前所查活动shared producer尚无价格日/资格来源日分开传参，且正确10月7日HK02 panel在该根缺失。先前HK10月8日池合同是target10/8、price10/7、eligibility9/30；该合同不能推导超跌reader允许回退其exact-date master。具体输入按各模块原reader核验。

以上缺项执行时需只读复核；未证恢复前不得称真实研究层成功。原生可复现依赖闭包和活动源码等价性尚待补齐。按用户最新分工，dot在当前工作中开发，云端Codex只承担定向测试，本地Codex承担获批部署和原生验证反馈；之前云开发环境启动失败不再作为编写代码的先决条件。

Python3.14.6仅为此前观察到的Mac解释器，不是已证必须精确相同的开发版本。云测试可用经源码/依赖校验兼容的解释器，记录实际版本与依赖；与Mac原生差异另验，不将补丁号差异本身当作开发阻塞。

## 上传范围

只包含规格、计划、源码身份与脱敏状态。没有凭据、令牌、账户/持仓、原始行情、完整真实panel、私密助手笔记、实际机器绝对路径或部署配置。后续代码包仍遵守该排除范围。
