"""Immutable saved Manager Workbench API projections for the isolated read stack."""
from __future__ import annotations

from datetime import datetime
from hashlib import file_digest
from pathlib import Path
import re
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .static_projection import read_member
from .us_mapping_catalog import CatalogStore, CatalogValidationError, RECOVERY_OVERLAY_NAME

PREFIX = "/api/v4/manager-workbench"
LANES = ("US_MAPPING", "OVERSOLD")
Lane = Literal["US_MAPPING", "OVERSOLD"]
Phase = Literal["PREOPEN", "INTRADAY", "NEXT_DAY", "RETROSPECTIVE", "MANUAL"]
Decision = Literal["SELECTED", "CONDITIONAL_WATCH", "UNASSESSED", "NOT_SELECTED", "OBSERVATION_ONLY"]
SCHEMA = "v4.manager_workbench.v1"
MAX_PLAN = 64 * 1024 * 1024
MAX_LANE = 128 * 1024 * 1024
MAX_DETAIL = 256 * 1024 * 1024
SUMMARY_STOCK_FIELDS = ("symbol", "name", "decision", "reasons", "evidence_ids", "row_id",
                        "recommendation_lane", "display_only")
RELATION_FIELDS = ("symbol", "us_symbol", "relation_type", "decision", "reason", "reasons",
                   "quote", "source_sha256", "source_session", "available_at")
SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
CATALOG_BASE = "us_hk_667_catalog_20261015.json"
CATALOG_REVIEW = "us_hk_667_review_overlay_20261015.json"


def envelope(state, data=None, gaps=None):
    return {"schema_version": SCHEMA, "state": state, "data": data, "gaps": gaps or [], **SAFETY}


def check_date(value):
    try:
        if len(value) == 8 and datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d") == value:
            return value
    except ValueError:
        pass
    raise HTTPException(422, "DATE_INVALID")


class ManagerHistory:
    def __init__(self, root: Path, manifest_sha256: str):
        self.root = root
        self.manifest = read_member(root, "manifest.json", manifest_sha256, 4 * 1024 * 1024)
        if self.manifest.get("schema") != "v4.r21.manager_static_projection.v1":
            raise ValueError("MANAGER_STATIC_PROJECTION_SCHEMA")
        self.catalogued = CatalogStore()
        self.catalogue_paths = {}
        for name in (CATALOG_BASE, CATALOG_REVIEW, RECOVERY_OVERLAY_NAME):
            ref = self.manifest["catalogues"][name]
            path = root / name
            if path.resolve(strict=True) != path or path.stat().st_size != ref["bytes"]:
                raise ValueError("MANAGER_STATIC_CATALOG_FILE")
            with path.open("rb") as stream:
                if file_digest(stream, "sha256").hexdigest() != ref["sha256"]:
                    raise ValueError("MANAGER_STATIC_CATALOG_SHA")
            self.catalogue_paths[name] = path

    def versions(self, day):
        date = self.manifest["dates"].get(day, {})
        return date.get("versions", []), date.get("version_metadata_gaps", [])

    def resolve(self, day, phase, run_id):
        by_day = self.manifest["dates"].get(day, {})
        versions = by_day.get("versions", [])
        if run_id is None:
            pointers = [row for key, row in by_day.get("pointers", {}).items() if not phase or key == phase]
            if not pointers:
                return None, None
            run_id = max(pointers, key=lambda row: (row["generated_at"], row["run_id"]))["run_id"]
        version = next((row for row in versions if row["run_id"] == run_id and (phase is None or row["phase"] == phase)), None)
        if version is None:
            explicit = self.manifest.get("explicit_versions", {}).get(run_id)
            if explicit is None or explicit["date"] != day or (phase is not None and explicit["phase"] != phase):
                raise HTTPException(404, "ENTITY_NOT_FOUND")
            version = explicit
        entry = self.manifest["runs"].get(run_id)
        if not entry or entry["status"] != "READY":
            raise HTTPException(503, "STATIC_SAVED_VERSION_UNAVAILABLE")
        plan = self.member(entry["plan"])
        identity = plan["api_version"]
        if (identity["run_id"] != run_id or identity["product_sha256"] != version["product_sha256"]
                or plan["snapshot"]["context"]["target_date"] != day or identity["phase"] != version["phase"]):
            raise HTTPException(503, "STATIC_SAVED_VERSION_IDENTITY")
        return entry, plan

    def member(self, ref, limit=MAX_PLAN):
        if ref is None:
            return None
        try:
            return read_member(self.root, ref["file"], ref["sha256"], limit)
        except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
            raise HTTPException(503, "STATIC_SAVED_VERSION_UNAVAILABLE") from exc

    def details(self, entry, symbol):
        if "detail" in entry:
            return self.member(entry["detail"], MAX_DETAIL)
        common = self.member(entry["detail_common"])
        shards = entry["detail_shards"]
        match = next((shards[symbol[-5:][:i]] for i in (3,4,5) if symbol[-5:][:i] in shards), None)
        shard = self.member(match, MAX_DETAIL)
        shard = shard or {"stocks": {}, "lanes": {}}
        return {
            "factor_rules": common["factor_rules"],
            "stocks": shard["stocks"],
            "lanes": {lane: {"evidence": evidence, "symbols": shard["lanes"].get(lane, {}).get("symbols", {})}
                      for lane, evidence in common["evidence"].items()},
        }

    def catalogue(self, query, research_use, offset, limit):
        try:
            value = self.catalogued.search(
                self.catalogue_paths[CATALOG_BASE], self.catalogue_paths[CATALOG_REVIEW], query,
                offset=offset, limit=limit, research_use=research_use,
            )
        except CatalogValidationError as exc:
            raise HTTPException(503, "US_HK_MAPPING_CATALOG_INVALID") from exc
        return envelope("STRUCTURE_VALID", value, [
            "SOURCE_FACTS_NOT_INDEPENDENTLY_VERIFIED", "PREDICTION_UNTESTED", "HISTORICAL_PIT_NOT_VALIDATED",
        ])


