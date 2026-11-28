"""Date-scoped read-only projection installed inside the isolation guard."""
import json
from hashlib import sha256
from urllib.parse import parse_qs, parse_qsl, urlencode

from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from .read_preselection import BoundPreselection, PATH as PRESELECTION
from .read_scheduled_lane import ScheduledLaneReader
from .workbench_parity import WorkbenchParity
from .seven_p0_reads import SevenP0Reads
from .formal_admission_reads import FormalAdmissionReads
from .closure_reads import ARCHIVE_STATE, ClosureReads, SLOT1_ROUTE, STAGE_ROUTE, STAGE_BATCH_ROUTE

from .slot1_reads import Slot1Reads
from .wechat_reads import WECHAT_PREFIX, WechatReads

from .stage_observation_reads import StageObservationReads
from .preopen_source_reads import ARCHIVE_PATH, PreopenSourceReads

STAGE_DATE = "20261127"
LANE = "/api/v4/research/lane"
DAY = "/api/v4/research/day"
MACHINE_CARDS = "/api/v4/research/machine-cards"
DATES = "/api/v4/research/dates"
RUN_DATES = "/api/v1/runs/date-list"
REVIEW = "/api/v4/review"
SAFETY = ("production_allowed", "buy_gate_updated", "orders_sent")
D24_WORKBENCH = "/api/v4/research/workbench/days/2026-11-24"
D24_REVISION = "660df6bf22e9069e56d6017911f61ed685ab3e1cb1cc78773ff37b10a71e0247"


def selected_date(query):
    return query.get("research_date", query.get("date", []))


def stage_or_research(query):
    return query.get("view", []) in ([], ["stage"], ["research"])


def date_as_compact(value):
    return value.replace("-", "")


def read_archive(root):
    manifest = json.loads((root / "projection_manifest.json").read_bytes())
    if manifest["version"] != "r21_research_exact_days.v2" or any(manifest[k] is not False for k in SAFETY):
        raise ValueError("R21_RESEARCH_ARCHIVE_MANIFEST_INVALID")
    documents = {}
    for date, dated in manifest["dates"].items():
        if date not in ("20261125", "20261126", "20261127"):
            raise ValueError("R21_RESEARCH_ARCHIVE_DATE_NOT_BOUND")
        docs = {}
        for key in ("lane", "day", "machine_cards", "wechat"):
            ref = dated[key]
            name = f"{key}_{date}.json"
            path = root / name
            if ref["file"] != name or path.resolve() != path:
                raise ValueError("R21_RESEARCH_ARCHIVE_MEMBER_INVALID")
            raw = path.read_bytes()
            if len(raw) != ref["bytes"] or sha256(raw).hexdigest() != ref["sha256"]:
                raise ValueError("R21_RESEARCH_ARCHIVE_MEMBER_MISMATCH")
            docs[key] = json.loads(raw)
        lane, day, cards, wechat = (docs[key] for key in ("lane", "day", "machine_cards", "wechat"))
        if (
            lane["research_date"] != date or day["archive_date"] != date
            or cards["research_date"] != date or wechat["query"]["date"] != date
            or lane["daily_archive_status"] != day["status"] or day["status"] != "READY_WITH_DECLARED_GAPS"
            or lane["status"] != "LIVE_HOURLY" or day["authoritative"] is not False
            or any(doc[k] is not False for doc in docs.values() for k in SAFETY)
        ):
            raise ValueError("R21_RESEARCH_ARCHIVE_MEMBER_CLASS_INVALID")
        documents[date] = docs
    if set(documents) != {"20261125", "20261126", "20261127"}:
        raise ValueError("R21_RESEARCH_ARCHIVE_DATE_SET_INVALID")
    return documents


