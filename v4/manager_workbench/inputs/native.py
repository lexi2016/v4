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
                    calendar_verified=True, sha256=owner_digest(pin), universe_ref="us-fixed33:"+context.target_date)
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
            if lane == Lane.ANNOUNCEMENT:
                candidates = [by_id[eid] for eid in item.get("evidence_ids", []) if eid in by_id
                    and by_id[eid].role in {"ANNOUNCEMENT_BODY", "ANNOUNCEMENT_CAPTURED_BODY"}
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
                        return str(v) if v is not None and math.isfinite(float(v)) else None
                    return dict(session=b.get("date"),close=number(b.get("close")),high=number(b.get("high")),
                                volume=number(b.get("volume")),price_unit=b.get("currency"),volume_unit=b.get("volume_unit"),
                                adjustment=b.get("price_basis"),available_at=b.get("source_available_at"))
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

    def oversold(self, context):
        date = context.source_sessions.get("hk_price") or previous_session(self.calendar, context.target_date, market="hk_securities")
        pin = self._binding("hk_panel", date, context)
        root = self.config.shared_root
        manifest, msha = self._json(root, pin["manifest_relative"], pin["manifest_sha256"])
        if manifest.get("panel_max_date") != date or manifest.get("research_only") is not True or manifest.get("production_allowed") is not False:
            raise ValueError("HK_PANEL_DATE_OR_SAFETY_INVALID")
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
        refs = [self._ref("v3_shared_data", "HK_DAILY_PANEL", date, manifest["panel_sha256"],
                          artifact_relative, pin.get("available_at"), manifest=pin["manifest_relative"])]
        # Security master pins full scope, independently from Connect membership.
        mpin, master, master_sha = self._manifest("security_master", date, root, context)
        mrelative = mpin.get("artifact_relative", "assets/hk_security_master/" + master["artifact_relative"])
        master_raw = SafeRoot(root).read_bytes(mrelative)
        if raw_sha(master_raw) != master["artifact_sha256"]:
            raise ValueError("HK_MASTER_SHA_MISMATCH")
        master_rows = list(csv.DictReader(io.StringIO(master_raw.decode())))
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
        # Optional pinned existing supplement, no fetching and no second producer.
        if "supplement" in pin:
            sp = pin["supplement"]
            sm, _ = self._json(root, sp["manifest_relative"], sp["manifest_sha256"])
            supplement_relative = sp.get("raw_relative", "assets/hk_0_2/" + sm["raw_capture_relative"])
            supplemental, ssha = self._json(root, supplement_relative, sm["raw_capture_sha256"])
            if sm.get("target_date") != date:
                raise ValueError("HK_SUPPLEMENT_DATE_MISMATCH")
            refs.append(self._ref("v3_shared_data", "HK_DAILY_SUPPLEMENT", date, ssha,
                                  supplement_relative, sm.get("prepared_at"), manifest=sp["manifest_relative"]))
            for source in supplemental.get("records", []):
                sym = symbol(source.get("code"))
                if sym:
                    existing = {str(r.get(date_col)):r for r in by_code.get(sym, [])}
                    for bar in source.get("bars", []):
                        if bar.get("trade_date") <= date and bar["trade_date"] not in existing:
                            existing[bar["trade_date"]] = {**bar, date_col:bar["trade_date"]}
                    by_code[sym] = list(existing.values())
        codes, member_ref, gaps = self.membership(context)
        if member_ref:
            refs.append(member_ref)
        records = []
        for code in sorted(master_codes):
            bars = []
            for raw_row in by_code.get(code, []):
                native = raw_row.get("native_fields", {})
                volume_unit = native.get("volume_unit") or raw_row.get("volume_unit") or pin.get("volume_unit")
                price_basis = native.get("price_basis") or raw_row.get("price_basis") or pin.get("price_basis")
                bars.append(dict(date=str(raw_row[date_col]), close=raw_row.get("close"), high=raw_row.get("high"),
                                 volume=raw_row.get("volume", raw_row.get("trade")),
                                 volume_unit=volume_unit, price_basis=price_basis, currency=raw_row.get("currency", pin.get("currency")),
                                 suspended=raw_row.get("suspended", False),
                                 source_available_at=raw_row.get("request_finished_at", pin.get("available_at"))))
            record = dict(symbol=code, price_session=date, bars=sorted(bars,key=lambda r:r["date"]),
                          expected_sessions=pin.get("expected_sessions"),
                          evidence_ids=[r.evidence_id for r in refs], name=None)
            records.append(self._member(record, codes, member_ref))
        return batch(context, Lane.OVERSOLD, records, refs, "Full exact-date security master and shared HK history",
                     Coverage(scope_count=len(master_codes), observed_count=len(records), gaps=gaps), gaps,
                     member_ref.evidence_id if member_ref else None)

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
        if member_ref:
            refs.append(member_ref)
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
                    published_at=relation.get("published_at"),relation_type=relation.get("relationship_type")))
            records.append(dict(us_symbol=us,source_session=expected,owner=pin["quote_owner"],source_sha256=qsha,
                source_status=q.get("research_priority", q.get("priority", "CANNOT_CONFIRM")),
                available_at=snapshot.get("available_at",snapshot.get("captured_at")),relations=relations_for_us,
                quote=q,evidence_ids=[r.evidence_id for r in refs]))
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
            manifest, msha = self._json(root, parent + "/manifest.json", entry["manifest_sha256"])
            receipt, rsha = self._json(root, parent + "/receipt.json", entry["receipt_sha256"])
            raw = SafeRoot(root).read_bytes(rel)
            if (raw_sha(raw) != entry["artifact_sha256"] or manifest.get("run_id") != entry.get("run_id")
                    or receipt.get("manifest_sha256") != msha or manifest.get("market") != "HK_CONNECT"
                    or manifest.get("trade_date") != context.target_date or manifest.get("production_allowed") is not False):
                gaps.append("STAGE_MANIFEST_RECEIPT_BINDING_INVALID")
                continue
            available = receipt.get("finished_at", receipt.get("generated_at"))
            ref = self._ref("stage_center", entry["role"], context.target_date, raw_sha(raw), rel,
                            available, manifest=parent+"/manifest.json", receipt=parent+"/receipt.json")
            refs.append(ref)
            parsed = list(csv.DictReader(io.StringIO(raw.decode()))) if rel.endswith(".csv") else json.loads(raw).get("rows", [])
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
