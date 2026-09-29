# V4 经理工作台三项修复 R3：代码候选

固定输入：`043e248f82360256de30b55fa45cb77c5be8b90f`。

状态：**OFFLINE_CODE_CANDIDATE / NOT_MAC_EXECUTED / NOT_DEPLOYED**。

## 本目录确实包含什么

`runtime.part1` 至 `runtime.part4` 是完整 `runtime.patch` 的 zlib + base64 分片，不是占位符。连接器不支持本地文件直接上传，故以可校验文本运输完整补丁。解码后的 patch 为 **98,286 bytes**，SHA256 `cfcb560e72f6c86c9947878fe12ace01971c5dcf922b0eca2b1bcc89c33de1e6`。补丁覆盖全部 **14 个 API 文件、1 个调度器文件、3 个配置/验收候选文件**。

`unpack_runtime.py` 校验四片 Git blob、patch SHA、固定提交前像以及每个后像 Git blob，在新隔离目录输出可读 `runtime.patch` 和完整 `after/api`、`after/scheduler`、`after/config`。它不访问网络，不覆盖活动源码，不启用任何配置。

在此仓库根目录执行，输出路径必须不存在：

```bash
python3 repairs/manager_remaining_r3/unpack_runtime.py \
  --repo "$PWD" --output /tmp/v4-manager-r3-isolated
```

本次工具传输路径已用固定提交对应前像在 Linux 逐字节验证；容器没有完整 Git clone，因此默认 `git show` 取前像路径仍需本机验证。替代路径 `--preimages <完整交付包/before>` 同样强制核对所有 Git 前像。

## 三项修复

公告沿原 provider/owner/store/consumer，接入已审阅官方目录协议，保留旧响应读回和正文独立取得时间。原 owner 增加冻结 singleton 验收参数，不另造 producer。

US-to-HK 保留发布时间/取得时间的原字段与无效值，补明确生物医药/石油词表；两源 PIT、发行人明确关系和独立引用不放宽。零接受映射及原始 movers 保留。

清晨候选窗口为 07:00–09:25，五分钟检查通过已有 API 注入的完整 owner，原事务锁内对输入身份去重，保留正式 pre-open freeze。修复 plan-only 回执重复关键字 TypeError，并贯通调度器/worker/API 的组合配置校验。

## 完整交付与验证边界

本聊天的可下载完整包另含未压缩 runtime.patch、tests.patch、完整 after/tests、after/fixtures、所有121后像文件、13精确前像、SOURCE_PINS.json、参考测试依赖、REPAIR_PLAN.md、LOCAL_ACCEPTANCE.md、CANNOT_CONFIRM.md 及完整原始测试日志。**本 Git 目录没有冒称同时存放那些大型 fixture 或全量测试包。**

封装后声明范围的离线测试一次运行 **405 passed / 0 skipped**，Linux / Python 3.13.5；两份 patch 正反重放121个后像逐字节一致。不是全仓库测试、Mac/Python 3.14 验收或真实业务验收。扩展财报测试有1项因五份 Mac PDF 不在输入中失败，未报为通过。参考 supervisor 夹具仅增加复制新增路由的4行，断言未改。

根原始证据 ZIP 二进制及完整约21.8MB API响应未取得，不宣称已重验全部原始证据。生产前像按固定提交 Git blob 接受；参考历史依赖不是另一套活动基线。

## 激活与回退

先按完整包 LOCAL_ACCEPTANCE.md 在 Mac 隔离副本核对依赖与测试，再冻结新的、确有非空官方公告证据的 singleton 与窗口。由原 owner 一次有界查询，保留请求、目录、正文、原 store、现有 API/consumer 的同一身份与真实时间，再独立 reviewer 核对。无新信息不重复历史空查询。

enabled recipe 不是可直接应用 binding。必须由原 canary、独立证据和本机新源码清单渲染、通过原 validator 后，才可按原发布流程切换；随后另验自然调度。失败恢复备份的 plan-only binding，关闭公告调度，保留全部失败收据。

本轮没有 Mac 连接、HKEX/Futu 请求、launchd 修改、服务重启、生产存储写入、订单、Stage/BUY 放宽或 pytdx 尾盘补采。
