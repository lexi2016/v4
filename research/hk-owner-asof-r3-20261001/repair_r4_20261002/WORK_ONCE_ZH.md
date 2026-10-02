# Mac一次接续：PR20 R4

本条仅在非活动隔离副本应用代码并独立测试。A既有21/21 API及新增UI验收保持，不重跑，不因旧A回执重新打开A任务。不要启动服务/provider/真实selection。

## 1. 取固定commit，核两个前像

从PR20修复commit读取本目录，原R3快照和mac_delivery失败证据仍保留。先git fetch，再在新的非活动worktree或原隔离副本核SHA：

- infrastructure/preselection_pool_store.py：e5ead3a523c44f95f7730d1faf4b314c93954db26eab3ec34b777d956223184d。
- infrastructure/scheduling/executor_registry_preselection.py：cf5d2d1f2cb67fe4881ff615b89b61315c8226a319bc27927a95556a31ace3e5。

完全等于before才能应用runtime.patch；完全等于after直接复用；第三SHA逐hunk适配，不强行覆盖。该patch是在R3已应用的active R9组合上增量修改；不是PR19原活动源补丁。canonical没有运行代码新增，不装R9存储到canonical；shared/Stage继续保留原R3候选及真实依赖。

```sh
(cd "$ISOLATED_R9_APP" && git apply --check "$REPAIR/runtime.patch" && git apply "$REPAIR/runtime.patch")
```

## 2. 一次集中独立验收

确认实际R9 facade、isolated loader、publisher和其app/upstreams strict universe reader来自mac_delivery记录的真实依赖，不能替换成作者旧缓存。测试目录无需写入活动源码，脚本通过HK_R3_APP_ROOT/PYTHONPATH显式绑定隔离app。报告输出目录必须新建：

```sh
"$SERVICE_PYTHON" -B "$REPAIR/tools/run_mac_acceptance.py" \
 --app-root "$ISOLATED_R9_APP" --output-root "$NEW_REVIEW_OUTPUT" \
 --variant active --suite reported
```

默认只运行旧报告7个受影响用例和新增20项，分别记录；不宣称旧19或整个业务全绿。确需复核原完整19时用--suite full（active另加新20）；canonical可用--variant canonical --suite full验证原19干净exit，canonical产品代码未改。不要把两组数量相加作独立场景。

脚本对每次运行新建临时父目录及独立--basetemp；不碰旧pytest-of-*垃圾目录，不chmod旧readonly快照。若自身清理仍失败，保留实际异常/exit，不改成通过。使用现有service解释器与依赖，不重装；HK模型3.13.12解释器只用于既有模型入口，不能因此改service版本。

## 3. 同一轮只读定位9/29原始来源

已核配置入口在PR19 CURRENT_BINDINGS.json，以及本次mac_delivery/ACTUAL_DEPENDENCIES.json和historical_receipts/SOURCES.json。现配置shared根是V35 state/workspace/v3_shared_data/.runtime/data，V4映射根也在当前配置内。资产位于原shared assets/hk_0_2；VIPDOC根由实际V3_SHARED_HK_TDX_ROOT/原owner参数读取，不猜Mac路径。

仅将原配置/原回执已确认的根作为重复参数传入，不全盘扫盘、不递归按mtime找最新版。程序不会采集，不调用旧只能采当前日的publisher，不改now/captured_at，不使用50股auction或9/28 Top100冒充9/29数据。

```sh
"$SERVICE_PYTHON" -B "$REPAIR/tools/prepare_original_hk_history.py" \
 --app-root "$ISOLATED_R9_APP" --shared-package-root "$ISOLATED_SHARED_PACKAGE" \
 --shared-root "$ORIGINAL_SHARED_DATA_ROOT" \
 --universe-root "$ORIGINAL_UNIVERSE_ROOT" \
 --asset-root "$ORIGINAL_HK_ASSET_ROOT" --tdx-root "$ORIGINAL_HK_TDX_ROOT" \
 --hk-python "$ORIGINAL_HK_MODEL_PYTHON" \
 --signal-date 20260929 --target-date 20260930 \
 > "$HISTORY_READBACK_JSON" 2> "$HISTORY_READBACK_STDERR"
```

有多个确知原根时重复--shared-root/--universe-root/--asset-root/--tdx-root。输出实际读过的路径、原件/模块SHA、价格日行数、资格asof/capture、旧池验证结果和具体失败。原生行情条数与成员资格分别检验，不能要求集合数量天然相等或以数量放行。

当且仅当原资格reader通过且原校验资产确有9/29价格时，输出既有scripts/materialize_hk_0_2.py命令；命令仍未执行，仍由原模型/覆盖/不可变key检查决定是否生成。先由owner审核源身份，再另行批准本机原件恢复/物化；此脚本不写池、不改配置根、不跨根自动搬移、不执行真实selection。若只找到native9/29记录但没有合格资产/资格，保持CANNOT_CONFIRM，由原updater/来源owner处理，不补造主档。

本次只需回传这个脱敏JSON和必要原source日期/字段/哈希，不需全项目或行情。既有根找不到原资格并不证明所有上游都不存在；也不能因此使用今天名单回填。源确实缺失时如实交付剩余缺件，不能把R9代码通过标为9/30数据恢复。

## 4. 完成与回退

通过本批代码测试仅说明接口可执行。真实完成标准另行验：真实9/29价格与实际成员capture链→9/30 D-1原100池→原Stage严格读取→普通API/UI的同date/stage/market/run/hash/行序和限制；不能把读取100旧行或exit0当自然刷新。

代码回退只对本批after用rollback.patch恢复before；不删除历史数据/receipt/attempt，不清budget，不改已完成A结果，不重新安装旧R3整包。PR继续Draft，不合并部署。
