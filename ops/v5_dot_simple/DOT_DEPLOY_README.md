# V5 Dot 部署

Mac 负责制作和验收交付包。Dot 在一个独立会话中串行执行，使用同一持久工作区、状态目录与已认证的 Drive 连接器。需要 POSIX 环境、Python 3.11+ 和 `Asia/Shanghai` 时区数据。原版 PAR 的 GBBQ 解码依赖 `pandas`。连到 [V5 产物目录](https://drive.google.com/drive/folders/1MnbcnmryNtVie6vt_mjWJwWaBUs34qcH) 后，先核对当前身份确实可读取该目录和目标文件。

## 首次准备

1. 解压到 Dot 工作区。建立同级持久目录 `intake` 和 `state`，从 `dot_manifest.json` 指定的原 Drive 文件 ID 下载原始字节。原 [冻结运行包](https://drive.google.com/open?id=1W9nexHSwYpkRgiLwn8s77k0i7BJKtWQ8) 保存为 `intake/V5_FINAL.zip`，原 [系统资产图](https://drive.google.com/open?id=1iSW2qwN0y4fUSddIw5jev86Ep3hoXYkI) 保存为 `intake/V5_SYSTEM_MAP.json`，原 [11 月 26 日看板](https://drive.google.com/open?id=1LsWT2s0j0sg8Jc_-graK9-WIQSbKrFgs) 保存为 `intake/V5_ORIGINAL_BOARD.html`。包内含三件原件的 ID、字节数和 SHA-256。
2. 运行 `python3 -B dot_run.py --intake intake --state preflight-state preflight --date 20261130`。应返回 `PREFLIGHT_PASS`、前一交易日 `20261127`、原包 113 件和 vendor 32 件。该回执的 D30 数据、PAR 与 Dot 连接器字段为 `NOT_RUN`。
3. 新部署的首次安装执行 `python3 -B dot_run.py --intake intake --state state init --first-install`。保留并备份整套 `state`，尤其是 `DOT_OWNER.json`、`CURRENT.json`、`boards/`、`plans/`、`attempts/`、`backfill/` 和 `drive/JOURNAL.json`。一个未确认的上传请求可能仍在途，恢复时须保留相应的日志历史和对应的看板指针。单独回退日志或看板指针会触发状态校验。同一会话恢复也使用原目录。状态丢失或损坏返回 `DURABLE_STATE_RESTORE_REQUIRED`，数据日留空，先恢复经验证的持久状态。首次安装命令只用于真正的新部署。

## 一条 Dot 自动化

在同一个持久 Dot 会话中配置一条工作日自动化，只设表中的三个北京时间触发。按触发时点路由到对应命令，复用同一 `intake` 与 `state`。每个命令保留五分钟启动窗口，并用交易日历判断休市。Dot 先完成当前批和连接器回执，再接受下一批。Mac 端无需配置 launchd。

| 北京时间 | 命令 |
| --- | --- |
| 16:20、16:50 | `python3 -B dot_run.py --intake intake --state state close` |
| 18:30 | `python3 -B dot_run.py --intake intake --state state evening` |

- 交易日取 [深交所 2026 全年休市公告](https://www.szse.cn/disclosure/notice/t20251222_618087.html)，原网页随包并带 SHA。新年度把官方全年公告原始字节和审核过的 pin 放在 `intake/calendars/SZSE_YYYY.html` 与 `SZSE_YYYY.json`。JSON 字段为 `schema=V5_DOT_SZSE_ANNUAL_V1`、整数 `year`、官方 `url`、文件名 `path`、`bytes` 和 `sha256`。跨年回查须提供所经过年度，遇到缺年、解析不全、周末或休市即停止当日计算。
- 收盘使用通达信当天 `https://www.tdx.com.cn/products/data/data/g4day/YYYYMMDD.zip`，一次 GET，核对官方 URL、200、大小、当日 ZIP 成员、CRC、股票记录结构和真实观察时间。16:50 也使用实际取数时间。当地已有已验的当日 Top200 时复用原始 G4 和计算。当天 G4 缺失时记录原因。
- PAR 继续使用 `dot_manifest.json` 固定的原版计算。它需要精确前一交易日的同代 `daily-update` 的完整原始回读及当日官方 GBBQ。前一交易日从日历计算，旧日期或缺证会阻断。合规比例由冻结代码决定，并校验 5,575 行、当日 109 字段样本、已计算行和原版分片。初始历史的 D27 分支沿用冻结代码的 D26 archive 和资产图别名约定。普通交易日通过前一日原版终态回执复用分片。当前没有 11 月 27 日真实完整 PAR 的已验证凭证。11 月 30 日可独立计算当日 Top200，PAR 须等 11 月 27 日真实完整原版回执与分片。此后的交易日同样要求精确前驱。缺件在授权恢复完成前持续阻断 PAR。
- 晚间读当日 Top200、当日已验 PAR 和 109 字段，并执行原版装配和 HTML 渲染。有上述输入才更新 `state/CURRENT.json` 中的看板指针。保留原 21 节点表与旧装配状态，低频约定外的节点仍显示真实缺失。缺当日必要输入时展示最后成功的看板数据日、尝试日与失败原因。包内首次安装看板数据日是 `20261126`。在 `CURRENT.json` 的 `view.path` 查看带状态的页面，`last_success.raw` 始终指向原始已验字节。

## 错过窗口后的指定日期补跑

`python3 -B dot_run.py --intake intake --state state backfill --date YYYYMMDD`

- 指定漏跑的北京时间交易日。补跑会查日历，依次执行原有收盘、晚间逻辑。收盘输入齐全时产出原版 Top200、完整 PAR 及八个分片，随后生成看板和待发布计划。成功回执为 `BACKFILL_READY`，重复运行复用同日已验结果和计划。补跑回执记录真实时间、`backfill=true`、`natural_verified=false` 和 `publication=NOT_RUN`。
- 同日错过窗口后，在冻结源规则允许的北京时间 15:00 至午夜内，Dot 可从通达信实际请求目标日 G4 和滚动 GBBQ。原 URL、HTTP、ZIP、观测时间、SHA 和下游检查照常执行。实际观测跨到下一日时拒绝写成前日观测。同日捕获并通过源校验的原始文件及回执保存在 `state/backfill/YYYYMMDD/`，供重跑复用。
- 已过午夜时，仍填写原交易日。若已有同日已验计划或同日终态回读，会优先复用。需要重新计算的源应在 `intake/stage/YYYYMMDD/SAME_DAY_SOURCE_RECEIPT.json` 里提供 `business_date` 及 `g4`、`gbbq` 原始观测凭据。每份凭据含同目录文件名 `path`、字节数 `bytes`、`sha256`、原官方 `url`、整数 `http_status`、带偏移的实际 `observed_at` 和有记录时的 `last_modified`。GBBQ 额外标记 `rights_snapshot_finality=OBSERVED_NOT_FINAL`。通达信仍能按日期提供 G4 文件时，也需保留目标日的原观测凭据。跨午夜后无法取得前日已归档的 GBBQ 时，回执为 `WAITING_INPUT`。滚动地址的新响应属于当前观测。
- 缺任一必要输入时，看板保留最后成功数据。已验的当日 Top200 可以单独形成待发布计划。确认整批完成以回执的 `BACKFILL_READY` 为准。仅看到进程退出码 0 或 Top200 待发布时，仍须查看回执中的 PAR 与晚间状态。补跑日期早于看板最后成功数据日时拒绝执行。补跑日期与较新的失败尝试并存时，看板保留较新尝试日及失败原因。

## Dot 连接器输入

每次开批前，根据当前交易日和上次发布回执，将已有真实对象暂存为 `intake/stage/YYYYMMDD/REMOTE_READBACKS.json` 和 `remote_<id>.raw`。当天主要读取 `a-top200`、`daily-update`、`evening-prepare` 的原版终态回执。前驱日前缀读取 `daily-update` 回执以及它引用的全部对象，包括八个 `PAR_STATE_nn.zip`。回执名为 `V5_W11C_<交易日>_<节点>_RECEIPT.json`。按目录和完整文件名查询，每个引用通过实际 ID 取元数据和原始字节。暂存 JSON 为 `{"date":"YYYYMMDD","entries":[...]}`。每条记录含 `id`、`name`、`parent_ids`、`trashed`、整数 `file_size_bytes`、本地原始字节计算的 `bytes` 和 `sha256`。拿不到源文件或完整回读时保留缺项。

新计算 PAR 时，Dot 在同一收盘窗口向官方 `https://www.tdx.com.cn/products/data/data/dbf/gbbq.zip` 请求一次，记录真实观察时间和原始 SHA，并通过原版 URL、HTTP、当日观察、ZIP 和记录结构检查。看板更新前还须通过冻结解码器的沪深北覆盖检查，并与原计算回执的市场计数一致。GBBQ 是 `OBSERVED_NOT_FINAL` 的当日观测快照。前一交易日保存在 `intake/stage/<前一交易日>/`，与本日暂存目录并列，两批可复用同一套前驱回读。

## Dot 连接器发布

运行回执有 `pending_connector_nodes` 时串行处理。按回执先后顺序选择节点，使用回执业务日。跨午夜发布补跑对象时，每次调用 guard 都添加 `--allow-backfill`。历史日期须经当日日历校验，且 `state/backfill/YYYYMMDD/RESULT.json` 内的节点与本地计划 SHA 必须匹配。保留以下精确查询、许可时效、回读和日志步骤。

1. 执行 `python3 -B dot_run.py --intake intake --state state guard --date YYYYMMDD --node NODE`。返回 `LIST_EXACT` 时，使用连接器按 `query` 在固定父目录执行精确查询，读取所有分页。按 `node_receipt_query` 同样查询该节点终态（当前文件即终态时只需一次查询）。使用 Drive v3 时投影 `nextPageToken,incompleteSearch,files(id,name,parents,trashed,size)`，在共享目录按实际身份使用对应的 Drive 查询参数。连接器须提供等价的完整性信息。仅有搜索近似命中、权限不清、分页未读完或 API 错误时停止。 [Google Drive files.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list)
2. 在本次独立的证据目录写 `LIST.json` 和需要时的 `NODE_LIST.json`。分别记录 `schema=V5_DOT_CONNECTOR_LIST_V1`、实际 `parent`、`name`、`query`、`authenticated=true`、带偏移的 `requested_at`、`completed_at` 和 `pages`。每页字段为 `request_page_token`、`next_page_token`（第一页请求与最后一页结束写 `null`）、原工具成功时 `status=OK`、`incomplete_search=false`、`files`（上节元数据格式，尚不需要 SHA 与 `bytes`）。这些字段须来自实际成功响应。查询发现一件对象时，以实际 ID 另取元数据和原始字节，写 `metadata_<id>.json` 与 `remote_<id>.raw`。同名多件、名称或目录不符、内容不同均停止并保留证据。 [Google Drive files.get](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get)
3. 紧接执行同一 guard 命令并追加 `--evidence 本次证据目录`。只有返回 `CREATE_ONCE` 时，在 `expires_at` 之前执行一次无自动重试的文件创建，按回执的固定父目录、精确文件名和 `state/<payload.path>` 原始字节。不要做格式转换。许可在返回前已作为 `ACK_UNKNOWN` 落盘。超时、连接器错误、进程重启或回执不明时，重新查同名并读回真实 ID 和原始字节。当前 guard 状态下找不到既有精确对象则等待人工核实，不再次创建。返回 `READ_EXACT` 时补实际 ID 的原始回读，再用最新清单执行 guard。返回 `READBACK_VERIFIED` 时推进到下一个对象。
4. 最后一件为同一节点的 `RECEIPT.json`，它只引用逐件已核对的 ID、父目录、名字、字节数和 SHA。终态也走相同的查询、创建和原始读回。只有 guard 返回 `REMOTE_VERIFIED` 才记已验证发布。将实际回执与对象引用保存到下次可用的暂存目录。坚持单 Dot 会话所有权。这个机制使用本地持久状态和真实回读。

运行回执中的 `publication=NOT_RUN` 表示计算尚未执行连接器操作。结果均为研究用途，`production_allowed=false`、`orders_sent=false`。离线历史回放保留 `natural_verified=false`，未执行的未来数据和真实连接器状态保留 `NOT_RUN`。