def display_stock_name(row):
    saved_name = row.get("name")
    if not isinstance(saved_name, dict) or set(saved_name) != {"name", "name_source"}:
        return row
    label, source = saved_name["name"], saved_name["name_source"]
    if not isinstance(label, str) or not label.strip() or not isinstance(source, dict):
        return row
    if "name_source" in row and row["name_source"] != source:
        if "saved_name_source" in row and row["saved_name_source"] != source:
            return row
        return {**row, "name": label, "saved_name_source": source}
    return {**row, "name": label, "name_source": source}


def page(rows, offset, limit):
    return {"stocks":[display_stock_name(row) for row in rows[offset:offset+limit]],
            "pagination":{"total":len(rows),"offset":offset,"limit":limit}}


def empty_plan(versions, gaps, offset, limit):
    return {"snapshot":None,"counts":None,"versions":versions,
            "version_metadata_gaps":gaps,**page([],offset,limit)}


def _focus_decision_matches(row, decision):
    actual = row.get("decision")
    if row.get("focus_decision"):
        focus_allowed = {"NOT_SELECTED": ("CAPPED", "NOT_TRIGGERED"), "UNASSESSED": ("PENDING",)}
        return actual in focus_allowed.get(decision, (decision,))
    return actual == decision


def search_rows(rows, query, *, keys=("symbol", "name")):
    if not query:
        return rows
    term = query.casefold()
    return [r for r in rows if term in " ".join(str(r.get(k) or "") for k in keys).casefold()]


def legacy_search(rows, query):
    if not query:
        return rows
    term = query.casefold()
    keys = ("symbol", "name", "us_symbol", "theme", "source_industry")
    return [row for row in rows if any(term in str(row.get(key) or "").casefold() for key in keys)]


def paginate_legacy_summary(value, offset, limit):
    if value is None:
        return None
    summary = value.get("factor_summary", {}).get("single_day_mapping")
    if not isinstance(summary, dict):
        return value
    rows = summary["rows"][offset:offset+limit]
    product = {**summary, "rows": rows,
               "benefit_rows": [r for r in rows if r["decision"]=="BENEFIT"],
               "risk_rows": [r for r in rows if r["decision"]=="RISK"],
               "pagination": {"total": summary["pagination"]["total"], "offset": offset, "limit": limit}}
    return {**value, "factor_summary": {**value["factor_summary"], "single_day_mapping": product}}


