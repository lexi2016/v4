"""Native owner bytes, read-only. Bindings name an exact manifest + SHA/date.

No legacy research code executes here. Old announcement scans are directory/body
inputs only; old lane conclusions are never promoted to new research results.
"""
from __future__ import annotations
import base64
import csv
import io
import json
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from contracts.trading_calendar import load_market_calendar, previous_session, CALENDAR_PATH
from ..contracts import Coverage, EvidenceRef, Lane, Verification
from ..engines.common import US_FACTOR_RULES_VERSION
from .validation import batch, before, owner_digest, raw_sha, symbol, time_value


class NativeAdapters:
    def __init__(self, config):
        self.config = config
        self.calendar = load_market_calendar()
        self._membership_versions = {}

    def prepare_context(self, context):
        context = context.model_copy(deep=True)
        try:
            context.source_sessions.setdefault("hk_price", previous_session(self.calendar, context.target_date, market="hk_securities"))
        except ValueError:
            context.source_sessions.setdefault("hk_price",None)
        if "us" not in context.source_sessions:
            try: context.source_sessions["us"] = self._us_session(context.cutoff)
            except (ValueError,OSError): context.source_sessions["us"] = None
        if self.config.dynamic_source_bindings and "owner_bindings" not in context.scope_refs:
            from .source_bindings import resolve_bindings
            pins, gaps = resolve_bindings(self.config, context)
            context.scope_refs["owner_bindings"] = pins
            context.scope_refs["owner_binding_gaps"] = gaps
        if self.config.capture_root:
            from .source_bindings import announcements
            try:
                context.scope_refs.setdefault("owner_bindings",{})["announcements"]=announcements(self.config,context)
                context.scope_refs.setdefault("owner_binding_gaps",{}).pop("announcements",None)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                context.scope_refs.setdefault("owner_bindings",{}).pop("announcements",None)
                context.scope_refs.setdefault("owner_binding_gaps",{})["announcements"]=str(exc)
        for lane, name in (("ANNOUNCEMENT","announcements"),("US_MAPPING","us_mapping")):
            pin = context.scope_refs.get("owner_bindings",{}).get(name) or self.config.source_bindings.get(name, {}).get(context.target_date, {})
            if lane == "ANNOUNCEMENT":
                context.scope_refs[lane] = dict(owner="v4.manager_workbench.capture_announcements" if self.config.capture_root else "ManagerResearchJobService.refresh_announcements",
                    scope_state="CANNOT_CONFIRM", sha256=owner_digest(pin), universe_ref="announcement-observed:"+context.target_date)
            else:
                context.scope_refs[lane] = dict(configured_symbols=pin.get("configured_symbols"),
                    source_session=context.source_sessions["us"], verification="VERIFIED" if pin else "CANNOT_CONFIRM",
                    calendar_verified=True, sha256=owner_digest(pin), universe_ref="us-fixed33:"+context.target_date,
                full_overlay_projection=pin.get("full_overlay_projection",[]),
                full_overlay_summary=pin.get("full_overlay_summary",{"state":"CANNOT_CONFIRM","gap":"US_MAPPING_FULL_OVERLAY_NOT_BOUND"}))
        close_pin = context.scope_refs.get("owner_bindings",{}).get("close") or self.config.source_bindings.get("close", {}).get(context.target_date,{})
        context.scope_refs["review_universe"] = close_pin.get("evaluation_scope_ref")
        return context

    def _us_session(self, cutoff):
        # Optional native dependency remains explicitly pinned until integrated.
        try:
            from contracts.us_equity_calendar import latest_completed_session
        except ModuleNotFoundError:
            import importlib.util
            import sys
            path = self.config.us_calendar_path
            if not path or raw_sha(path.read_bytes()) != self.config.us_calendar_sha256:
                raise ValueError("US_CALENDAR_DEPENDENCY_NOT_BOUND")
            spec = importlib.util.spec_from_file_location("mwb_pinned_us_calendar",path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            latest_completed_session = module.latest_completed_session
        return latest_completed_session(time_value(cutoff)).session_date

    def _binding(self, name, date, context=None):
        bindings = self.config.source_bindings.get(name, {})
        value = context.scope_refs.get("owner_bindings",{}).get(name) if context else None
        value = value or bindings.get(date)
        if value:
            for source in value.get("checked_files",[]):
                if raw_sha(SafeRoot(Path(source.get("source_local_path") or source["root"])).read_bytes(source["relative"])) != source["sha256"]:
                    raise ValueError("OWNER_BOUND_BYTES_CHANGED")
        if not isinstance(value, dict):
            raise ValueError(name.upper() + "_EXACT_DATE_BINDING_MISSING")
        return value

    @staticmethod
    def _json(root, relative, sha=None):
        raw = SafeRoot(root).read_bytes(relative)
        if sha is not None and raw_sha(raw) != sha:
            raise ValueError("SOURCE_BYTES_SHA_MISMATCH")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("SOURCE_OBJECT_REQUIRED")
        return value, raw_sha(raw)

    @staticmethod
    def _stage_json(root, relative, expected, schema):
        # This owner hashes canonical JSON, while other sources pin raw bytes.
        # Keep the distinction local to its two explicitly versioned contracts.
        raw = SafeRoot(root).read_bytes(relative)
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get("schema_version") != schema or value.get("owner") != "stage_center"
                or owner_digest(value) != expected):
            raise ValueError("STAGE_OWNER_SCHEMA_OR_SHA_MISMATCH")
        return value, raw_sha(raw)

    def _manifest(self, name, date, root, context=None):
        pin = self._binding(name, date, context)
        manifest, sha = self._json(root, pin["manifest_relative"], pin["manifest_sha256"])
        if (manifest.get("trade_date", manifest.get("target_date", manifest.get("source_date"))) != date
                or manifest.get("production_allowed") is not False or manifest.get("orders_sent", False) is not False):
            raise ValueError("SOURCE_MANIFEST_DATE_OR_SAFETY_INVALID")
        return pin, manifest, sha

    @staticmethod
    def _ref(owner, role, date, sha, relative, available=None, gaps=None, manifest=None, receipt=None, url=None):
        gaps = list(gaps or [])
        if available is None:
            gaps.append("SOURCE_AVAILABLE_AT_UNKNOWN")
        return EvidenceRef(evidence_id=f"{owner}:{role}:{sha}", owner=owner, role=role,
                           source_date=date, source_session=date, sha256=sha, artifact_ref=relative,
                           manifest_ref=manifest, receipt_ref=receipt, available_at=available,
                           source_url=url, verification=Verification.CANNOT_CONFIRM if gaps else Verification.VERIFIED,
                           gaps=gaps)

    def membership(self, context):
        """Monthly Connect membership is separate from security-master membership."""
        try:
            pin = self._binding("membership", context.target_date, context)
            value, sha = self._json(Path(pin.get("source_local_path") or pin.get("root") or self.config.shared_root), pin["artifact_relative"], pin["artifact_sha256"])
            value = pin.get("projection",value)
            if value.get("schema_version") == "v4.manager_research.hk_connect_monthly_eligibility.v1":
                source = value.get("source",{})
                authority_root = pin.get("authority_root")
                if not authority_root or value.get("status") != "VERIFIED" or value.get("month") != context.target_date[:6]:
                    raise ValueError("MONTHLY_CONNECT_AUTHORITY_NOT_BOUND")
                for key, expected in value.get("authority_file_sha256s",{}).items():
                    if raw_sha(SafeRoot(authority_root).read_bytes(source[key])) != expected:
                        raise ValueError("MONTHLY_CONNECT_AUTHORITY_SHA_MISMATCH")
                if not value.get("authority_file_sha256s") or source.get("role") != "HK_CONNECT_FULL_MARKET_AUTHORITY":
                    raise ValueError("MONTHLY_CONNECT_AUTHORITY_ROLE_INVALID")
                value = {**value,"market":source.get("market"),"owner":source.get("owner"),
                    "version":value["identity_sha256"],"effective_from":value["month"]+"01",
                    "effective_to":value["month"]+"31","available_at":source.get("available_at"),
                    "source_url":"https://www.hkex.com.hk/Mutual-Market/Stock-Connect"}
            if (value.get("market") != "HK_CONNECT" or not value.get("version")
                    or not (value.get("effective_from", "") <= context.target_date <= value.get("effective_to", ""))
                    or not before(value.get("available_at"), context.cutoff)
                    or value.get("owner") != pin.get("owner") or not value.get("source_url")):
                raise ValueError("MONTHLY_CONNECT_MEMBERSHIP_INVALID")
            codes = [symbol(v) for v in value.get("codes", [])]
            if not codes or None in codes or len(codes) != len(set(codes)):
                raise ValueError("MONTHLY_CONNECT_MEMBERSHIP_CODES_INVALID")
            ref = self._ref(value["owner"], "MONTHLY_CONNECT_MEMBERSHIP", context.target_date,
                            sha, pin["artifact_relative"], value["available_at"], url=value["source_url"])
            self._membership_versions[ref.evidence_id] = value
            return set(codes), ref, []
        except (OSError, ValueError, KeyError, TypeError):
            return set(), None, ["MONTHLY_CONNECT_MEMBERSHIP_UNVERIFIED"]

    def _member(self, row, codes, ref):
        row["membership_status"] = "VERIFIED" if ref and row.get("symbol") in codes else (
            "NOT_ELIGIBLE" if ref else "CANNOT_CONFIRM")
        if ref:
            row.setdefault("evidence_ids", []).append(ref.evidence_id)
            version = self._membership_versions[ref.evidence_id]
            row["membership"] = dict(verification="VERIFIED", owner=ref.owner, sha256=ref.sha256,
                eligible=row.get("symbol") in codes, available_at=ref.available_at,
                effective_from=version["effective_from"], effective_through=version["effective_to"], version=version["version"])
        return row

    def load(self, lane, context):
        value = {Lane.ANNOUNCEMENT: self.announcements, Lane.US_MAPPING: self.us_mapping,
                Lane.OVERSOLD: self.oversold, Lane.STAGE_REFERENCE: self.stage,
                Lane.CLOSE_REFERENCE: self.close}[lane](context)
        return self._engine_shape(value)

    def _engine_shape(self, value):
        """Map native facts into A's explicit evidence contract, preserving unknowns."""
        context, lane = value.context, value.lane
        records = []
        by_id = {ref.evidence_id: ref for ref in value.evidence_refs}
        default_primary = next((ref for ref in value.evidence_refs if ref.role not in
            {"MONTHLY_CONNECT_MEMBERSHIP", "HK_SECURITY_MASTER"}), None)
        for item in value.records:
            primary = default_primary
            if lane == Lane.ANNOUNCEMENT or lane == Lane.OVERSOLD and item.get("comparison_basis"):
                candidates = [by_id[eid] for eid in item.get("evidence_ids", []) if eid in by_id
                    and by_id[eid].role in {"ANNOUNCEMENT_BODY", "ANNOUNCEMENT_CAPTURED_BODY", "FUTU_DAILY_HISTORY_RAW", "TDXPY_DAILY_HISTORY_RAW"}
                    and by_id[eid].sha256 == item.get("source_sha256")]
                # Each article owns its evidence identity. Missing or ambiguous
                # source matches stay unknown instead of borrowing a batch owner.
                identities = {(ref.owner, ref.sha256) for ref in candidates}
                primary = candidates[0] if len(identities) == 1 else None
            row = dict(item, market="HK_CONNECT", target_date=context.target_date,
                       owner=primary.owner if primary else None,
                       source_sha256=item.get("source_sha256") or (primary.sha256 if primary else None),
                       available_at=item.get("available_at") or (primary.available_at if primary else None))
            if lane == Lane.ANNOUNCEMENT:
                row.update(article_id=f"{item['event_id']}:{item['symbol']}", observed_at=item.get("observed_at",item.get("available_at")),
                           is_pdf=item.get("source_kind") != "EASTMONEY_MIRROR", source_page_count=len(item.get("pages",[])),
                           source_pages_complete=item.get("body_complete") is True)
                pages = item.get("pages", [])
                row["segments"] = [{"index":i,"count":len(pages),"page_number":p["page"],
                                    "text":p["text"]+(item.get("join_separator","\n") if i+1<len(pages) else "")} for i,p in enumerate(pages)]
            elif lane == Lane.OVERSOLD:
                previous = item["price_session"]
                sixty, cursor = [], previous
                for _ in range(60):
                    cursor = previous_session(self.calendar,cursor,market="hk_securities")
                    sixty.append(cursor)
                sixty.reverse()
                by_date = {b["date"]:b for b in item["bars"]}
                duplicate = len(by_date) != len(item["bars"])
                prev = by_date.get(previous,{})
                def bar(b):
                    def number(v):
                        import math
                        try:return str(v) if v is not None and math.isfinite(float(v)) else None
                        except (ValueError,TypeError):return None
                    return dict(session=b.get("date"),close=number(b.get("close")),high=number(b.get("high")),
                                volume=number(b.get("volume")),price_unit=b.get("currency"),volume_unit=b.get("volume_unit"),
                                adjustment=b.get("price_basis"),available_at=b.get("source_available_at"),
                                source_metadata=b.get("source_metadata",{}),comparison_basis_sha256=b.get("comparison_basis_sha256"))
                row.update(price_unit=prev.get("currency"),volume_unit=prev.get("volume_unit"),adjustment=prev.get("price_basis"),
                    previous_bar=bar(prev),high_history60=[bar(by_date[d]) for d in sixty if d in by_date],
                    volume_history5=[bar(by_date[d]) for d in sixty[-5:] if d in by_date],
                    calendar=dict(verification="INVALID" if duplicate else "VERIFIED",sha256=raw_sha(CALENDAR_PATH.read_bytes()),
                        target_date=context.target_date,previous_session=previous,
                        expected_high_sessions60=sixty,expected_volume_sessions5=sixty[-5:]))
                row["previous_bar"]["suspended"]=prev.get("suspended",False)
                row["observed_history_total"] = len(item["bars"])
                row.pop("bars",None)
                if any(v in {"NOT_PROVEN", "UNKNOWN", "UNVERIFIED"} for v in (row["adjustment"], row["volume_unit"])):
                    row["adjustment"] = None
            records.append(row)
        universe_ref = value.universe_ref
        coverage = value.coverage
        if lane == Lane.ANNOUNCEMENT:
            universe_ref = "announcement-observed:" + context.target_date
            # The observed catalog is complete as a set even if full-market coverage is unknown.
            context.scope_refs["ANNOUNCEMENT"] = dict(owner="v4.manager_workbench.capture_announcements" if self.config.capture_root else "ManagerResearchJobService.refresh_announcements",
                scope_state="VERIFIED",sha256=value.input_sha256,universe_ref=universe_ref,
                article_ids=[r["article_id"] for r in records],coverage_gaps=value.gaps)
            coverage = Coverage(scope_count=len(records),observed_count=len(records),gaps=value.gaps)
        elif lane == Lane.US_MAPPING:
            universe_ref = "us-fixed33:"+context.target_date
        return batch(context,lane,records,value.evidence_refs,value.scope_description,coverage,value.gaps,universe_ref)

    def announcements(self, context):
        pin = context.scope_refs.get("owner_bindings",{}).get("announcements") if self.config.capture_root else self._binding("announcements", context.target_date, context)
        if not isinstance(pin,dict):raise ValueError("NEW_CAPTURE_OWNER_EXACT_DATE_BINDING_MISSING")
        if "capture_binding_relative" in pin:
            return self._announcement_capture(context,pin)
        if "corpus_relative" in pin:
            return self._announcement_corpus(context,pin)
        codes, member_ref, gaps = self.membership(context)
        refs = [member_ref] if member_ref else []
        documents, rows, windows, observed_ids = {}, {}, [], set()
        scope_count = None
        material_io = SafeRoot(self.config.manager_root / "materials")
        # The explicit list is a complete observed owner set, not a few issuer queries.
        for source in pin.get("scans", []):
            scan, sha = self._json(self.config.manager_root, source["relative"], source["sha256"])
            if (scan.get("target_trade_date") != context.target_date
                    or scan.get("owner") != "ManagerResearchJobService.refresh_announcements"
                    or scan.get("sha256") != owner_digest({k:v for k,v in scan.items() if k != "sha256"})):
                gaps.append("ANNOUNCEMENT_SCAN_IDENTITY_INVALID")
                continue
            source_ref = self._ref(scan["owner"], "OBSERVED_ANNOUNCEMENT_SCAN", context.target_date,
                                  sha, source["relative"], scan.get("generated_at"))
            refs.append(source_ref)
            directory = scan.get("market_directory", {})
            if directory:
                windows.append({k:directory.get(k) for k in ("from_date", "to_date", "window_mode", "publication_window_start", "query_cutoff", "source_scope")})
                scope_count = max(scope_count or 0, directory.get("record_count") or 0) or None
                if directory.get("directory_exhaustion") not in {"EXHAUSTED", "VERIFIED_EXHAUSTED", "SERVER_PAGINATION_EXHAUSTED"}:
                    gaps.append("ANNOUNCEMENT_DIRECTORY_COVERAGE_UNVERIFIED")
                for row in directory.get("rows", []):
                    key = str(row.get("news_id"))
                    observed_ids.add(key)
                    rows[key] = {**row, "source_ref_id": source_ref.evidence_id}
            else:
                gaps.append("ISSUER_QUERY_IS_NOT_FULL_MARKET_DIRECTORY")
            for doc in [*scan.get("market_documents", []), *scan.get("documents", [])]:
                key = str(doc.get("news_id") or doc.get("row", {}).get("news_id") or doc.get("art_code"))
                documents[key] = doc
                rows.setdefault(key, {**doc.get("row", {}), "source_ref_id": source_ref.evidence_id})
        records = []
        for event_id, raw in rows.items():
            doc = documents.get(event_id, {})
            stock_codes = doc.get("codes") or raw.get("stock_codes") or [doc.get("code")]
            body_ref = doc.get("body_ref", {})
            pages, body_gaps, body_sha = [], [], body_ref.get("body_sha256")
            try:
                blob_sha = body_ref["blob_sha256"]
                envelope = material_io.read_bytes(f"blobs/{blob_sha}", max_bytes=48*1024*1024)
                if raw_sha(envelope) != blob_sha:
                    raise ValueError("ANNOUNCEMENT_BLOB_SHA_MISMATCH")
                wrapper = json.loads(envelope)
                body = base64.b64decode(wrapper["body_b64"], validate=True)
                if raw_sha(body) != body_sha or wrapper.get("status_code") != body_ref.get("http_status"):
                    raise ValueError("ANNOUNCEMENT_BODY_SHA_MISMATCH")
                if body.startswith(b"%PDF"):
                    import pymupdf
                    with pymupdf.open(stream=body, filetype="pdf") as pdf:
                        pages = [{"page":i+1, "text":p.get_text()} for i,p in enumerate(pdf)]
                    if not pages or any(not p["text"].strip() for p in pages):
                        body_gaps.append("PDF_TEXT_EXTRACTION_INCOMPLETE")
                else:
                    body_gaps.append("BODY_FORMAT_UNSUPPORTED")
            except (OSError, ValueError, KeyError, ImportError, RuntimeError):
                body_gaps.append("ANNOUNCEMENT_BODY_UNAVAILABLE_OR_INVALID")
            source_time = body_ref.get("retrieved_at")
            if not before(raw.get("published_at"), context.cutoff) or not before(source_time, context.cutoff):
                body_gaps.append("ANNOUNCEMENT_AFTER_CUTOFF_OR_TIME_UNKNOWN")
            text = "\n".join(p["text"] for p in pages)
            for code in stock_codes:
                sym = symbol(code)
                if not sym:
                    continue
                record = dict(symbol=sym, name=doc.get("code_names", {}).get(sym, doc.get("name")),
                              event_id=event_id, title=raw.get("title"), published_at=raw.get("published_at"),
                              source_url=raw.get("url"), source_sha256=body_sha,
                              body_sha256=raw_sha(text.encode()) if text else None,
                              source_body_sha256=body_sha, body=text, pages=pages,
                              available_at=source_time, body_complete=bool(pages) and not body_gaps,
                              evidence_ids=[raw["source_ref_id"]], gaps=body_gaps,
                              source_kind="OFFICIAL_HKEX" if "hkexnews.hk" in str(raw.get("url")) else "MIRROR")
                if body_sha:
                    body_evidence = self._ref("HKEX" if record["source_kind"] == "OFFICIAL_HKEX" else "MIRROR",
                        "ANNOUNCEMENT_BODY", raw.get("publication_date"), body_sha,
                        f"body:{body_sha}", source_time, body_gaps, url=record["source_url"])
                    refs.append(body_evidence)
                    record["evidence_ids"].append(body_evidence.evidence_id)
                records.append(self._member(record, codes, member_ref))
        if not pin.get("scans"):
            gaps.append("ANNOUNCEMENT_OBSERVED_SET_MISSING")
        return batch(context, Lane.ANNOUNCEMENT, records, refs,
                     "Complete pinned observed announcement directories; official and mirror separated",
                     Coverage(scope_count=scope_count, observed_count=len(observed_ids), gaps=list(set(gaps))),
                     list(set(gaps)), universe_ref=member_ref.evidence_id if member_ref else None)

    def _announcement_capture(self,context,pin):
        from .capture_binding import read_binding
        _,product=read_binding(self.config,pin,context)
        codes,member_ref,gaps=self.membership(context)
        refs=[member_ref] if member_ref else []
        # After-submit material may be consumed at this honest later cutoff;
        # original capture cutoff and gaps remain in the immutable owner record.
        gaps += [g for g in product["gaps"] if g not in {
            "CAPTURE_AVAILABLE_AFTER_RESEARCH_CUTOFF","ANNOUNCEMENT_OUTSIDE_PUBLICATION_WINDOW"}]
        records=[]
        for article in product["rows"]:
            if article["window_consumption_status"]=="EXCLUDED_OUTSIDE_WINDOW":continue
            body_gaps=list(article["gaps"])
            evidence=self._ref("EASTMONEY_MIRROR","ANNOUNCEMENT_BODY",article["publication_date"].replace("-",""),
                article["source_sha256"],article["body_artifact_ref"],article["available_at"],body_gaps,
                manifest=pin["capture_binding_relative"],url=(article["pages"][0]["source_ref"]["source_url"] if article["pages"] else article["listing_source_ref"]["source_url"]))
            refs.append(evidence)
            for issuer in article["source_issuer_codes"]:
                sym=symbol(issuer["code"])
                if not sym:continue
                records.append(self._member(dict(symbol=sym,name=issuer.get("name"),event_id="EASTMONEY:"+article["art_code"],
                    source_kind="EASTMONEY_MIRROR",title=article["title"],body=article["body_text"] or "",
                    body_sha256=article["body_text_sha256"],source_sha256=article["source_sha256"],
                    available_at=article["available_at"],observed_at=article["available_at"],
                    published_at=None,publication_date=article["publication_date"],publication_time_status="CANNOT_CONFIRM",
                    original_point_in_time_availability="CANNOT_CONFIRM",source_url=evidence.source_url,
                    body_complete=article["body_complete"],pages=[dict(page=p["page_number"],text=p["text"]) for p in article["pages"]],
                    join_separator="\n\n",evidence_ids=[evidence.evidence_id],gaps=body_gaps),codes,member_ref))
        context.scope_refs["capture_original_window"]=product["window"]
        return batch(context,Lane.ANNOUNCEMENT,records,refs,"Exact-window new owner Eastmoney mirror source; full directory retained in capture audit",
            Coverage(scope_count=product["scope_count"],observed_count=product["observed_count"],gaps=gaps),gaps)

    def _announcement_corpus(self, context, pin):
        """Existing captured official/mirror bodies, with independent source variants."""
        corpus, csha = self._json(self.config.manager_root,pin["corpus_relative"],pin["corpus_sha256"])
        manifest, msha = self._json(self.config.manager_root,pin["manifest_relative"],pin["manifest_sha256"])
        receipt, rsha = self._json(self.config.manager_root,pin["receipt_relative"],pin["receipt_sha256"])
        if (corpus.get("target_trade_date") != context.target_date or manifest.get("target_trade_date") != context.target_date
                or receipt.get("target_trade_date") != context.target_date or receipt.get("body_corpus_file_sha256") != csha
                or receipt.get("body_corpus_manifest_file_sha256") != msha or corpus.get("source_manifest_sha256") != msha
                or receipt.get("RESEARCH_ONLY") is not True or receipt.get("production_allowed") is not False
                or corpus.get("input_identity_sha256") != manifest.get("input_identity_sha256")):
            raise ValueError("ANNOUNCEMENT_CORPUS_MANIFEST_RECEIPT_INVALID")
        codes, membership_ref, gaps = self.membership(context)
        refs = [membership_ref] if membership_ref else []
        originals = [("EASTMONEY_MIRROR",r) for r in corpus.get("rows",[])] + [
            ("HKEX_OFFICIAL",r) for r in corpus.get("source_variants",[])]
        if len(corpus.get("rows",[])) != corpus.get("article_count") or len(corpus.get("source_variants",[])) != corpus.get("source_variant_count"):
            raise ValueError("ANNOUNCEMENT_CORPUS_SOURCE_COUNTS_MISMATCH")
        if receipt.get("hkex_body_coverage_status") != "COMPLETE":
            gaps.append("ANNOUNCEMENT_FULL_MARKET_BODY_COVERAGE_PARTIAL")
        gaps.append("CROSS_SOURCE_EVENT_DEDUP_UNASSESSED") if corpus.get("hkex_cross_source_link_status") == "NOT_ASSESSED" else None
        records, seen = [], set()
        for source_kind, item in originals:
            original_id = item.get("event_id") or item.get("source_variant_id") or item.get("art_code")
            if not original_id or (source_kind,original_id) in seen:
                raise ValueError("ANNOUNCEMENT_CORPUS_DUPLICATE_ID")
            seen.add((source_kind,original_id))
            body = item.get("body_text") or ""
            body_sha = item.get("body_text_sha256")
            body_gaps=[]
            if raw_sha(body.encode()) != body_sha:
                body_gaps.append("ANNOUNCEMENT_BODY_TEXT_SHA_MISMATCH")
            pages = item.get("pages") or []
            source_times = [time_value(p.get("retrieved_at")) for p in pages if time_value(p.get("retrieved_at"))]
            available = max(source_times).isoformat() if source_times else item.get("available_at")
            source_ref = item.get("body_source_ref") or item.get("listing_source_ref") or {}
            source_sha = source_ref.get("body_sha256") or item.get("pdf_sha256") or item.get("listing_raw_body_sha256")
            # Text is already extracted by the original owner. Its full extraction
            # must be traced to complete page receipts; no prefix is treated as full.
            if not pages or any(p.get("page_total") != len(pages) or p.get("page_index") != i+1
                    or raw_sha(str(p.get("text","")).encode()) != p.get("text_sha256") for i,p in enumerate(pages)):
                body_gaps.append("ANNOUNCEMENT_PAGE_RECEIPTS_INCOMPLETE")
            if not before(available,context.cutoff):
                body_gaps.append("ANNOUNCEMENT_AFTER_CUTOFF_OR_TIME_UNKNOWN")
            url = item.get("source_url") or item.get("attachment_url") or source_ref.get("final_url")
            evidence = self._ref(source_kind,"ANNOUNCEMENT_CAPTURED_BODY",context.target_date,source_sha,
                pin["corpus_relative"]+":"+original_id,available,body_gaps,
                manifest=pin["manifest_relative"],receipt=pin["receipt_relative"],url=url)
            refs.append(evidence)
            for code in item.get("matched_connect_codes",item.get("issuer_codes",item.get("source_issuer_codes",[]))):
                sym=symbol(code)
                if not sym: continue
                records.append(self._member(dict(symbol=sym,name=None,event_id=source_kind+":"+original_id,original_event_id=original_id,
                    source_kind=source_kind,title=item.get("title"),body=body,body_sha256=body_sha,
                    source_sha256=source_sha,source_body_sha256=source_sha,
                    published_at=item.get("published_at",item.get("publication_date",corpus.get("publication_date"))),
                    available_at=available,source_url=url,original_point_in_time_availability=item.get("original_point_in_time_availability","CANNOT_CONFIRM"),
                    body_complete=item.get("body_status") in {"COMPLETE_CONTENT_API_BODY","COMPLETE_HKEX_OFFICIAL_PDF_BODY"} and not body_gaps,
                    # Body text uses owner's exact concatenation; retain page receipts
                    # independently while preserving the complete byte string.
                    pages=[{"page":i+1,"text":p["text"]} for i,p in enumerate(pages)],join_separator="\n\n",source_page_receipts=pages,
                    evidence_ids=[evidence.evidence_id],gaps=body_gaps),codes,membership_ref))
        return batch(context,Lane.ANNOUNCEMENT,records,refs,
            "Complete observed pinned multi-source corpus; source rows and official variants remain distinct",
            Coverage(scope_count=len(records),observed_count=len(records),gaps=gaps),gaps)

    def _futu_history(self, context, pin, previous):
        """Validate one already-captured owner response; never requests a quote."""
        root=Path(pin['source_local_path']);raw=SafeRoot(root).read_bytes(pin['raw_relative'])
        if raw_sha(raw)!=pin['raw_sha256']:raise ValueError('FUTU_HISTORY_RAW_SHA_MISMATCH')
        receipt,rsha=self._json(root,pin['receipt_relative'],pin['receipt_sha256'])
        request=receipt.get('request',{});sym=symbol(receipt.get('code'))
        if (receipt.get('source')!='FUTU' or sym!=pin.get('symbol') or receipt.get('return_code')!=0
                or receipt.get('has_next_page') is not False or receipt.get('raw_sha256')!=raw_sha(raw)
                or request.get('ktype')!='K_DAY' or request.get('autype')!='NONE'
                or not before(receipt.get('started_at'),context.cutoff) or not before(receipt.get('finished_at'),context.cutoff)
                or time_value(receipt['started_at'])>time_value(receipt['finished_at'])):
            raise ValueError('FUTU_HISTORY_REQUEST_RECEIPT_INVALID')
        values=json.loads(raw)
        sessions=[previous];cursor=previous
        for _ in range(60):
            cursor=previous_session(self.calendar,cursor,market='hk_securities');sessions.append(cursor)
        sessions.sort()
        if (not isinstance(values,list) or len(values)!=61 or receipt.get('row_count')!=61
                or receipt.get('missing_sessions')!=[] or receipt.get('extra_sessions')!=[]
                or request.get('start')!=sessions[0][:4]+'-'+sessions[0][4:6]+'-'+sessions[0][6:]
                or request.get('end')!=previous[:4]+'-'+previous[4:6]+'-'+previous[6:]):
            raise ValueError('FUTU_HISTORY_EXACT_61_SESSION_INVALID')
        dates=[]
        for value in values:
            text=value.get('time_key')
            if not isinstance(text,str) or len(text)!=19 or text[10:]!=' 00:00:00' or value.get('code')!=sym:
                raise ValueError('FUTU_HISTORY_SECURITY_OR_DAY_INVALID')
            dates.append(text[:10].replace('-',''))
        if dates!=sessions:raise ValueError('FUTU_HISTORY_SESSION_DUPLICATE_OR_GAP')
        original_request=dict(source='FUTU',code=sym,request=request)
        basis=dict(source='FUTU',security_symbol=sym,request=original_request,
            request_sha256=owner_digest(original_request),raw_sha256=raw_sha(raw),receipt_sha256=rsha,
            adjustment='RAW',price_comparison='SAME_SOURCE_SECURITY_REQUEST',volume_comparison='SAME_SOURCE_SECURITY_REQUEST',
            available_at=receipt['finished_at'])
        bsha=owner_digest(basis)
        ref=self._ref('FUTU','FUTU_DAILY_HISTORY_RAW',previous,raw_sha(raw),pin['raw_relative'],receipt['finished_at'],receipt=pin['receipt_relative'])
        bars=[dict(date=d,close=v.get('close'),high=v.get('high'),volume=v.get('volume'),currency=None,volume_unit=None,
            price_basis='RAW',source_available_at=receipt['finished_at'],suspended=False,comparison_basis_sha256=bsha,
            source_metadata=dict(source='FUTU',code=v['code'],time_key=v['time_key'],request=original_request,
                raw_sha256=raw_sha(raw),receipt_sha256=rsha)) for d,v in zip(dates,values)]
        return sym,bars,basis,ref

    def _tdxpy_history(self, context, pin, previous, panel_sha, master_sha, master_codes, panel_manifest_sha, master_manifest_sha):
        from upstreams.v3_shared_data.shared_data.hk_daily_supplement import read_tdxpy_window_supplement
        manifest,records=read_tdxpy_window_supplement(pin,target_date=previous,cutoff=context.cutoff,
            expected_panel_sha=panel_sha,expected_master_sha=master_sha,expected_codes=master_codes,
            expected_panel_manifest_sha=panel_manifest_sha,expected_master_manifest_sha=master_manifest_sha)
        output={};refs=[];gaps=['TDXPY_GLOBAL_CATALOGUE_PARTIAL'] if manifest['catalogue_coverage_status']=='PARTIAL' else []
        for value in records:
            sym=value['code']
            if value['status']!='READY':
                gaps.append('TDXPY_EXACT_HISTORY_UNAVAILABLE:'+sym);continue
            request=value['request']
            original_request=dict(source='TDXPY_0_2_7',code=sym,request=request)
            basis=dict(source='TDXPY_0_2_7',security_symbol=sym,request=original_request,
                request_sha256=owner_digest(original_request),raw_sha256=pin['raw_sha256'],receipt_sha256=pin['manifest_sha256'],
                response_sha256=value['response_sha256'],catalogue_sha256=value['catalogue_sha256'],
                adjustment='TDX_PROTOCOL_PARAM1_FIXED',price_comparison='SAME_SOURCE_SECURITY_REQUEST',
                volume_comparison='SAME_SOURCE_SECURITY_REQUEST',available_at=manifest['available_at'])
            bsha=owner_digest(basis)
            ref=self._ref('TDXPY_0_2_7','TDXPY_DAILY_HISTORY_RAW',previous,pin['raw_sha256'],pin['raw_relative'],
                manifest['available_at'],manifest=pin['manifest_relative'])
            bars=[dict(date=b['trade_date'],close=b['close'],high=b['high'],volume=b['trade'],currency=None,volume_unit=None,
                price_basis='TDX_PROTOCOL_PARAM1_FIXED',source_available_at=manifest['available_at'],suspended=False,
                comparison_basis_sha256=bsha,source_metadata=dict(source='TDXPY_0_2_7',code=sym,request=original_request,
                    raw_sha256=pin['raw_sha256'],receipt_sha256=pin['manifest_sha256'],response_sha256=value['response_sha256'],
                    catalogue_sha256=value['catalogue_sha256'],native_fields=b['native_fields'])) for b in value['bars']]
            output[sym]=(bars,basis,ref);refs.append(ref)
        return output,refs,gaps

    def oversold(self, context, *, panel_only=False):
        date = context.source_sessions.get("hk_price") or previous_session(self.calendar, context.target_date, market="hk_securities")
        pin = self._binding("hk_panel", date, context)
        root = self.config.shared_root
        manifest, msha = self._json(root, pin["manifest_relative"], pin["manifest_sha256"])
        actual_max = manifest.get("panel_max_date")
        projected = (context.phase.value == "RETROSPECTIVE" and isinstance(actual_max,str)
                     and date <= actual_max <= context.target_date)
        available = manifest.get("manifest_prepared_at",manifest.get("prepared_at",pin.get("available_at")))
        if (actual_max != date and not projected or manifest.get("research_only") is not True
                or manifest.get("production_allowed") is not False):
            raise ValueError("HK_PANEL_DATE_OR_SAFETY_INVALID")
        if not before(available,context.cutoff) or pin.get("available_at") != available:
            raise ValueError("HK_PANEL_AVAILABLE_TIME_INVALID")
        artifact_relative = pin.get("panel_relative", "assets/hk_0_2/" + manifest["panel_relative"])
        raw = SafeRoot(root).read_bytes(artifact_relative, max_bytes=512*1024*1024)
        if raw_sha(raw) != manifest["panel_sha256"]:
            raise ValueError("HK_PANEL_BYTES_SHA_MISMATCH")
        import pandas as pd
        frame = pd.read_parquet(io.BytesIO(raw))
        date_col = "trade_date_compact" if "trade_date_compact" in frame else "trade_date"
        code_col = "code_norm" if "code_norm" in frame else "symbol"
        frame[date_col] = frame[date_col].astype(str).str.replace("-", "", regex=False).str[:8]
        frame = frame[frame[date_col] <= date]
        from upstreams.v3_shared_data.shared_data.hk_history_resolution import policy_for_shared
        resolution = policy_for_shared(root)
        resolution.check_panel(manifest["panel_sha256"])
        frame = resolution.guard_frame(frame, required_fields=('close','high'), code_column=code_col,
            date_column=date_col, end=date, lookback=61, consumer='HK_OVERSOLD_PRICE61_V1')
        resolution_proofs = [resolution.encode_proof(frame.attrs['history_resolution_proof'])]
        resolution_holds = dict(frame.attrs['history_resolution_holds'])
        frame = resolution.guard_frame(frame, required_fields=('trade',), code_column=code_col,
            date_column=date_col, end=date, lookback=6, consumer='HK_OVERSOLD_VOLUME6_V1')
        resolution_proofs.append(resolution.encode_proof(frame.attrs['history_resolution_proof']))
        resolution_holds.update(frame.attrs['history_resolution_holds'])
        refs = [self._ref("v3_shared_data", "HK_DAILY_PANEL", actual_max, manifest["panel_sha256"],
                          artifact_relative, available, manifest=pin["manifest_relative"])]
        # Security master pins full scope, independently from Connect membership.
        mpin, master, master_sha = self._manifest("security_master", date, root, context)
        mrelative = mpin.get("artifact_relative", "assets/hk_security_master/" + master["artifact_relative"])
        master_raw = SafeRoot(root).read_bytes(mrelative)
        if raw_sha(master_raw) != master["artifact_sha256"]:
            raise ValueError("HK_MASTER_SHA_MISMATCH")
        master_rows = list(csv.DictReader(io.StringIO(master_raw.decode("utf-8-sig"))))
        master_codes = {symbol(r.get("code", r.get("symbol", r.get("code_norm")))) for r in master_rows}
        master_codes.discard(None)
        if len(master_codes) != master["row_count"]:
            raise ValueError("HK_MASTER_SCOPE_COUNT_MISMATCH")
        refs.append(self._ref("v3_shared_data", "HK_SECURITY_MASTER", date, master["artifact_sha256"],
                              mrelative, master.get("captured_at"), manifest=mpin["manifest_relative"]))
        by_code = {}
        for code, group in frame.groupby(code_col):
            sym = symbol(code)
            if sym:
                by_code[sym] = group.to_dict("records")
        codes, member_ref, gaps = self.membership(context)
        if member_ref:
            refs.append(member_ref)
        wanted = []; cursor = date
        for _ in range(61):
            wanted.append(cursor); cursor=previous_session(self.calendar,cursor,market="hk_securities")
        wanted.reverse()
        records = []
        for code in sorted(master_codes):
            bars = []
            for raw_row in by_code.get(code, []):
                # Parquet nulls/nonfinite cells remain unknown, so one bad
                # security cannot make the whole immutable batch non-JSON.
                def clean(v):
                    import math
                    if isinstance(v,float) and not math.isfinite(v):return None
                    if isinstance(v,dict):return {k:clean(x) for k,x in v.items()}
                    if isinstance(v,list):return [clean(x) for x in v]
                    return v
                raw_row=clean(raw_row)
                native = raw_row.get("native_fields") if isinstance(raw_row.get("native_fields"),dict) else {}
                volume_unit = native.get("volume_unit") or raw_row.get("volume_unit") or pin.get("volume_unit")
                price_basis = native.get("price_basis") or raw_row.get("price_basis") or pin.get("price_basis")
                bars.append(dict(date=str(raw_row[date_col]), close=raw_row.get("close"), high=raw_row.get("high"),
                                 volume=raw_row.get("volume", raw_row.get("trade")),
                                 volume_unit=volume_unit, price_basis=price_basis, currency=raw_row.get("currency", pin.get("currency")),
                                 suspended=raw_row.get("suspended", False),
                                 source_available_at=raw_row.get("request_finished_at", pin.get("available_at")),
                                 source_metadata={k:(None if isinstance(v,float) and pd.isna(v) else v) for k,v in raw_row.items() if k == "source" or k == "source_path" or k.startswith("history_") or k == "native_fields"}))
            record = dict(symbol=code, price_session=date, bars=sorted(bars,key=lambda r:r["date"]),
                          expected_sessions=pin.get("expected_sessions"),
                          evidence_ids=[r.evidence_id for r in refs], name=None)
            record["history_resolution_proofs"] = resolution_proofs
            if code in resolution_holds:
                record["window_gap"] = "HK_HISTORY_FIELD_QUARANTINED"
            record["panel_origin"] = dict(actual_panel_max_date=actual_max,projection_price_date=date,
                manifest_relative=pin["manifest_relative"],manifest_sha256=msha,panel_sha256=manifest["panel_sha256"],
                available_at=available)
            # Restrict the comparison to its exact 61-session window. Older panel
            # history remains in the original artifact, not in window admission.
            record["bars"] = [b for b in record["bars"] if b["date"] in wanted]
            sources=set()
            for b in record["bars"]:
                meta=b["source_metadata"]
                source=meta.get("history_source",meta.get("source"))
                if source is not None: sources.add(str(source))
            if len(sources)>1: record["window_gap"]="PANEL_MIXED_SOURCE_COMPARISON_UNVERIFIED"
            records.append(self._member(record, codes, member_ref))
        from ..engines.oversold import window_metrics
        base = batch(context,Lane.OVERSOLD,records,refs,"Shared HK panel window",Coverage(scope_count=len(master_codes),observed_count=len(records)),gaps)
        shaped = self._engine_shape(base)
        missing = {}
        for record,row in zip(records,shaped.records):
            reasons=[]
            try: window_metrics(context.model_dump(mode="json"),row)
            except (ValueError,KeyError,TypeError) as exc:
                reasons.append(str(exc) if str(exc).isidentifier() else "OVERSOLD_EVIDENCE_UNASSESSED")
            absent=[d for d in wanted if d not in {b["date"] for b in record["bars"]}]
            if absent and "HISTORY_DATE_DUPLICATE_OR_GAP" not in reasons:reasons.append("HISTORY_DATE_DUPLICATE_OR_GAP")
            record["panel_window_gaps"]=reasons
            record["panel_missing_sessions"]=absent
            record["window_origin"]="PANEL"
            if reasons:missing[record["symbol"]]=reasons
        if missing and not panel_only:
            # The old six-day sidecar cannot prove a mixed-provider 61-day
            # comparison. Keep it as an explicit gap; do not splice its bars.
            if "supplement" in pin:gaps.append("LEGACY_SIX_DAY_SUPPLEMENT_COMPARISON_UNVERIFIED")
            if pin.get("supplement_gap"):gaps.append(pin["supplement_gap"])
            futu={};tdx={}
            for original in pin.get("futu_history",[]):
                if original.get("symbol") not in missing:continue
                try:
                    sym,bars,basis,ref=self._futu_history(context,original,date)
                    if sym not in master_codes or sym in futu:raise ValueError("FUTU_HISTORY_SCOPE_OR_DUPLICATE_INVALID")
                    futu[sym]=(bars,basis,ref);refs.append(ref)
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    gaps.append(str(exc) if isinstance(exc,ValueError) else "FUTU_HISTORY_OWNER_UNAVAILABLE")
            if pin.get("tdxpy_history"):
                try:
                    tdx,tdx_refs,tdx_gaps=self._tdxpy_history(context,pin["tdxpy_history"],date,
                        manifest["panel_sha256"],master["artifact_sha256"],master_codes,msha,master_sha)
                    refs.extend(tdx_refs);gaps.extend(tdx_gaps)
                except (OSError,ValueError,KeyError,TypeError) as exc:
                    gaps.append(str(exc) if isinstance(exc,ValueError) else "TDXPY_HISTORY_OWNER_UNAVAILABLE")
            for record in records:
                code=record["symbol"]
                if code in resolution_holds:continue  # audit-only disputes cannot become a supplement gap fallback
                if code not in missing or code not in tdx and code not in futu:continue
                bars,basis,ref=tdx[code] if code in tdx else futu[code]
                record.pop("window_gap",None)
                record.update(bars=bars,comparison_basis=basis,source_sha256=ref.sha256,available_at=ref.available_at,
                    window_origin="PANEL_OWNER_SUPPLEMENT",evidence_ids=[ref.evidence_id]+([member_ref.evidence_id] if member_ref else []))
        return batch(context, Lane.OVERSOLD, records, refs, "Full exact-date security master and shared HK history",
                     Coverage(scope_count=len(master_codes), observed_count=len(records), gaps=gaps), gaps,
                     member_ref.evidence_id if member_ref else None)

    def panel_gap_plan(self, context):
        """Read-only machine scope for the existing shared supplement owner."""
        from upstreams.v3_shared_data.shared_data.hk_daily_supplement import _read_panel_identity, _read_master_identity
        value=self.oversold(context,panel_only=True)
        date=context.source_sessions["hk_price"]
        pin=self._binding("hk_panel",date,context)
        panel=_read_panel_identity(self.config.shared_root,date,manifest_relative=pin["manifest_relative"],
            manifest_sha256=pin["manifest_sha256"],allow_projection=context.phase.value=="RETROSPECTIVE")
        master,codes=_read_master_identity(self.config.shared_root,date)
        actual=sorted(r["symbol"] for r in value.records)
        master_ref=next(ref for ref in value.evidence_refs if ref.role=="HK_SECURITY_MASTER")
        if actual!=codes or master_ref.sha256!=master['artifact_sha256']:
            raise ValueError("PANEL_GAP_MASTER_SCOPE_CHANGED")
        # Recheck both immutable parent identities after window projection.
        origin=value.records[0]["panel_origin"]
        if panel["panel_sha256"]!=origin["panel_sha256"] or panel["panel_manifest_sha256"]!=origin["manifest_sha256"]:
            raise ValueError("PANEL_GAP_PARENT_CHANGED")
        wanted=[];cursor=date
        for _ in range(61):
            wanted.append(cursor);cursor=previous_session(self.calendar,cursor,market="hk_securities")
        wanted.reverse()
        rows=[dict(code=r["symbol"],reasons=r["panel_window_gaps"],missing_sessions=r["panel_missing_sessions"]) for r in value.records]
        return dict(schema_version="v3_shared_data.hk_0_2_panel_window_gaps.v1",
            window_validator="OVERSOLD_60_5_V1",target_date=context.target_date,price_date=date,
            phase=context.phase.value,cutoff=context.cutoff,requested_sessions=wanted,calendar_sha256=raw_sha(CALENDAR_PATH.read_bytes()),
            panel_identity=panel,master_identity=master,master_scope_count=len(codes),records=rows,
            gap_codes=[r["code"] for r in rows if r["reasons"]],panel_valid_count=sum(not r["reasons"] for r in rows),
            replacement_reason="COMPLETE_61_SAME_PROFILE_REQUIRED_NO_UNVERIFIED_SOURCE_MIX",
            protocol_request_count=128,projected_session_count=61)

    def us_mapping(self, context):
        expected = context.source_sessions.get("us") or self._us_session(context.cutoff)
        pin = self._binding("us_mapping", context.target_date, context)
        # Pinned native US owner payload + reviewed registry, never old computed matches.
        quote_root = Path(pin.get("quote_local_path") or pin["quote_root"])
        quotes, qsha = self._json(quote_root, pin["quote_relative"], pin["quote_sha256"])
        snapshot=quotes.get("market_snapshot",quotes)
        if not isinstance(snapshot,dict):raise ValueError("US_NATIVE_SNAPSHOT_SHAPE_INVALID")
        registry, rsha = self._json(Path(pin.get("relation_local_path") or pin["relation_root"]), pin["relation_relative"], pin["relation_sha256"])
        registry = pin.get("relation_projection",registry)
        if snapshot.get("session_date", snapshot.get("us_session_date",snapshot.get("capture_session_date"))) != expected:
            raise ValueError("US_SESSION_MISMATCH")
        configured = pin.get("configured_symbols", [])
        if len(configured) != 33 or len(set(configured)) != 33:
            raise ValueError("US_FIXED_33_SCOPE_INVALID")
        codes, member_ref, gaps = self.membership(context)
        refs = [self._ref(pin["quote_owner"], "US_FIXED_33_QUOTES", expected, qsha,
                          pin["quote_relative"], snapshot.get("available_at", snapshot.get("captured_at"))),
                self._ref(pin["relation_owner"], "REVIEWED_US_HK_RELATIONS", expected, rsha,
                          pin["relation_relative"], registry.get("available_at"))]
        factor_payload = None
        if context.rules_version == US_FACTOR_RULES_VERSION:
            factor_pin = pin.get("factor_exposure")
            if isinstance(factor_pin, dict) and factor_pin.get("status") == "READY":
                candidate, review = factor_pin.get("candidate"), factor_pin.get("review")
                target_memberships = {}
                for fact in candidate.get("rows", []) if isinstance(candidate, dict) else []:
                    if not isinstance(fact, dict): continue
                    member = self._member(dict(symbol=fact.get("symbol"), evidence_ids=[]), codes, member_ref)
                    target_memberships[fact.get("id")] = member.get("membership")
                factor_payload = dict(candidate=candidate, review=review,
                    candidate_sha256=factor_pin.get("candidate_sha256"),
                    review_sha256=factor_pin.get("review_sha256"), target_memberships=target_memberships,
                    hk_scope_count=len(codes) if member_ref else None,
                    candidate_relative=factor_pin.get("candidate_relative"),
                    review_relative=factor_pin.get("review_relative"),
                    evidence_ids=[ref.evidence_id for ref in refs if ref.role in {
                        "US_FIXED_33_QUOTES", "MONTHLY_CONNECT_MEMBERSHIP",
                        "US_FACTOR_EXPOSURE_CANDIDATE", "US_FACTOR_EXPOSURE_INDEPENDENT_REVIEW"}])
                refs.append(self._ref("V4_REVIEWED_US_FACTOR_EXPOSURE", "US_FACTOR_EXPOSURE_CANDIDATE",
                    context.target_date, factor_pin["candidate_sha256"], factor_pin["candidate_relative"],
                    candidate.get("created_at")))
                refs.append(self._ref(review["review_owner"], "US_FACTOR_EXPOSURE_INDEPENDENT_REVIEW",
                    context.target_date, factor_pin["review_sha256"], factor_pin["review_relative"],
                    review.get("reviewed_at")))
            else:
                factor_payload = dict(gap=(factor_pin or {}).get("gap", pin.get("factor_exposure_gap")
                    or "US_FACTOR_PAIRED_REVIEW_UNAVAILABLE"), hk_scope_count=len(codes) if member_ref else None)
        for source in registry.get("additional_relation_sources",[]):
            refs.append(self._ref(source["owner"],"REVIEWED_US_HK_RELATIONS",expected,source["sha256"],source["relative"],source["available_at"]))
        if member_ref:
            refs.append(member_ref)
        if isinstance(factor_payload, dict):
            factor_payload["evidence_ids"] = [ref.evidence_id for ref in refs if ref.role in {
                "US_FIXED_33_QUOTES", "MONTHLY_CONNECT_MEMBERSHIP",
                "US_FACTOR_EXPOSURE_CANDIDATE", "US_FACTOR_EXPOSURE_INDEPENDENT_REVIEW"}]
        quote_rows = snapshot.get("quotes",snapshot.get("symbols",snapshot.get("rows", [])))
        if isinstance(quote_rows, dict):
            quote_rows = [{"symbol":s, **v} for s,v in quote_rows.items()]
        quote_map = {q.get("symbol"):q for q in quote_rows if q.get("symbol") in configured}
        relations = registry.get("cards", registry.get("relations", []))
        mapped = []
        for relation in relations:
            us = relation.get("us_symbol")
            if us not in configured:
                continue
            sym = symbol(relation.get("hk_symbol", relation.get("hk_code")))
            if not sym:
                gaps.append("US_RELATION_HK_IDENTITY_UNKNOWN")
                continue
            record = dict(symbol=sym, name=relation.get("hk_name"), us_symbol=us,
                          session_date=expected, quote=quote_map.get(us), relation=relation,
                          relation_reviewed=relation.get("evidence_review_status") in {"VERIFIED", "REVIEWED", "PASS"},
                          available_at=relation.get("available_at", registry.get("available_at")),
                          evidence_ids=[r.evidence_id for r in refs])
            mapped.append(self._member(record, codes, member_ref))
        if len(quote_map) != 33:
            gaps.append("US_FIXED_33_QUOTES_PARTIAL")
        # Absent relations remain an explicit scope gap, never a fabricated HK row.
        linked = {r["us_symbol"] for r in mapped}
        if set(configured) - linked:
            gaps.append("US_SYMBOL_RELATIONS_UNASSESSED:" + ",".join(sorted(set(configured)-linked)))
        records = []
        for us in configured:
            q = quote_map.get(us, {})
            relations_for_us = []
            for row in mapped:
                if row["us_symbol"] != us: continue
                relation = row["relation"]
                relations_for_us.append(dict(target_symbol=row["symbol"],target_name=row["name"],
                    membership=row.get("membership"),evidence_ids=row["evidence_ids"],
                    status="REVIEWED" if row["relation_reviewed"] else "CANNOT_CONFIRM",
                    sha256=relation.get("relation_identity_sha256", owner_digest(relation)),
                    review_owner=relation.get("reviewer_identity"), available_at=row["available_at"],
                    published_at=relation.get("published_at"),relation_type=relation.get("relationship_type"),
                    publication_evidence=relation.get("publication_evidence",[
                        dict(role=source.get("role"),published_at=source.get("published_at"),
                             precision="DATE" if isinstance(source.get("published_at"),str) and len(source["published_at"])==10 else "TIMESTAMP",
                             source_body_sha256=source.get("source_body_sha256"),url=source.get("url"))
                        for source in relation.get("sources",[])]),
                    research_priority=relation.get("research_priority"),research_basis=relation.get("reason"),
                    research_priority_reason=relation.get("research_priority_reason"),
                    priority_assessment=relation.get("priority_assessment"),
                    relation_limitations=relation.get("limitations",[]),
                    publication_time_gaps=["RELATION_SOURCE_PUBLICATION_TIME_UNKNOWN"] if any(
                        source.get("role")=="RELATION" and not source.get("published_at") for source in relation.get("sources",[])) else [],
                    relation_source_refs=relation.get("relation_source_refs",[])))
            records.append(dict(us_symbol=us,source_session=expected,owner=pin["quote_owner"],source_sha256=qsha,
                source_status="CANNOT_CONFIRM", positive_change_required=True,
                available_at=snapshot.get("available_at",snapshot.get("captured_at")),relations=relations_for_us,
                quote=q,evidence_ids=[r.evidence_id for r in refs],
                reviewed_assessments=[a for a in registry.get("symbol_assessments",[]) if a.get("original",{}).get("us_symbol")==us],
                proxy_metadata=[dict(label=proxy.get("label"),mapping_type=proxy["mapping_type"],
                    source_sha256=qsha,owner=pin["quote_owner"],available_at=snapshot.get("available_at",snapshot.get("captured_at")),
                    **({"owner_row":dict(proxy)} if context.rules_version == US_FACTOR_RULES_VERSION else {}))
                    for proxy in snapshot.get("rows",[]) if isinstance(proxy,dict) and proxy.get("mapping_type") in (
                        ("etf_proxy","etf_basket_proxy","stock_basket_proxy") if context.rules_version == US_FACTOR_RULES_VERSION
                        else ("etf_proxy","etf_basket_proxy"))
                    and us in proxy.get("proxy_symbols",[])]))
        # Carry every relation from the canonical 667/1,003 catalog into
        # the selector as an explicitly non-selectable observation. Raw source,
        # review-use and recovery closure fields remain nested and unchanged.
        overlay_summary = pin.get("full_overlay_summary") or {}
        overlay_rows = pin.get("full_overlay_projection") or []
        if overlay_summary.get("state") == "READY":
            for relation in overlay_rows:
                hk_code = relation.get("hk_code")
                target_symbol = symbol(hk_code)
                if not target_symbol:
                    gaps.append("US_MAPPING_OVERLAY_HK_IDENTITY_INVALID")
                    continue
                relation_identity = owner_digest(relation)
                catalog_relation = dict(
                    target_symbol=target_symbol,
                    target_name=relation.get("hk_name"),
                    status="CANNOT_CONFIRM",
                    sha256=relation_identity,
                    relation_type="CATALOG_OBSERVATION_ONLY",
                    research_priority="NONE",
                    catalog_relation=relation,
                    catalog_relation_id=relation.get("relation_id"),
                    catalog_research_use=relation.get("research_use"),
                    catalog_recovery_status=(relation.get("recovery_v2r1") or {}).get("closure_status"),
                )
                records.append(dict(
                    us_symbol=None, source_session=expected,
                    owner="v4.manager_workbench.us_mapping_catalog",
                    source_sha256=overlay_summary.get("catalog_file_sha256"),
                    source_status="CATALOG_OBSERVATION",
                    positive_change_required=False, available_at=None, quote={},
                    relations=[catalog_relation], evidence_ids=[],
                ))
            if len(overlay_rows) != 1003 or len([
                row for row in records if row.get("source_status") == "CATALOG_OBSERVATION"
            ]) != 1003:
                gaps.append("US_MAPPING_OVERLAY_CONSUMER_COUNT_MISMATCH")
        else:
            gaps.append(overlay_summary.get("gap", "US_MAPPING_FULL_OVERLAY_NOT_BOUND"))
        if factor_payload is not None and records:
            records[0]["us_factor_payload"] = factor_payload
        return batch(context, Lane.US_MAPPING, records, refs, "Fixed 33 configured US symbols and audited relation scope",
                     Coverage(scope_count=33, observed_count=len(quote_map), gaps=gaps), gaps,
                     member_ref.evidence_id if member_ref else None)

    def stage(self, context):
        root = self.config.stage_root
        pin = context.scope_refs.get("owner_bindings",{}).get("stage")
        if pin is None:
            pointer, _ = self._json(root, "selection_latest.json")
        else:
            pointer = {"entries":pin["entries"]}
        records, refs, gaps = [], [], []
        for key, entry in pointer.get("entries", {}).items():
            if entry.get("trade_date") != context.target_date or entry.get("market") != "HK_CONNECT":
                continue
            rel = entry["artifact_relative"]
            parent = str(Path(rel).parent)
            manifest, msha = self._stage_json(root, parent + "/manifest.json", entry["manifest_sha256"],
                                            "stage_center.selection.manifest.v1")
            receipt, rsha = self._stage_json(root, parent + "/receipt.json", entry["receipt_sha256"],
                                           "stage_center.selection.receipt.v1")
            raw = SafeRoot(root).read_bytes(rel)
            if (raw_sha(raw) != entry["artifact_sha256"] or manifest.get("run_id") != entry.get("run_id")
                    or receipt.get("manifest_sha256") != entry["manifest_sha256"] or manifest.get("market") != "HK_CONNECT"
                    or manifest.get("trade_date") != context.target_date or manifest.get("production_allowed") is not False):
                gaps.append("STAGE_MANIFEST_RECEIPT_BINDING_INVALID")
                continue
            available = receipt.get("finished_at", receipt.get("generated_at"))
            ref = self._ref("stage_center", entry["role"], context.target_date, raw_sha(raw), rel,
                            available, manifest=parent+"/manifest.json", receipt=parent+"/receipt.json")
            refs.append(ref)
            refs.extend([self._ref("stage_center", "STAGE_MANIFEST_RAW", context.target_date, msha,
                                  parent+"/manifest.json", available),
                         self._ref("stage_center", "STAGE_RECEIPT_RAW", context.target_date, rsha,
                                  parent+"/receipt.json", available)])
            parsed = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))) if rel.endswith(".csv") else json.loads(raw).get("rows", [])
            if len(parsed) != manifest.get("row_count"):
                gaps.append("STAGE_ROW_COUNT_MISMATCH")
                continue
            for row in parsed:
                sym = symbol(row.get("symbol", row.get("code", row.get("code_norm"))))
                if sym:
                    records.append(dict(symbol=sym, name=row.get("name"), native=row,
                                        stage_run_id=entry["run_id"], stage_id=entry["stage_id"],
                                        available_at=available, evidence_ids=[ref.evidence_id],
                                        membership_status="CANNOT_CONFIRM"))
        if not refs:
            gaps.append("EXACT_DATE_STAGE_NOT_AVAILABLE")
        return batch(context, Lane.STAGE_REFERENCE, records, refs, "Original HK D-1 canonical Stage outputs; observation only",
                     Coverage(observed_count=len(records), gaps=gaps), gaps)

    def close(self, context):
        pin, manifest, msha = self._manifest("close", context.target_date, self.config.shared_root, context)
        rel = pin.get("artifact_relative", "assets/hk_0_2/" + manifest["artifact_relative"])
        data, sha = self._json(self.config.shared_root, rel, manifest["artifact_sha256"])
        receipt_relative=pin.get("receipt_relative")
        if receipt_relative:
            receipt, _ = self._json(self.config.shared_root,receipt_relative,pin.get("receipt_sha256"))
            if receipt.get("manifest_sha256")!=msha or receipt.get("run_id")!=manifest.get("run_id"):
                raise ValueError("CLOSE_RECEIPT_BINDING_INVALID")
        ref = self._ref("review_core", "FULL_CLOSE_RANKING", context.target_date, sha, rel,
                        data.get("available_at", data.get("generated_at")), manifest=pin["manifest_relative"],receipt=receipt_relative)
        rows = data.get("rows", data.get("stocks", []))
        if len(rows) != manifest.get("row_count"):
            raise ValueError("CLOSE_ROW_COUNT_MISMATCH")
        records = [{**r, "symbol":symbol(r.get("symbol", r.get("code"))),
                    "evidence_ids":[ref.evidence_id]} for r in rows if symbol(r.get("symbol",r.get("code")))]
        gaps = [] if data.get("complete_ranking") is True and data.get("market") == "HK_CONNECT" and receipt_relative else ["FULL_CLOSE_RANKING_UNVERIFIED"]
        return batch(context, Lane.CLOSE_REFERENCE, records, [ref], "Exact-date full authoritative HK close ranking",
                     Coverage(scope_count=data.get("scope_count"), observed_count=len(records), gaps=gaps), gaps,
                     data.get("evaluation_scope_ref"))
