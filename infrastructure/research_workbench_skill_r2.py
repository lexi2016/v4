"""Read-only adapter for the explicitly bound D28 skill R2 artifact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode

ASOF = "20261028"
ISO_DATE = "2026-10-28"
RULESET = "ZGE_SKILL_DAILY_CANDIDATES_R2"
GROUPS = ("skill_r2_b1", "skill_r2_nana", "skill_r2_super_b1", "skill_r2_sb1",
          "skill_r2_b2", "skill_r2_b3", "skill_r2_parallel", "skill_r2_rebuild", "skill_r2_platform")
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
FORMULA_SHA = "d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac"


def _path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute() or p.is_symlink() or p.resolve(strict=True) != p:
        raise ValueError("SKILL_R2_PATH_INVALID")
    return p


def _bytes(ref: dict) -> bytes:
    if not isinstance(ref, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", ""))):
        raise ValueError("SKILL_R2_REFERENCE_INVALID")
    raw = _path(ref["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("SKILL_R2_SOURCE_SHA_DRIFT")
    return raw


def _same_ref(a: dict, b: dict) -> bool:
    return isinstance(a, dict) and isinstance(b, dict) and all(a.get(k) == b.get(k) for k in ("path", "sha256"))


def _flags(value: dict) -> bool:
    return all(value.get(k) is v for k, v in FLAGS.items())


class SkillR2Workbench:
    def __init__(self, config: dict):
        if not isinstance(config, dict) or config.get("schema") != "ZGE_SKILL_D28_WORKBENCH_BINDING_V1":
            raise ValueError("SKILL_R2_BINDING_INVALID")
        self.config = config
        self._candidate_cache = None
        self._chart_cache = None

    def _receipt(self):
        ref = self.config.get("receipt")
        receipt = json.loads(_bytes(ref))
        source = receipt.get("source", {})
        if (receipt.get("schema") != "zge_skill_d28_screen_run/1" or receipt.get("asof") != ASOF
                or receipt.get("ruleset_id") != RULESET or not _flags(receipt)
                or receipt.get("counts", {}).get("accepted_target_rows") != 5538
                or receipt.get("counts", {}).get("quarantine_retained_separately") != 270
                or set(receipt.get("enabled_groups", [])) != set(GROUPS)):
            raise ValueError("SKILL_R2_RECEIPT_IDENTITY_CONFLICT")
        source_receipt = json.loads(_bytes({"path": source["receipt_path"], "sha256": source["receipt_sha256_actual"]}))
        generation = source_receipt.get("formula", {}).get("authority", {}).get("generation_id")
        source_input = source_receipt.get("formula", {}).get("authority", {}).get("source_sha256")
        if (source_receipt.get("target_date") != ASOF or generation != source.get("generation_id")
                or source_receipt.get("selector_sha256") != source.get("selector_sha256_declared")
                or not re.fullmatch(r"[0-9a-f]{64}", str(generation or ""))
                or not re.fullmatch(r"[0-9a-f]{64}", str(source_input or ""))):
            raise ValueError("SKILL_R2_SOURCE_IDENTITY_CONFLICT")
        candidate_ref = receipt.get("artifacts", {}).get("d28_candidate_union_R2.jsonl")
        if not isinstance(candidate_ref, dict) or _path(candidate_ref["path"]).parent != _path(ref["path"]).parent:
            raise ValueError("SKILL_R2_CANDIDATE_PATH_CONFLICT")
        return receipt, candidate_ref, generation, source_input

    def _candidates(self, receipt, ref, generation):
        path = _path(ref["path"])
        st = path.stat()
        key = (ref["sha256"], st.st_ino, st.st_size, st.st_mtime_ns)
        if self._candidate_cache and self._candidate_cache[0] == key:
            return self._candidate_cache[1]
        rows = [json.loads(line) for line in _bytes(ref).splitlines() if line.strip()]
        if len(rows) != receipt["counts"]["candidate_union"] or len(rows) != len({r["ts_code"] for r in rows}):
            raise ValueError("SKILL_R2_CANDIDATE_COUNT_CONFLICT")
        for row in rows:
            branches = row.get("branches", {})
            raw = row.get("raw_hit_group_ids", [])
            if (not re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", str(row.get("ts_code", "")))
                    or row.get("asof") != ASOF or row.get("ruleset_id") != RULESET
                    or row.get("source_generation") != generation
                    or row.get("ruleset_sha256") != receipt["ruleset"]["sha256"]
                    or set(branches) != set(GROUPS) or not raw or len(raw) != len(set(raw))
                    or set(raw) != {g for g in GROUPS if branches[g].get("seed_state") == "TRUE"}
                    or row.get("name_source_date") and row["name_source_date"] > ASOF):
                raise ValueError("SKILL_R2_ROW_IDENTITY_CONFLICT")
        self._candidate_cache = key, rows
        return rows

    def _charts(self, receipt, candidate_ref, generation, source_input):
        ref = self.config.get("chart_manifest")
        if not ref:
            return None
        p = _path(ref["path"])
        st = p.stat()
        key = (ref["sha256"], st.st_ino, st.st_size, st.st_mtime_ns)
        if self._chart_cache and self._chart_cache[0] == key:
            return self._chart_cache[1]
        chart = json.loads(_bytes(ref))
        if (chart.get("schema") != "ZGE_SKILL_D28_ORIGINAL_CHARTS_V1" or chart.get("source_date") != ASOF
                or chart.get("source_generation") != generation or chart.get("source_input_sha256") != source_input
                or chart.get("source_selector_sha256") != receipt["source"]["selector_sha256_declared"]
                or chart.get("ruleset_id") != RULESET or chart.get("rule_config_sha256") != receipt["ruleset"]["sha256"]
                or not _same_ref(chart.get("lineage", {}).get("screen_receipt"), self.config["receipt"])
                or not _same_ref(chart.get("lineage", {}).get("candidate_artifact"), candidate_ref)
                or not _flags(chart) or not isinstance(chart.get("samples"), dict)):
            raise ValueError("SKILL_R2_CHART_IDENTITY_CONFLICT")
        self._chart_cache = key, chart
        return chart

    def _sample(self, chart, code):
        if chart is None:
            return None
        sample = chart["samples"].get(code)
        if not isinstance(sample, dict) or sample.get("status") != "READY":
            return None
        if (sample.get("symbol") != code or sample.get("data_date") != ASOF
                or str(sample.get("last_date")) != ASOF or sample.get("values_per_row") != 51
                or sample.get("drawings_per_row") != 22 or not _flags(sample)
                or not isinstance(sample.get("rows"), int) or sample["rows"] < 1):
            raise ValueError("SKILL_R2_SAMPLE_IDENTITY_CONFLICT")
        root = _path(self.config["chart_manifest"]["path"]).parent
        for kind in ("PNG", "html", "projection"):
            ref = sample.get(kind)
            if not isinstance(ref, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", ""))):
                raise ValueError("SKILL_R2_SAMPLE_REFERENCE_INVALID")
            if not _path(ref["path"]).is_relative_to(root):
                raise ValueError("SKILL_R2_SAMPLE_PATH_ESCAPE")
        return sample

    def _reviews(self, candidate_ref, chart):
        path_string = self.config.get("review_path")
        if not path_string or not Path(path_string).exists():
            return {}, "NOT_REVIEWED", None
        try:
            raw = _path(path_string).read_bytes()
            review = json.loads(raw)
            chart_ref = self.config.get("chart_manifest")
            if (chart is None or review.get("schema") != "ZGE_SKILL_D28_CHART_REVIEW_V1"
                    or review.get("asof") != ASOF or review.get("ruleset_id") != RULESET
                    or review.get("source_generation") != chart["source_generation"]
                    or not _same_ref(review.get("candidate_artifact"), candidate_ref)
                    or not _same_ref(review.get("chart_manifest"), chart_ref)
                    or not _flags(review) or not isinstance(review.get("rows"), dict)):
                raise ValueError("SKILL_R2_REVIEW_IDENTITY_CONFLICT")
            return review["rows"], "AVAILABLE", hashlib.sha256(raw).hexdigest()
        except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError):
            return {}, "ERROR_REVIEW_BINDING", None

    def _review_for(self, code, reviews, sample, status, generation):
        if status == "ERROR_REVIEW_BINDING":
            return {"status": status, "decision": None, "actual_image_viewed": False}
        item = reviews.get(code)
        if item is None:
            return {"status": "NOT_REVIEWED", "decision": None, "actual_image_viewed": False}
        if (not isinstance(item, dict) or sample is None or item.get("actual_image_viewed") is not True
                or item.get("symbol") != code or item.get("asof") != ASOF
                or item.get("ruleset_id") != RULESET or item.get("source_generation") != generation
                or item.get("decision") not in {"KEEP", "WATCH", "DEFER"}
                or item.get("image_sha256") != sample["PNG"]["sha256"]
                or not isinstance(item.get("visible_evidence"), list) or not item["visible_evidence"]
                or not any(isinstance(text, str) and text.strip() for text in item["visible_evidence"])
                or not isinstance(item.get("counter_evidence"), list)
                or not all(isinstance(item.get(k), str) and item[k].strip()
                           for k in ("reason", "reviewer_id", "reviewed_at"))):
            return {"status": "ERROR_REVIEW_RECORD", "decision": None, "actual_image_viewed": False}
        return {**item, "status": "REVIEWED"}

    def _asset_url(self, code, kind, ref, generation):
        return (f"/api/v4/research/workbench/days/{ISO_DATE}/skill-r2/assets/{code}/{kind}?"
                + urlencode({"revision": generation, "sha256": ref["sha256"]}))

    def _chart_refs(self, sample, code, generation):
        if sample is None:
            return None
        projection = sample["projection"]
        path = _path(projection["path"])
        return {
            "png_url": self._asset_url(code, "png", sample["PNG"], generation),
            "html_url": self._asset_url(code, "html", sample["html"], generation),
            "png_sha256": sample["PNG"]["sha256"], "html_sha256": sample["html"]["sha256"],
            "projection": {"projection_url": self._asset_url(code, "projection", projection, generation),
                           "sha256": projection["sha256"], "bytes": path.stat().st_size,
                           "encoding": "gzip" if path.suffix == ".gz" else "identity",
                           "row_count": sample["rows"], "formula_sha256": FORMULA_SHA},
            "rows": sample["rows"],
        }

    def _bound(self, revision=None):
        receipt, candidate_ref, generation, source_input = self._receipt()
        if revision is not None and revision != generation:
            raise ValueError("SKILL_R2_REVISION_CONFLICT")
        rows = self._candidates(receipt, candidate_ref, generation)
        chart = self._charts(receipt, candidate_ref, generation, source_input)
        reviews, review_status, review_sha = self._reviews(candidate_ref, chart)
        return receipt, candidate_ref, generation, source_input, rows, chart, reviews, review_status, review_sha

    def history_entry(self, observation):
        receipt, _, generation, _, _, _, _, _, _ = self._bound()
        return dict(source_date=ISO_DATE, observation_date=observation, revision=generation,
                    numeric_manifest=self.config["receipt"], ruleset_id=RULESET)

    def day(self, observation, workflow, revision=None):
        receipt, candidate_ref, generation, source_input, rows, chart, reviews, review_status, _ = self._bound(revision)
        output = []
        for row in rows:
            code = row["ts_code"]
            try:
                sample = self._sample(chart, code)
                chart_ref = self._chart_refs(sample, code, generation)
                entry = chart.get("samples", {}).get(code) if chart else None
                chart_state = ("READY" if sample else "ERROR_CHART_RENDER" if entry and entry.get("status") != "READY"
                               else "NOT_MATERIALIZED")
            except (ValueError, OSError, KeyError, TypeError):
                sample, chart_ref, chart_state = None, None, "ERROR_CHART_BINDING"
            output.append(dict(
                symbol=code, enriched_display_name=row.get("name"), name_source_date=row.get("name_source_date"),
                group_states={g: row["branches"][g]["seed_state"] for g in GROUPS},
                eligible_candidate=True, in_fifth=bool(row.get("risk_review_group_ids")),
                r2_pending=bool(row.get("pending_group_ids")), r2_risk=bool(row.get("risk_review_group_ids")),
                r2_record_status=row.get("record_status"), r2_chart_status=chart_state, r2_chart=chart_ref,
                r2_review=self._review_for(code, reviews, sample, review_status, generation),
                source_row=row, history_rates={},
            ))
        return dict(schema="RESEARCH_SYSTEM_DAY_V1", source_date=ISO_DATE, observation_date=observation,
                    generation=generation, input_sha256=source_input, revision=generation,
                    source_selector_sha256=receipt["source"]["selector_sha256_declared"],
                    numeric_manifest=self.config["receipt"], ruleset_id=RULESET, rows=output,
                    scope_count=len(output), original_processed_count=5538,
                    row_scope="D28_SKILL_R2_RAW_HIT_UNION_ONLY", formula_review="PENDING",
                    chart_review="UNKNOWN_NOT_REVIEWED", execution_status="DEFERRED_USER",
                    classification_catalogs={}, classification_identity_counts={},
                    classification_status="CANNOT_CONFIRM_NOT_BOUND",
                    statistics_status="CANNOT_CONFIRM_NO_SAME_RULESET_D2_D5", statistics_version=None,
                    workflow=[dict(label=x["label_zh"], status=x["execution_status"],
                                   recorded_at=x.get("recorded_at"), materials=x.get("materials", []))
                              for x in workflow.get("time_contract", {}).get("nodes", [])],
                    materials=[], reference_links=[], source_refs=dict(receipt=self.config["receipt"],
                    candidate_artifact=candidate_ref, chart_manifest=self.config.get("chart_manifest")), **FLAGS)

    def chart_views(self, revision=None):
        _, _, generation, source_input, rows, chart, _, _, _ = self._bound(revision)
        images, projections = [], []
        for row in rows:
            code = row["ts_code"]
            try:
                sample = self._sample(chart, code)
                refs = self._chart_refs(sample, code, generation)
            except (ValueError, OSError, KeyError, TypeError):
                continue
            if refs:
                images.append(dict(symbol=code, image_url=refs["png_url"], rows_declared=refs["rows"]))
                projections.append(dict(symbol=code, **refs["projection"]))
        common = dict(source_date=ISO_DATE, source_generation=generation, source_input_sha256=source_input,
                      chart_review="UNKNOWN_NOT_REVIEWED", full_stock_PASS=0, **FLAGS)
        return dict(charts=dict(rows=images, name_overlay=dict(rows=[dict(symbol=r["ts_code"], name=r.get("name"))
                                                                      for r in rows]), **common),
                    projections=dict(rows=projections, **common))

    def asset(self, code, kind, sha, revision=None):
        _, _, generation, _, rows, chart, _, _, _ = self._bound(revision)
        if code not in {r["ts_code"] for r in rows} or kind not in {"png", "html", "projection"}:
            raise KeyError("SKILL_R2_ASSET_NOT_FOUND")
        sample = self._sample(chart, code)
        if sample is None:
            raise KeyError("SKILL_R2_ASSET_NOT_MATERIALIZED")
        ref = sample[{"png": "PNG", "html": "html", "projection": "projection"}[kind]]
        if sha != ref["sha256"]:
            raise ValueError("SKILL_R2_ASSET_SHA_CONFLICT")
        return _bytes(ref), {"png": "image/png", "html": "text/html; charset=utf-8",
                             "projection": "application/octet-stream"}[kind]

    def versions(self, observation, revision=None):
        _, _, generation, source_input, _, _, _, status, review_sha = self._bound(revision)
        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        modules = dict(list=digest([self.config["receipt"], self.config.get("chart_manifest"), status, review_sha]),
                       statistics=digest("NO_SAME_RULESET_D2_D5"), classification=digest("NOT_BOUND"),
                       observations=digest("NOT_BOUND"), context=digest("NOT_BOUND"), workflow=digest("BOUND_HOST"))
        return dict(schema="V4_WORKBENCH_VERSIONS_V1", source_date=ISO_DATE, observation_date=observation,
                    generation=generation, input_sha256=source_input, numeric_manifest=self.config["receipt"],
                    modules=modules, event_id=digest(modules), **FLAGS)