def compact_projection(body, q, decision, symbol, offset, limit, relationship_offset, relationship_limit):
    rows = search_rows(body["stocks"], q, keys=("symbol","name","research_state","direction"))
    if symbol:
        rows = [row for row in rows if row["symbol"] == symbol]
    if decision:
        rows = [row for row in rows if _focus_decision_matches(row, decision)]
    result = {**body, **page(rows, offset, limit)}
    if any("relationships" in row for row in result["stocks"]):
        result["stocks"] = [
            {**row, "relationships":row["relationships"][relationship_offset:relationship_offset+relationship_limit],
             "relationship_pagination":{"total":row["relationship_pagination"]["total"],
                                        "offset":relationship_offset,"limit":relationship_limit}}
            if "relationships" in row else row for row in result["stocks"]
        ]
    return result


def read_stock_detail(data, symbol, run_id, lane_order, lane=None, row_id=None):
    item = data["stocks"].get(symbol)
    selected = None
    if lane:
        chosen = data["lanes"].get(lane)
        if not chosen or row_id is None or re.fullmatch(re.escape(lane) + r":[0-9]+", row_id) is None:
            raise HTTPException(422, "LANE_ROW_IDENTITY_INVALID")
        index = int(row_id.partition(":")[2])
        selected = next((item for item in chosen["symbols"].get(symbol, ()) if item["index"] == index), None)
        if selected is None:
            raise HTTPException(422, "LANE_ROW_IDENTITY_INVALID")
        item = selected.get("stock") or item
    elif item is None:
        raise HTTPException(404, "ENTITY_NOT_FOUND")
    if item is None:
        raise HTTPException(404, "ENTITY_NOT_FOUND")
    details = []
    for name in lane_order:
        value = data["lanes"][name]
        if lane and lane != name:
            continue
        rows = [member["display"] for member in value["symbols"].get(symbol, ())]
        if selected and selected["stock"] and not (lane == "US_MAPPING" and data["factor_rules"]):
            rows = [selected["raw"]]
        ids = item["evidence_ids"]
        refs = [ev for ev in value["evidence"] if ev["evidence_id"] in ids]
        details.append({"lane":name,"rows":rows,"evidence_refs":refs})
    return envelope("READY", {"plan_run_id":run_id,"stock":display_stock_name(item),"recommendation_lane":lane,
                              "display_projection":{"display_only":True,"snapshot_hash_basis":"ORIGINAL_SAVED_SNAPSHOT"},
                              "lane_details":details})