class ContentProjection:
    def __init__(self, app, data, dist):
        self.app = WorkbenchParity(app, data)
        self.research = read_archive(data / "r21_research_archive")
        self.scheduled = ScheduledLaneReader(data.parent.parent / "research_e2e_20261127/scheduled_jobs")
        self.preselection = BoundPreselection(app.state.store, data / "r21_preselection_proof.json")
        self.seven_p0_reads = SevenP0Reads(app.state.store, data, self.preselection)
        self.formal_admission = FormalAdmissionReads(data, self.seven_p0_reads)
        self.closure_reads = ClosureReads(data.parent.parent)
        self.stage_observations = StageObservationReads(self.closure_reads, self.preselection.proof)
        self.slot1_reads = Slot1Reads(data.parent.parent, self.closure_reads)
        self.wechat_reads = WechatReads()
        self.preopen_source_reads = PreopenSourceReads(data.parent.parent)
        self.review = json.loads((data / "r21_d27_close_review.json").read_bytes())
        if (
            self.review["trade_date"] != "2026-11-27" or self.review["status"] != "CANNOT_CONFIRM"
            or any(self.review[k] is not False for k in SAFETY)
        ):
            raise ValueError("R21_D27_REVIEW_CLASS_INVALID")
        self.symbol_content = {
            row["route"]: row["payload"]
            for row in json.loads((data / "r21_d24_symbol_content.json").read_bytes()).values()
        }
        if set(self.symbol_content) != {
                D24_WORKBENCH + "/formula-daily-k/920770.BJ",
                D24_WORKBENCH + "/single-research/920770.BJ",
        } or any(
            payload["source_date"] != "2026-11-24" or payload["symbol"] != "920770.BJ"
            or payload["generation"] != D24_REVISION
            or any(payload[key] is not False for key in SAFETY)
            for payload in self.symbol_content.values()
        ):
            raise ValueError("D24_SYMBOL_CONTENT_BINDING_INVALID")
        self.html = (dist / "index.html").read_text(encoding="utf-8")
        if self.html.count("<body>") != 1:
            raise ValueError("ISOLATED_FRONTEND_BODY_NOT_UNIQUE")

    def root_html(self, date, research_selected):
        day = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        source_note = ("已核验研究日档（保留缺口）；股票层只列明确标题证据。"
                       if research_selected else "阶段记录未获自然验证。")
        identity = "研报决策台" if research_selected else day
        banner = ('<aside role="status" style="padding:10px 16px;background:#eff6f4;color:#17372d;'
                  'border-bottom:1px solid #c5d9d1;font:14px system-ui">'
                  f'隔离只读快照 · {identity} · {source_note}'
                  '</aside>')
        if research_selected:
            banner += self.closure_reads.banner(date)
        return self.html.replace("<body>", "<body>" + banner, 1)

    def research_response(self, key, requested):
        date = date_as_compact(requested[0]) if len(requested) == 1 else self.latest_research_date()
        if len(requested) > 1:
            return None
        mode = "EXACT" if requested else "LATEST"
        payload = self.base_research_response(key, date, mode)
        if payload is None:
            return None
        if key == "lane":
            payload = self.preopen_source_reads.lane(payload, date)
        if key == "lane" and (slot := self.slot1_reads.for_date(date)):
            payload = {**payload, "preopen_research": slot}
        return payload

    def base_research_response(self, key, date, mode):
        legacy_lane = self.closure_reads.lanes.get(date)
        if date in self.research:
            payload = {**self.research[date][key], "endpoint_mode": mode}
            if key == "lane" and legacy_lane:
                payload["legacy_readonly_detail"] = {
                    "scope": ARCHIVE_STATE, "research_date": date,
                    **{field: legacy_lane[field] for field in (
                        "stock_research_daily", "stock_research_timeline", "source_binding",
                        "isolated_legacy_read", "morning_news", "news_workbench")
                       if field in legacy_lane},
                }
            elif key == "day":
                owner_day = self.closure_reads.legacy(date, "research_day")
                if owner_day and owner_day.get("status") == payload.get("status"):
                    payload = {**owner_day, **payload, "legacy_readonly_detail": {
                        "scope": ARCHIVE_STATE, "archive_date": date,
                        "owner_counts": owner_day.get("counts"),
                        "source_binding": owner_day.get("isolated_legacy_read"),
                    }}
            return payload
        if key == "lane" and legacy_lane:
            return {**legacy_lane, "RESEARCH_ONLY": True, "endpoint_mode": mode, "legacy_readonly_detail": {
                "scope": ARCHIVE_STATE, "research_date": date,
            }}
        if key == "day":
            legacy_day = self.closure_reads.legacy(date, "research_day")
            if legacy_day is not None:
                return {**legacy_day, "endpoint_mode": mode}
        lane = self.scheduled.get(date)
        if lane is None:
            return None
        if key == "lane":
            return {**lane, "endpoint_mode": mode}
        return {
            "schema_version": "v3_5.research_day_product.v1",
            "status": "NOT_MATERIALIZED", "authoritative": False, "endpoint_mode": mode,
            "archive_date": date, "requested_date": date, "resolved_date": None,
            "cannot_confirm": ["ISOLATED_DAY_DTO_NOT_BOUND"],
            "reason": "已核验同日研报流，独立正式日档 DTO 未接入。",
            "write_policy": "read_only", "recommendation_status": "RESEARCH_ONLY",
            "RESEARCH_ONLY": True, **dict.fromkeys(SAFETY, False),
        }

    def research_date_set(self):
        return self.research.keys() | self.scheduled.recent_dates() | self.closure_reads.lanes.keys()

    def latest_research_date(self):
        return max(self.research_date_set())

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD"):
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == WECHAT_PREFIX or path.startswith(WECHAT_PREFIX + "/"):
            return await self.wechat_reads(scope, receive, send)
        query_string = scope["query_string"].decode("latin-1")
        query = parse_qs(query_string, keep_blank_values=True)
        response = None
        if path == "/" and stage_or_research(query):
            research_selected = query.get("view") == ["research"]
            if "date" not in query:
                fields = parse_qsl(query_string, keep_blank_values=True)
                date = self.latest_research_date() if research_selected else STAGE_DATE
                response = RedirectResponse("/?" + urlencode([*fields, ("date", date)]), status_code=307,
                                            headers={"Cache-Control": "no-store"})
            elif len(query["date"]) == 1:
                date = date_as_compact(query["date"][0])
                if (research_selected and date in self.research_date_set()) or (
                    not research_selected and date == STAGE_DATE
                ):
                    response = HTMLResponse(self.root_html(date, research_selected), headers={"Cache-Control": "no-cache"})
        elif path == ARCHIVE_PATH:
            response = self.preopen_source_reads.resolve(query)
        elif path == SLOT1_ROUTE and set(query) == {"date"} and len(query["date"]) == 1:
            slot = self.slot1_reads.for_date(query["date"][0])
            if slot is not None:
                response = JSONResponse(slot, headers={"Cache-Control": "no-store"})
        elif path == LANE and set(query) in (set(), {"date"}, {"research_date"}):
            payload = self.research_response("lane", selected_date(query))
            if payload is not None:
                response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
        elif path == DAY and set(query) in (set(), {"archive_date"}):
            payload = self.research_response("day", query.get("archive_date", []))
            if payload is not None:
                response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
        elif path == MACHINE_CARDS and set(query) == {"research_date"}:
            date = query["research_date"]
            if len(date) == 1:
                compact = date_as_compact(date[0])
                cards = self.research.get(compact, {}).get("machine_cards")
                cards = cards or self.closure_reads.legacy(compact, "research_machine_cards")
                if cards is not None:
                    response = JSONResponse(cards, headers={"Cache-Control": "no-store"})
        elif path == DATES and not query and scope["method"] == "GET":
            return await self.with_native_json(scope, receive, send, self.research_dates)
        elif path == RUN_DATES and not query and scope["method"] == "GET":
            return await self.with_native_json(scope, receive, send, self.run_dates)
        elif path == PRESELECTION:
            try:
                payload = await run_in_threadpool(self.project_preselection, query_string)
            except (ValueError, KeyError):
                response = JSONResponse({"detail": "R21_D1_OWNER_SNAPSHOT_NOT_BOUND"}, status_code=409)
            else:
                if payload is not None:
                    response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
        elif path == REVIEW and set(query) == {"date"} and query["date"] in (["20261127"], ["2026-11-27"]):
            review = {**self.review, "trade_date": query["date"][0]}
            transform = self.formal_admission.native_transform(path, query)
            review = self.project_review(transform(review), query["date"][0])
            response = JSONResponse(review, headers={"Cache-Control": "no-store"})
        elif path in self.symbol_content:
            if query not in ({}, {"revision": [D24_REVISION]}):
                response = JSONResponse({"detail": "ISOLATED_SOURCE_REVISION_NOT_BOUND"}, status_code=404)
            else:
                response = JSONResponse(self.symbol_content[path], headers={"Cache-Control": "no-store"})
        if response is None:
            response = self.formal_admission.resolve(path, query)
        if response is None:
            response = self.seven_p0_reads.resolve(path, query)
        if response is None and scope["method"] == "GET":
            transform = self.formal_admission.native_transform(path, query)
            transform = self.closure_transform(path, query, transform)
            if transform is not None:
                return await self.with_native_json(scope, receive, send, transform)
        if response is None:
            return await self.app(scope, receive, send)
        if scope["method"] == "HEAD":
            response.body = b""
        return await response(scope, receive, send)

    def project_preselection(self, query_string):
        payload = self.preselection.requested(query_string)
        return self.stage_observations.preselection(payload) if payload is not None else None

    def project_review(self, value, date):
        review = self.stage_observations.review(self.closure_reads.review(value, date), date)
        markets = review.get("market_reviews", {})
        if "A" in markets and "HK" in markets:
            return review

        # Keep evidence-empty exact dates renderable after all owner projections.
        # An owner-supplied market always takes precedence over a pending DTO.
        day = review["trade_date"]
        if "A" not in markets:
            markets = {**markets, "A": {
                "trade_date": day, "status": "NOT_MATERIALIZED",
                "big_picture": [], "mainlines": [], "core_stocks": [],
                "observation_pool": [], "next_day_trigger_tree": [], "quality_gate": [],
                "cannot_confirm": ["A_SHARE_REVIEW_NOT_MATERIALIZED"],
            }}
        if "HK" not in markets:
            markets = {**markets, "HK": {"market": "HK", "model_selection_review": {
                "trade_date": day, "status": "REFERENCE_NOT_IMPORTED",
                "cannot_confirm": ["CLOSE_REVIEW_REFERENCE_NOT_IMPORTED"],
            }}}
        return {**dict.fromkeys(SAFETY, False), **review, "market_reviews": markets}

    def closure_transform(self, path, query, native):
        dates = query.get("date", [])
        if path == "/api/v4/tasks/status" and native:
            return lambda value: self.slot1_reads.tasks(native(value), dates[0] if dates else None)
        if len(dates) != 1:
            return native
        date = dates[0]
        if path == REVIEW and native:
            return lambda value: self.project_review(native(value), date)
        if path == STAGE_BATCH_ROUTE and set(query) <= {"date", "stages"}:
            return lambda value: self.closure_reads.batch(value, date)
        if path == STAGE_ROUTE and set(query) <= {"date", "stage", "market", "limit", "source_date"}:
            stage = query.get("stage", ["STAGE_0930_0935"])
            market = query.get("market", ["ALL"])
            limit = query.get("limit", ["50"])
            source = query.get("source_date", dates)
            variants = {"ALL": None, "A": "A", "A_SHARE": "A", "HK": "HK", "HK_CONNECT": "HK"}
            if (len(stage) == len(market) == len(limit) == len(source) == 1
                    and market[0].upper() in variants and limit[0].isdigit()):
                def project_stage(value):
                    payload = native(value) if native else value
                    kind = variants[market[0].upper()]
                    row_limit = int(limit[0])
                    if date_as_compact(date) == date_as_compact(source[0]):
                        payload = self.closure_reads.stage(payload, date, stage[0], kind, row_limit)
                    return self.stage_observations.prior_stage7(
                        payload, date, source[0] if "source_date" in query else None, stage[0], kind, row_limit)
                return project_stage
        return native

    def research_dates(self, payload):
        bound = self.research_date_set()
        dates = sorted({date_as_compact(day) for day in payload["dates"]} | bound, reverse=True)
        return {**payload, "dates": dates, "research_dates": dates, "latest_date": max(bound)}

    def run_dates(self, payload):
        today = payload["system_date"]
        days = set(self.preselection.proof)
        dates = sorted(set(payload["stage_navigation_dates"]) | days, reverse=True)
        future = sorted(set(payload["future_target_dates"]) | {date for date in days if date > today})
        research = sorted(set(payload["research_dates"]) | self.research_date_set())
        return {**payload, "stage_navigation_dates": dates, "future_target_dates": future,
                "research_dates": research, "runtime_identity": self.formal_admission.identity.runtime()}

    async def with_native_json(self, scope, receive, send, transform):
        # Preserve native non-200 responses and project only verified read contracts.
        start = None

        async def add_date(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                if start["status"] == 200:
                    return
            elif message["type"] == "http.response.body" and start is not None and start["status"] == 200:
                if message.get("more_body"):
                    raise RuntimeError("R21_RESEARCH_DATE_CATALOG_STREAMING")
                def project_response():
                    payload = json.loads(message["body"])
                    return JSONResponse(transform(payload), headers={"Cache-Control": "no-store"})

                if scope["path"] in (STAGE_ROUTE, STAGE_BATCH_ROUTE):
                    response = await run_in_threadpool(project_response)
                else:
                    response = project_response()
                return await response(scope, receive, send)
            await send(message)

        return await self.app(scope, receive, add_date)
