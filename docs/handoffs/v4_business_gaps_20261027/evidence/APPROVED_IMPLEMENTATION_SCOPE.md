# 用户已批准实施的 V4 业务缺口最小修复

唯一Writer /root/six_fixes_writer（Sol High）；主控不代写业务代码；一次独立Luna Max冻结范围审，按批准规则升级独立Sol High。新worktree /Users/lexi/.codex/worktrees/v4-business-gaps-20261027/v4_app，branch codex/v4-business-gaps-20261027，Git base55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054。实际源码owner见SCOPE.json，必须按Stage/API/collector各自现役基线导入、留before SHA及依赖闭包，禁止canonical脏树或API同名文件覆盖Stage。

批准的十项：
1. A09:25先验证主源行，再按无效/缺失行调用原TDX备用报价；保持真实09:25:00至09:25:05截点，不修写原时间、不手写manifest。今日482原行477未来09:30/5空时间全部拒绝的原据保留，今日自然失败不重写。
2. 原权威证券身份与报价市场核验；BJ920575不许映为SH/SZ。能力未证明逐码隔离，不混市场，不造另一个producer。
3. 状态UI统一formatter：采集失败、未到期/等待执行、不适用、成功零结果、部分完成分别显示；时间线/详情同语义；stage8补采提示只出现在stage8。复用既有每市场证据，保留旧接口，必要planned_at/due_status为可选增量。
4. 美股日期消费：当前原件/receipt已含研究日20261027、原采集美股场次20261026和24/24nativeboards；原消费函数跨日误拒。核上海日/纽约场次/真实采集/原交易日历与SHA唯一匹配，修读链，不重采、不强贴LATE身份。
5. A来源未认证/HK缺09903及盘口不足按来源/市场列出，不降资格、不删成员；16:05新实测stage8本次90/100、batch4订阅失败纳入同一原owner最小修复，成功90及PARTIAL保留，缺少错误消息不可猜quota。
6. 原reader绑定、deadline实际产物合同、终态/当前PID分开。Lifecycle R8尚未部署；先复用其源成果和匹配的已审合同，不重做另一生命周期系统，不覆盖原owner成果。原owner交接未齐时可做不冲突源修，禁止自行执行R8。
7. 原研究输入缺口：显示公众号精确日期缺失文件/owner；研报沿成功页、原cursor/checkpoint接续，未到since边界保留PARTIAL。业务补采/重跑由主控根据原owner与进度材料执行；Writer不擅动原数据或运行采集。
8. 汇总翻页只更新汇总行和其分页，独立短池按同date/输入fingerprint保留；日期或来源变更整体失效并重读第一页。不改真实池成员/评分。
9. authority既有API可选compact投影，原默认响应兼容；保留状态/首失败/计数/原件引用，collector使用compact；4MiB上限保持。实际full约8.24MB，不能临时继续放大。
10. 前端构建身份与API身份分别核验，不一致提示刷新；不只凭服务器banner判实际bundle。

必须完成：针对性原失败回归、来源/SHA manifest、最小diff和测试摘要、候选构建材料；无新证据不重复名称90或过去32/13/19整套验证。首审只做一次完整冻结差异，相关新增真实失败才增量。

禁止：现役源码/数据/ledger/plist直接修改、未经主控的服务/锁/信号/发布、选股算法/排名/资格/PIT/BUY改变、PDF夜门控改变、Vibe8910、秘密/大数据/dist上传。保持RESEARCH_ONLY=true与其他三旗false。

自然验收：A新版本须下一交易日原09:25自然窗；明日PDF02:05/08:35原闹钟保持。软件/测试/独审/部署/API/UI/业务/自然分别记，不以部分PASS报总完成。
