# US → HK mapping research — 2026-09-30

Research date: 2026-09-30. US session: 2026-09-29. Review performed: 2026-10-05.
Baseline commit: 7dd1f638bea9e3a499de74fe73b315331d5ebb3f.
Canonical source: /Users/lexi/Desktop/学习/v4_app.
Observed runtime: manager-announcement-r15-20261005-stock-selection-r1 on port 8873.
This delivery changes no application source, configuration, runtime, or business data.

## Research result

The strongest observed group in the existing configured snapshot is optical interconnect: LITE +5.662528%, COHR +3.459019%, CIEN +3.102937%. AVGO is +1.581944%. The snapshot is a fixed 33-symbol universe, not a full US-market screen. Its 19 positive symbols are 8 stocks and 11 ETFs; the 14 positive industry rows are proxies. Gains are existing snapshot observations, not independently recollected prices or proof of catalysts.

1. HK06166 CIG Shanghai / 剑桥科技: priority peer comparison for LITE/COHR high-speed optical transceivers. The 2026 interim report describes mass-produced/shipped 800G modules. Some 1.6T models completed certification with shipment expected in 2H26, while other projects remained in development. CPO was not established as mass production. No named LITE/COHR customer relationship is established.
   Official report: https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0903/2026090300698.pdf
2. HK06088 FIT Hon Teng / 鸿腾精密: priority mapping to AVGO's Bailly CPO platform. FIT's May 13, 2025 announcement identifies deliveries of LGA sockets, remote pluggable laser-source interface cages and connector assemblies for Broadcom Tomahawk 5 Bailly. This establishes platform component supply; it does not establish FIT as a laser or transceiver supplier.
   Official disclosure: https://www.fit-foxconn.com/mainssl/modules/MySpace/BlogInfo.php?xmlid=27625
3. HK00763 ZTE / 中兴通讯: priority peer/competitive comparison for CIENA optical transport and OTN equipment. This is not a CIENA supplier claim.
   Official 2025 annual report, March 26, 2026: https://www.hkexnews.hk/listedco/listconews/sehk/2026/0326/2026032600626.pdf
4. HK06869 YOFC / 长飞光纤光缆: conditional observation for broader fiber and optical-interconnect demand. This includes optical-transmission components and modules, not only cabling: 50G PON modules reached mass delivery, 400G/800G AEC passed phased customer acceptance, and 1.6T optical modules remained at solution selection/design. These support a broader mapping, not a named US customer relationship.
   Official interim report, August 21, 2026: https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0821/2026082101705.pdf
5. HK01729 TIME Interconnect / 汇聚科技: conditional observation for data-center fiber and high-speed cable assemblies. Cable assemblies are not interchangeable with lasers, transceivers, or CPO.
   Official interim results, August 28, 2026: https://www.time-interconnect.com/en/aboutus_news_detail.asp?ID=416BACFF-1A97-4528-A4DF-122C589D26E2

HK00992 Lenovo is excluded from this optical-device shortlist. Its AI-server/liquid-cooling activities may support a separate infrastructure study, not a verified VRT supply relationship.
Official results: https://news.lenovo.com/pressroom/press-releases/fy-2024-25/

These rankings are research judgments about business correspondence, not expected-return rankings or causal explanations of September 29 share-price moves. The named official disclosures predate the target cutoff; their present-day verification does not recreate historical captured_at or PIT evidence.

## Existing V4 lineage and limitations

Read-only owner inspection found:
- Existing state/data/research/peripherals/20260929/external_finance.json: payload SHA prefix 7eb0094a; source-response SHA prefix a6451a3b; capture 2026-09-29T20:15:06Z; run us-rss:20260929:POST_CLOSE:09ae1f626e370a9e43d73fc2.
- The current receipt matches the payload identity but omits market_snapshot_captured_at and market_snapshot_source_response_sha256 required by the active reader. Current admission fails with US_MARKET_LINEAGE_BYTES_INVALID.
- The original cutoff is 2026-09-30T09:27:08.283634+08:00. Saved plan ba13fba330464300b760fe940ba579a1 had US INPUT_MISSING and zero movers. Current historical readback is SOURCE_FAILED / HISTORY_READER_VERSION_CHANGED.
- Later plan f0db65a25bb340b584682542b8d597b8 at 09:53 has the 14 positive proxies / 19 positive symbols, but no accepted HK mappings. Missing verified materials and structured issuer relations mean this zero is incomplete evaluation, not proof that no mapping exists.
- The currently available date-indexed 9/29 HK identity artifact was captured October 2. It cannot substitute for cutoff-bound identity or Connect eligibility.
- New official evidence above has not been integrated into V4 date-scoped mapping artifacts.

Scope status: RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
Source/runtime modifications, deployment, tests, natural-slot validation: NOT_RUN / not applicable to this read-only research.
Target-date formal eligibility, historical PIT, formal selection: CANNOT_CONFIRM.

## Independent review

REVIEWED: PASS by separate Luna Max identity announcement_finish_review. Official disclosures were independently checked for the five primary/secondary mappings. Product-stage boundaries above incorporate the review. US return inputs were not recalculated. Business correspondence was verified; historical eligibility, PIT and return causality remain CANNOT_CONFIRM. No formal selection or software behavior acceptance is claimed.
