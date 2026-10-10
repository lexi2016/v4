# M06编码任务 · 复用原HK02生成Top100并独立读回

只做原M06。已验证既有池reader，不再为已有guard错误重写一版。基于f7cb静态目标交最小候选，嘻嘻负责Mac真实输入与独立验收。

## 最小工作内容
1. 固定target_date、HK证券前一signal_date、eligibility_source_date、带时区cutoff与真实取得时间。M02价格panel、主表和Connect资格分别绑定，资格不明保持原限制。
2. 读取原materialize_hk_0_2.py和shared_data.hk_0_2完整调用闭包；复用materialize_frozen_hk_0_2、原模型bundle/manifest校验、原预测/排序/Top100、publish/read_exact。不得重训、换权重、改阈值、用100条JSON假装新生成。
3. 先复用合格精确现有池；新日确需计算时输入当前合格panel及真实weights，在V5私有asset/store运行原producer。原generator对输入不成立应拒绝，不能偷偷fallback旧日/source-root。
4. 新hk_preselection_daily区分producer receipt和已有reader投影回执；reader的model_weights_reverified=false不应随手改true。真实加载并校验权重的生产证据独立记录；未验证则明确NOT_RUN。
5. 完整100行、排名1—100、代码集合/次序、score_prob_active及pool_score、理由与source provenance保持原值，独立readback同run/manifest/receipt；少于100按原拒绝，不能填充/截断/复制补数。
6. 输入和输出路径分离，同输入幂等，错误新池不得覆盖旧成功。M08读取同三日期/同源identity；旧成功可追溯但不冒新日。
7. 当前reader不支持独立eligibility_universe_root/research_name_supplement，保持明确拒绝，不偷偷忽略kwargs。若新增业务确需合同扩展，给M02/统一集成者精确接口请求，不自行放宽。

## 测试与共享边界
新增新生产adapter定向测试覆盖错三日期、证券/Connect日历分离、after-cutoff、master clock顺序、weights真实SHA不符、panel错日/缺行、Top100重复/顺序/概率非有限、无静默fallback、失败旧成功保留、独立读回identity与回滚。现有15项仅历史引用，新变动必要回归单独报。
仅SOURCE_MAP白名单。a_preselection共享guard、M02来源、M08阶段、所有UI/gateway/API/调度/contract注册/pin不直接改；共享接线交INTEGRATION_REQUEST。原vendor算法只读，闭包依赖按manifest逐文件固定。

## 必须交付
1. 唯一固定candidate commit或完整候选包、base ref、donor→现有V5目标映射；已等价实现不改。
2. before/after完整修改文件、runtime.patch、reverse.patch；每文件Git blob SHA、before SHA256、after SHA256，新增文件before=ABSENT，删除说明用途；不编造未来after值。
3. 依赖/私有输出/输入manifest清单，原算法等价用例与失败用例源码，原始测试命令/环境/退出码/日志；没有真实数据时标NOT_RUN。
4. 共享变更单INTEGRATION_REQUEST：共享目标路径、before SHA、调用方、接口与日期/cutoff/失败语义、向后兼容、验收方法；统一集成者实施，Chat不附共享文件覆盖补丁。
5. MAC_APPLY_AND_ACCEPTANCE：前像检查、隔离应用、必要回归、真实输入/独立读回、API/页面、唯一发布窗口及单模块回滚。部署路径/端口未知时列现场核实项，不猜命令。
6. 五层分别报告代码候选、Mac工程测试、真实业务生产/保存/独立读回、API/原页面、自然接续与回滚。历史测试不相加，不冒称本轮运行。
缺当前Mac active前像不阻挡固定f7cb静态候选；嘻嘻安装前核active SHA。不要要求Chat连Mac，也不要向用户索取已有GitHub材料/整库/凭据。保留V4、8910与BUY门，不交易，不扩大安全权限或凭据。