def create_manager_app(reader):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid_parameters(request, error):
        return JSONResponse(envelope("FAILED", None, ["REQUEST_VALIDATION_FAILED"]), status_code=422)

    @app.exception_handler(HTTPException)
    async def invalid_lookup(request, error):
        code = error.detail if isinstance(error.detail, str) and re.fullmatch(r"[A-Z0-9_]{1,128}", error.detail) else "REQUEST_FAILED"
        return JSONResponse(envelope("FAILED", None, [code]), status_code=error.status_code)

    @app.get(PREFIX + "/history")
    def history(date: str):
        versions, gaps = reader.versions(check_date(date))
        return envelope("READY" if versions else "NOT_RUN", {"date":date,"versions":versions,"version_metadata_gaps":gaps})

    @app.get(PREFIX + "/mapping-catalog")
    def catalogue(q: str | None = Query(None,max_length=128),
                  research_use: str | None = Query(None,pattern="^(PENDING_REVIEW|CONDITIONAL_OBSERVATION|BACKGROUND_HISTORICAL|EXCLUDED_CURRENT)$"),
                  offset: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=200)):
        return reader.catalogue(q,research_use,offset,limit)

    @app.get(PREFIX + "/days/{date}/recommendations/{lane}")
    def recommendations(date: str, lane: Lane, phase: Phase | None = None, run_id: str | None = None,
                        offset: int = Query(0,ge=0),limit: int = Query(50,ge=1,le=200),
                        decision: Decision | None = None,q: str | None = Query(None,max_length=128),
                        view: Literal["compact","diagnostics"] | None = None,
                        projection: Literal["focus","catalogue"] = "focus",
                        symbol: str | None = Query(None,pattern=r"^HK\.[0-9]{5}$"),
                        relationship_offset: int = Query(0,ge=0),
                        relationship_limit: int = Query(50,ge=1,le=200)):
        check_date(date)
        versions, gaps = reader.versions(date)
        entry, plan = reader.resolve(date, phase, run_id)
        if plan is None:
            return envelope("NOT_RUN",empty_plan(versions,gaps,offset,limit),["NO_SAVED_PLAN"])
        index = plan["api_version"]
        versions = sorted([*filter(lambda x: x["run_id"] != index["run_id"], versions), index],
                          key=lambda x: (x["generated_at"],x["run_id"]),reverse=True)
        branch = lane.lower()
        reference = entry.get(branch)
        if reference is None:
            data = empty_plan(versions,gaps,offset,limit)
            data.pop("version_metadata_gaps", None)
            if view is None:
                data["snapshot"] = plan["snapshot"]
            return envelope("NOT_RUN", data, ["LANE_NOT_SAVED"])
        saved = reader.member(reference, MAX_LANE) if lane == "US_MAPPING" else reader.member(reference)
        if view or saved["industry_default"]:
            mode = "diagnostics" if view == "diagnostics" else projection
            body = reader.member(entry[f"{branch}_{mode}"], MAX_DETAIL)
            if not saved["saved_selection"]:
                selected_rows = saved["decisions"].get(decision, []) if decision else saved["stocks"]
                selected_rows = legacy_search(selected_rows, q)
                by_id = {row.get("row_id"): row for row in body["stocks"]}
                briefs = [by_id.get(raw["row_id"]) or {key: raw.get(key) for key in SUMMARY_STOCK_FIELDS}
                          for raw in selected_rows]
                body = {**body, "stocks": briefs,
                        "us_mapping_summary": paginate_legacy_summary(body.get("us_mapping_summary"), offset, limit)}
                q = None
            result = compact_projection(body, q, decision, symbol, offset, limit,
                                        relationship_offset, relationship_limit)
            if view == "diagnostics" and not saved["saved_selection"] and decision:
                for index, brief in enumerate(result["stocks"]):
                    if "relationships" in brief:
                        continue
                    detail = reader.details(entry, brief["symbol"])["lanes"][lane]["symbols"]
                    relations = [{key: (item["raw"] or item["display"]).get(key) for key in RELATION_FIELDS}
                                 for item in detail.get(brief["symbol"], [])]
                    result["stocks"][index] = {**brief,
                        "relationships": relations[relationship_offset:relationship_offset+relationship_limit],
                        "relationship_pagination":{"total":len(relations),"offset":relationship_offset,
                                                   "limit":relationship_limit}}
            return envelope(body["lane_state"],{**result,"versions":versions,"version_metadata_gaps":gaps},saved["gaps"])
        rows = saved["decisions"].get(decision, []) if decision else saved["stocks"]
        rows = search_rows(rows,q) if saved["saved_selection"] else legacy_search(rows,q)
        counts = plan.get("counts")
        if counts is None:
            counts = {name: (reader.member(entry[name.lower()], MAX_LANE)["selection"]["counts"]
                             if name.lower() in entry else None) for name in LANES}
        result = {**saved["selection"], **page(rows,offset,limit), "snapshot": plan["snapshot"],
                  "versions":versions,"recommendation_counts":counts,
                  "us_mapping_summary":saved["default_summary"]}
        return envelope(saved["selection"]["lane_state"],result,saved["gaps"])

    @app.get(PREFIX + "/stocks/{symbol}")
    def stock(symbol: str, date: str, run_id: str, lane: Lane | None = None, row_id: str | None = None):
        check_date(date)
        if re.fullmatch(r"HK\.[0-9]{5}",symbol) is None:
            raise HTTPException(422,"SYMBOL_INVALID")
        entry, plan = reader.resolve(date, None, run_id)
        lanes = [item["lane"] for item in plan["snapshot"]["lanes"]]
        return read_stock_detail(reader.details(entry, symbol), symbol, run_id, lanes, lane, row_id)

    @app.get(PREFIX + "/reviews/{date}")
    def reviews(date: str, plan_run_id: str):
        _, plan = reader.resolve(check_date(date), None, plan_run_id)
        return (envelope("READY",plan["review"],plan["review_gaps"]) if plan["review"] else
                envelope("NOT_RUN",None,["SAME_DATE_CLOSE_INPUT_UNAVAILABLE"]))
    return app
