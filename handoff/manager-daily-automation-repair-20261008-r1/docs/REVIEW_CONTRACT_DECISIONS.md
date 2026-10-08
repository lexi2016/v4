# 独立复验中的合同裁定

独立测试既检查代码，也核对其断言是否符合原合同。第1、2项保留原时点/历史语义，不作为已修复代码缺陷计数；第3、4项界定本轮进一步发现的真实读回缺陷及其验收要求。修复是否通过，以对应的最终独立 review 和源码 SHA 为准。

## 1. 事后计划与 target-bound US daily 的 cutoff 不相同

目标10/8、实际10/9执行的显式 manual plan 是 `RETROSPECTIVE`，其 `research_cutoff_policy=ACTUAL_OWNER_EXECUTION_CUTOFF_RETROSPECTIVE`，保存真实10/9研究 as-of 和 started/generated 时间。这表示现在对该目标日作事后研究，不表示10/8盘前或当天已知。

同一次恢复中的 US daily 则通过原 US owner 使用 `TARGET_DATE_END_OF_DAY_RETROSPECTIVE`，将 US源选择约束到目标10/8对应的US10/7，并检查原capture/registry时点。原 raw US attention 可以显示以当前实际时点看到的另一个session，须与target-bound daily显式分开。较早cutoff的封存计划不消费晚到daily。

因此“manual plan 的所有 cutoff 必须统一变成目标日EOD”不是当前合同。该断言被改为验证真实 retrospective metadata、US daily精确session和盘前排除；没有把实际日期改成过去日期，也没有放开历史输入校验。

## 2. 幂等单位是同 target、binding、时段的原触发

问题包要求同一目标日/时段的重复触发幂等，且不覆盖历史run。已完成同slot调用和服务重建后的重放必须读同receipt/plan，原文件字节不变。

10:00与12:30是两个不同研究cutoff。原 `workspace_projection.py` 在基础input identity中保留整个market screen及其时点上下文；仅排除顶层context的 `research_cutoff` 不意味着所有嵌套时点都被视为无关。该生产文件本轮保持不变。US daily显示/attempt元数据在基础semantic projection完成后才附加，不能仅凭两个cutoff的hash变化断言是新US attempt污染原identity。

在每日最多5次catchup的限制内，允许不同cutoff各保存一个真实时点的同日版本，不对原screen/PIT字段作全局删除或hash改写来强制复用。独立测试应验证第二slot可运行、真实cutoff/trigger、源SHA未被伪称更新、旧run不可变、同slot重放及日预算；这也继续允许真正晚到产品进入新评估。

如果在**相同研究cutoff和相同权威输入**下，仅改变展示用attempt/执行时间元数据就改变权威输入身份，仍应作为缺陷处理；上述裁定不免除这种检查。不同cutoff之间的内容去重不作为本轮自然闭环通过条件。

## 3. 保存计划的普通页读回必须区分研究时点与读取时点

同一完整 plan/selection/announcement 日期绑定的普通页 GET，应能通过原 reader 重验刚保存的计划。仅因读回发生在几秒后、嵌套 screen 的 cutoff 改变，就将来源字节未变的计划判为过期，是读回上下文漂移，不能用第2项的“不同评估时段允许新版本”解释。

允许从经验证的同日期封存计划取原研究上下文，再运行原 reader 和原输入身份比较。所有实际来源校验继续执行；真实来源变化或不相同的日期绑定不能直接认作 CURRENT。默认公告读取的原多日范围须保留；普通页显式提交与封存绑定相同的 publication 日期，不应悄悄把已保存的默认多日研究解释成单日研究。用户真正选择不同日期并显式重算时，使用该请求的原日期语义。

例如09:27已有封存计划，09:45才导入的合法审核产品不应进入该旧计划。同绑定普通GET应继续读回09:27的成果；原owner的新评估入口则应在09:45时点看到新产品，并由随后10:00的原catch-up实际消费新SHA、保存新版本，页面再认回新计划。独立测试必须覆盖这整个接续，不能只删除“旧GET应立刻改变input”的断言，也不能把旧截止后的新数据倒入盘前历史。

`research_cutoff` 是封存研究时点，`run_readback.read_at` 是本次实际读回时点。后者不能照抄前者，尤其不能早于已保存产品的生成时间；页面的同 run/SHA/attempt/时间校验继续保留。接口 CURRENT 与页面“保存产物已读回核验”须用同一个实际路由 DTO 串联验证，分别用手工构造的 DTO 通过测试不能替代这项接续。

## 4. 合法推进 latest 不得破坏前一天的不可变链

原 master publisher 更新共享 latest 的日期 entry，原 panel publisher 写新不可变目录并推进共享 pointer。次日合法更新不应改变前一日原件，也不应让前一日原件失去可验证性。

将共享 latest 整文件字节作为昨日不可变 artifact，并要求当前 panel pointer 永远指向昨日，是新增 gate 的跨日耦合缺陷。修复必须保留原 immutable run/manifest/receipt 与精确日期身份，使用可追溯的发布时证据区分可变索引和不可变产物；不能通过跳过任意 SHA 校验或重新发布旧资格来通过。

验收需在同根顺序发布两个合法日期后，再读回第一日的 chain、原 master 日期 entry 和 panel/manifest/receipt，检查第一日原件未改、缓存重入不重采，并确认真实旧产物被篡改仍会拒绝。合成隔离日期可证明此代码合同；实际两个连续自然日期仍须另外观察。
