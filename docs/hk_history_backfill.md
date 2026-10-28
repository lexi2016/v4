# HK 历史分钟数据补采 Runbook

本说明记录已验证的研究数据获取路径，便于后续复用。它不授权自动请求；每次补采仍须有任务范围、目标日期和输出目录。所有结果保持 `RESEARCH_ONLY`，不含交易或下单操作。

## 固定顺序

1. **先查已存证据。** 按市场、代码、目标日检查现有 raw response/cache、captured-at、来源、时区及 SHA。只复用可核对身份和目标日期的数据；已有完整 raw 时不再请求同源。缺缓存才进入下一个来源。
2. **TDX ExHQ 是既有 HK 行情入口。** 使用项目已配置的 Python、`pytdx.exhq.TdxExHq_API` 和既有连接主机 `119.97.142.130:7721`。HK Connect 一分钟 bars 使用 `get_instrument_bars(category=7, market=71, code=<代码数字>, start=<偏移>, count=<页大小>)`；分页读取，保存原始各页及请求参数，再按 bar 自身日期严格筛选目标日。不要用“最近 N 个交易日”的固定偏移猜日期。主板 `market=31` 与 Connect `market=71` 是不同市场输入，不能互换。

   `get_history_minute_time_data(market, code, date)` 和 `get_history_transaction_data(market, code, date, start=0)` 可用于诊断指定日期的分钟时槽或逐笔覆盖；它们必须保留原始响应并逐码判读。本批对 2026-09-25 的七个剩余代码，TDX minute-time API 都返回 330 个价/均价/量全零时槽，HK.02715 的 market31 对照也相同；逐笔查询为空。这是占位/无可用行情证据，**不能**据此认定无交易，也不能作为补齐成功。
