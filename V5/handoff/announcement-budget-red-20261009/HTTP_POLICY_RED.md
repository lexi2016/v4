# 阶段一：完整目录/正文共享 HTTP 门禁 RED 候选

状态：TEST_CANDIDATE_NOT_RUN。父任务报告79fcdf81的31项Mac通过，独立复审确认字节与CLI两缺陷关闭。本轮先交新失败回归，candidate三个文件和既有31项保持不变；云端不运行、不采集、不部署。

## 可直接验收的代码

`tests/test_http_policy_red.py` 新增9项，复用真实HkexOfficialProvider和默认transport，只有opener/response受控。覆盖：HTTPError 429秒数Retry-After、503 HTTP-date、403硬停止、200 HTML captcha、返回型429计字节但不缓存、非法Retry-After不虚构时间、正常JSON仅提及captcha的反例、无显式budget的目录调用绑定策略、目录调用成功后释放许可。

历史31项不由这个文件执行。预计 **1 PASS / 8 FAIL / 0 ERROR**，只是假设，须现有Mac观察实际RED。日期解析的当前时间通过原provider `_now` 固定为2026-10-09T12:00:00Z，不依赖Mac真实时钟。HTTP状态/冷却字段预期放入receipt `byte_accounting.http_policy`，只保留status_code、reason、action、合法Retry-After信息和automatic_retry=false；断言禁止Cookie/Authorization/HTTP错误描述中的测试秘密出现在回执。

已有未知消耗门禁可能阻止HTTPError后的下一调用，但没有保留HTTP状态/Retry-After，不能据此把新测试当已覆盖。

## Mac单次RED命令

按README从本轮固定commit提取目录后，仅运行新文件一次（不要重跑31项或discover）：

```bash
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_http_policy_red.py > http-policy-red.log 2>&1
HTTP_POLICY_RC=$?
cat http-policy-red.log
printf 'http_policy_exit=%s\n' "$HTTP_POLICY_RC"
```

预计exit1。返回固定commit、完整日志、环境与退出码；ERROR或意外网络禁止异常不算合格RED。源码仍是已验79fcdf81，所有字节可由SHA256SUMS核对。

## RED之后的最小实现范围

- 默认transport显式处理HTTPError，保留code以及唯一白名单Retry-After，不存headers全集、Cookie、token或错误body。read字节与unknown消耗语义继续有效，HTTP策略停止原因不能被通用unknown标记覆盖。
- 429/503有合法Retry-After（整数秒或HTTP-date）时记录STOP_AND_COOLDOWN与最早允许后续操作的UTC时间；当前批次保持one-attempt且不自动重试、不睡眠后偷偷继续。403和明确captcha为STOP，Retry-After不构成解除403许可。缺失/非法Retry-After停止并标记待协调，不猜等待时间。
- 200挑战页在入MaterialStore前拒绝并计已读字节；仅明确HTML挑战结构命中，正常JSON正文提及captcha不能误判。普通HTML异常可另外拒绝解析，但不假称所有HTML都是验证码。不得尝试解码/绕过验证码。
- 目录函数原样调用 `capture_eastmoney(provider,url,force=True)`，没有budget参数。因此预设provider `_capture_policy` 绑定同一个gate，source在未显式传budget时采用该绑定并自行finally释放本次请求。显式body budget仍由body `_capture_url` 释放，禁止跨层重复归属。
- 门禁先在同gate关闭，随后阶段二私有owner把策略状态写入独立于run_id的owner policy ledger，至少403/验证码/unknown和冷却截止不得靠换run清除。该持久层未完成前不得真实采集。body需接收owner提供的同一个gate，不另开预算。

## 真实成功链与固定来源已核实

`OWNER_SOURCE_MANIFEST.json` 记录12项固定依赖定位，来自 `0382f753929365048d231a7252d9c328d40f8522` 的daily-chain bundle/API manifest，并验证manifest SHA和原文件SHA；没有取main。

- daily CLI SHA `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee`
- body原源 SHA `7e37ed7e904d80c135a51bdff1aaa95aec02012eecfcfdc8a1770fa31297cbdb`
- analysis SHA `b60b8c0c663b203d2ece5a5b451eb41ca296396b2db3630dff4a92a8566f373f`

父任务提供成功T20261008/P20261007依据：目录run6730f3cf34c8480d86fa229df5aa4019，613条/31页+空终页COMPLETE；bodyrun3f9d37a643060b57992167f3df05d987，608成功5失败/1435请求/3workers；4reader及独立reviewer613决定，owner导入和回读已验证；529股票中33selected/54watch/367notselected/75unassessed；NATURAL=false。这是历史来源依据，不是今天结果或本轮吞吐测试。

## 阶段二：最小V5私有owner接线（不另造采集器）

复用原daily CLI的capture/prepare/register-handoff/build-reviewed/import/readback函数。为它提供封闭的**进程内owner调用适配**，不创建HTTP服务、不向8873 POST，也不接受任意api-base；使用固定本地占位base仅满足原本地URL校验，所有允许路径由私有适配直接分派，其他路径fail closed。真实网络只发生在已获许可且门禁通过的原provider抓取边界，当前阶段不启用。

分派目标固定为原模块函数：

| 旧入口用途 | 私有V5内的复用函数 |
|---|---|
| 全日期目录刷新/回读 | workspace_announcements.refresh_eastmoney_date_catalog / read_date_catalog |
| 全rows正文 | 已验body_batch.run_capture，补接owner同gate |
| 正文/reader/reviewer手递产物 | 原daily CLI prepare/register-handoff/build-reviewed与原校验器 |
| 审查导入 | 原router的validate_registered_handoff、validate_agent_judgment_receipt → announcement_analysis.import_product |
| owner导入收据和最终回读 | 原router的冲突/事务/receipt校验 → announcement_analysis.read |

不能只调用analysis.import_product而跳过router的handoff、reviewer、owner receipt和最终SHA回读。service固定旧快照不含新增date-catalog/import方法，不能冒称其就是现役R3；薄V5owner仅暴露这些原函数所需的store/material/provider及只读回调，不启用旧service其他后台任务或manager/UI模块。

状态存储使用原ManagerResearchStore/MaterialStore，绑定**新的V5私有根**；写入前验证显式V5 owner identity与允许根、拒绝V4根/其子目录/符号链接。精确私有根和V4禁止根由现有Mac验收从既有V5工作区/运行身份解析，不向用户重新索取已授权权限。owner锁/policy ledger位于私有根，跨run生效，阶段检查沿用原日期、SHA和NO_RETRY；不复制旧V4结果冒充今日、不读写8873状态。

阶段二离线验收将覆盖：根隔离/拒绝8873、T09/P08日期绑定、超过3发行人的全目录+空终页、全rows正文、失败正文必须NOT_ASSESSED、4reader/独立reviewer完整决定、注册SHA冲突和导入回读、跨run停止/冷却持久性。随后才由父任务安排同Mac单次T20261009/P20261008真实采集；今天目前没有采集结果，不能输出虚构选股。

本交付不是今日采集许可：HTTP门禁实际RED→实现复验→V5私有owner隔离/持久门禁复验是有限阶段；不等待未来scheduler、不另起本机任务、不触碰V4。