3. **Futu 只在用户选择或 TDX 不支持时使用。** 先只读调用 `get_history_kl_quota(get_detail=True)`，记录原始返回中的 `used`、`remain` 和 detail 列表。配额会变化；一次 `100/0` 不是永久状态。只有来源被明确标为 Futu、且额度/权限允许时，才用 `OpenQuoteContext.request_history_kline` 请求 `K_1M`、`AuType.NONE`，按页取数并保存每页 raw、查询时间、目标日期及时区；不把 Yahoo、AKShare 或 TDX 观察数据伪装成 Futu。Futu quota/history API 参考：[get_history_kl_quota](https://openapi.futunn.com/futu-api-doc/quote/get-history-kl-quota.html)、[request_history_kline](https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html)。
4. **AKShare EastMoney 路径仅作不稳定的补充来源。** 已验证函数为 `ak.stock_hk_hist_min_em(symbol=<代码>, period="1", adjust="")`，接口通常只返回最近 5 个交易日；在返回结果内按目标日期的本地时间严格过滤，目标日期不在响应窗口时记为不可用，不能从该响应推断无数据。本批 11 个代码经 AKShare 成功，HK.02402 另有一次 `curl -4` 同源查询成功；其余响应不稳定。相同输入失败不盲重试，不把 HTTP/连接失败写成零行行情。
5. **已有成功证据支持时才用 Yahoo Chart API。** 本批七码使用 `query2.finance.yahoo.com/v8/finance/chart/{ticker}`，按香港目标日生成 `period1`（当天 00:00）和 `period2`（次日 00:00）的 Unix 秒，`interval=1m`、`includePrePost=false`、`events=div,splits,capitalGains`。对本批 0 开头的五位 HK Connect 代码（如 `02715`），Yahoo ticker 为去掉前导 0 的四位 `.HK` 代码（`2715.HK`）。yfinance 官方测试记录了 1m 查询窗口限制（单次最多 7 天，位于最近 30 天内）：[test_price_repair.py](https://github.com/ranaroussi/yfinance/blob/main/tests/test_price_repair.py)。该限制说明单日请求可尝试，不保证某次请求成功或覆盖齐全。

   使用已安装的服务 Python 和 `curl_cffi` Chrome impersonation，会话开启 TLS 验证，单码 canary 先确认 HTTP 200、香港时区和目标日时间戳；成功后再逐码请求，间隔至少 2 秒。代理只通过参数传入本机**当前已有**配置，不写入代码或收据；`127.0.0.1:7897` 只是本批历史示例，不是默认值。不要改系统代理、节点、TUN，不安装依赖，不探测新端点。示例只保存响应和收据，不发送交易：

   ```python
   # 在已配置 curl_cffi 的项目 Python 中运行；不会下单。
   import argparse, collections, hashlib, json, math, time
   from datetime import date, datetime, time as day_time, timedelta, timezone
   from pathlib import Path
   from zoneinfo import ZoneInfo
   from curl_cffi import requests

   ap = argparse.ArgumentParser()
   ap.add_argument("--date", required=True, help="香港交易日，例如 2026-09-25")
   ap.add_argument("--codes", nargs="+", required=True, help="五位 Connect 代码，例如 02715 02922")
   ap.add_argument("--out", required=True, type=Path)
   ap.add_argument("--proxy", default=None, help="本机已配置的代理 URL；不传则使用当前客户端默认网络设置")
   args = ap.parse_args()
   target = date.fromisoformat(args.date)
   tz = ZoneInfo("Asia/Hong_Kong")
   start = datetime.combine(target, day_time.min, tzinfo=tz)
   end = datetime.combine(target + timedelta(days=1), day_time.min, tzinfo=tz)
   params = {"period1": int(start.timestamp()), "period2": int(end.timestamp()),
             "interval": "1m", "includePrePost": "false",
             "events": "div,splits,capitalGains"}
   # --out must be a fresh run directory. Refuse reuse before any request.
   args.out.mkdir(parents=True, exist_ok=False)
   codes = [str(code).zfill(5) for code in args.codes]
   if len(set(codes)) != len(codes):
       raise SystemExit("Duplicate codes are not allowed in one run.")
   session = requests.Session(impersonate="chrome", verify=True)
   if args.proxy:
       session.proxies = {"http": args.proxy, "https": args.proxy}

   def capture(code):
       code = str(code).zfill(5)
       if len(code) != 5 or not code.startswith("0") or not code.isdigit():
           raise ValueError("本批 Yahoo 映射仅覆盖 0 开头的五位 HK Connect 代码")
       ticker = code[1:] + ".HK"
       folder = args.out / f"HK_{code}"
       folder.mkdir(parents=True, exist_ok=False)
       raw_path = folder / "raw_response.body"
       receipt_path = folder / "receipt.json"
       captured_start = datetime.now(timezone.utc).isoformat()
       receipt = {"source_id": "YAHOO_FINANCE_CHART_1M", "code": "HK." + code,
                  "ticker": ticker, "target_date": target.isoformat(),
                  "query_timezone": "Asia/Hong_Kong", "request_params": params,
                  "tls_verify": True, "proxy_configured": bool(args.proxy),
                  "captured_at_start_utc": captured_start,
                  "adjustment_basis": "Yahoo chart quote fields; no client-side adjustment or repair",
                  "volume_semantics": "native Yahoo quote.volume; unit as returned; no turnover inference"}
       url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
       try:
           response = session.get(url, params=params, timeout=15, verify=True)
           body = response.content
           with raw_path.open("xb") as stream:
               stream.write(body)
           receipt.update({"http_status": response.status_code,
                           "raw_response_path": str(raw_path),
                           "raw_response_sha256": hashlib.sha256(body).hexdigest()})
           if response.status_code == 429:
               receipt["result"] = "HTTP_429_RATE_LIMIT"
           elif response.status_code == 403:
               receipt["result"] = "HTTP_403_FORBIDDEN"
           elif response.status_code != 200:
               receipt["result"] = "HTTP_ERROR"
           else:
               payload = response.json()
               chart = payload.get("chart") or {}
               receipt["chart_error"] = chart.get("error")
               result = (chart.get("result") or [None])[0]
               meta = (result or {}).get("meta") or {}
               tz_name = meta.get("exchangeTimezoneName")
               receipt["currency"] = meta.get("currency")
               receipt["meta_checks"] = {
                   "symbol_matches_request": meta.get("symbol") == ticker,
                   "exchange_is_hkg": meta.get("exchangeName") == "HKG" or
                                      meta.get("fullExchangeName") == "Hong Kong Stock Exchange",
                   "currency_is_hkd": meta.get("currency") == "HKD",
                   "granularity_is_1m": meta.get("dataGranularity") == "1m",
                   "timezone_is_hong_kong": tz_name == "Asia/Hong_Kong",
               }
               timestamps = (result or {}).get("timestamp") or []
               receipt["exchange_timezone"] = tz_name
               day_counts = collections.Counter(
                   datetime.fromtimestamp(ts, ZoneInfo(tz_name)).date().isoformat()
                   for ts in timestamps
               ) if tz_name else collections.Counter()
               receipt["returned_timestamp_counts_by_local_date"] = dict(day_counts)
               target_indices = [i for i, ts in enumerate(timestamps)
                                 if tz_name and datetime.fromtimestamp(ts, ZoneInfo(tz_name)).date() == target]
               quote = (((result or {}).get("indicators") or {}).get("quote") or [{}])[0]
               complete = 0
               complete_values = []
               for i in target_indices:
                   values = [((quote.get(k) or [])[i] if i < len(quote.get(k) or []) else None)
                             for k in ("open", "high", "low", "close", "volume")]
                   finite = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                and math.isfinite(v) for v in values)
                   if finite:
                       complete += 1
                       complete_values.append(values)
               receipt["target_date_timestamp_count"] = len(target_indices)
               receipt["target_date_complete_finite_ohlcv_count"] = complete
               if chart.get("error") is not None:
                   receipt["result"] = "YAHOO_CHART_ERROR"
               elif not all(receipt["meta_checks"].values()):
                   receipt["result"] = "CANNOT_CONFIRM_META"
               elif not target_indices:
                   receipt["result"] = "HTTP_200_NO_TARGET_TIMESTAMP"
               elif complete == 0:
                   receipt["result"] = "TARGET_DATE_NO_COMPLETE_FINITE_OHLCV"
               elif all(all(v == 0 for v in values) for values in complete_values):
                   receipt["result"] = "ALL_ZERO_PLACEHOLDER"
               else:
                   receipt["result"] = "TARGET_DATE_ROWS_PRESENT"
       except Exception as exc:
           # Do not store proxy URLs or credential-bearing exception text.
           receipt["result"] = "TLS_OR_TRANSPORT_ERROR" if "ssl" in type(exc).__name__.lower() else "REQUEST_ERROR"
           receipt["error_type"] = type(exc).__name__
       receipt["captured_at_end_utc"] = datetime.now(timezone.utc).isoformat()
       with receipt_path.open("x", encoding="utf-8") as stream:
           stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
       return receipt["result"] == "TARGET_DATE_ROWS_PRESENT"

   # Run one canary first. A failed canary is evidence to stop, not to retry.
   if not capture(args.codes[0]):
       raise SystemExit("Canary did not establish a usable target-date response; inspect receipt, do not retry blindly.")
   for code in args.codes[1:]:
       time.sleep(2)
       capture(code)  # isolate per-code errors; do not retry a failed code on identical inputs
   ```

## 读取与失败判读

- 保存 provider raw body 不改写，并为每个代码保存请求参数、capture UTC 起止、HTTP 状态、来源 ID、代码/ticker、目标日、交易所时区、币种（从 Yahoo meta 读取）、raw SHA、目标日时间戳数、完整 OHLCV 数、返回的其他本地日期计数。Yahoo 响应可能混入非目标日期（本批每码有 2026-09-30 时间戳）；raw 原样保留，派生数据只取香港时区下目标交易日的时间戳。
- canary 只有在 `chart.error` 为空，且 `meta.symbol` 与请求 ticker 一致、`exchangeName=HKG`（或 `fullExchangeName=Hong Kong Stock Exchange`）、`currency=HKD`、`dataGranularity=1m`、`exchangeTimezoneName=Asia/Hong_Kong`，目标日存在至少一个有限数值 OHLCV bar 且这些完整 bars 不全为零时才建立成功路由。单独记录目标日 timestamp 数与完整有限 OHLCV 数；null/NaN/全零不能算有效 canary。示例先用 `mkdir(exist_ok=False)` 拒绝已存在的输出目录，raw 与 receipt 再用排他创建，禁止覆盖旧证据。
- 标准化时保留原始返回顺序与 null；不得补 0、前向填充、估算成交额/turnover、推导买卖盘或暗示调整基础已确认。目标日有 raw 不等于阶段窗口有效或 `temporal_cutoff_safe=true`。
- 严格阶段窗口为 `(09:30:00, 09:35:00] Asia/Hong_Kong`。有日内数据但该窗口没有完整 bar，应保留为窗口缺口；不得把 `09:30` 纳入窗口。
- 分开记录错误：429 限流、403 拒绝、TLS/传输异常、HTTP 200 无目标日、全零占位。429/403/TLS 失败不是零行行情；全零不证明停牌或无交易。同一请求参数没有新证据时不重试、不换代理节点、不扩端点。
- Yahoo/AKShare/TDX 都是独立来源；没有对应 19 字段和来源/PIT 证明时，不得把它们投影或标记成 Futu 原始 stage 行。任何观察保持 WATCH_ONLY/研究用途，`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 本次验证样例（2026-10-05，非默认覆盖承诺）

证据目录：`/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/historical_restore_20261003/restore_candidate/publication_plan/r2_active_publication/day25_true_d1_r1/stage0930_true_d1/minute_gap19_repair/yahoo_20260925/`；汇总 `seven_code_summary.json` SHA-256 `f459c2fe046a759a80bc9295436ebf84f0e51cc4c9944bd73f96d4aa96d6d149`。本次七码共返回 2,585 个目标日时间戳、504 个完整 OHLCV bars；严格阶段窗口仅 4 个完整 bars、覆盖 3 个代码。以上只是这七码和该目标日的已核验证据，不代表其他代码、日期或全阶段覆盖。
