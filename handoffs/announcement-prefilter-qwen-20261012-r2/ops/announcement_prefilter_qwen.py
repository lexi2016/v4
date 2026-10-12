"""Issue #38: fail-closed daily announcement prefilter and local-model cache.

Research evidence ONLY.  A quote-checked result is never a reviewed semantic
catalog or an owner-import authorization.  This code consumes existing captured
catalog/body JSON; it does not fetch announcements, place orders, or create timers.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

RULE_VERSION = "v4.ann-prefilter-r1"
PARSER_VERSION = "v4.body-identity-r1"
PROMPT_VERSION = "v4.qwen-body-facts-r1"
SCHEMA_VERSION = "v4.qwen-verifiable-facts-r1"
OUTPUT_SCHEMA = "v4.announcement-prefilter-triage.v1"
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}
HASH = re.compile(r"^[0-9a-f]{64}$")
ROUTINE_TITLE = re.compile(r"^(?:公司通[讯訊]的?发[布佈]通知|公司通[讯訊]之发[布佈]通知|通知信函)$")
ROUTINE_BODY = re.compile(r"公司通[讯訊].*(?:[电電]子方式|公司网[站頁]|公司網[站頁])")
MATERIAL_TERMS = re.compile(
    r"盈利|业绩|業績|預警|预警|亏损|虧損|收购|收購|兼并|併購|重组|重組|重大|"
    r"诉讼|訴訟|仲裁|债务|債務|融资|融資|担保|擔保|违约|違約|监管|監管|"
    r"停牌|复牌|復牌|股权|股權|股份配售|回购|回購|清盘|清盤|关联|關聯|"
    r"联营|聯營|第三方|未偿|未償|已偿|已償|本金|贷款|貸款|利息|变更|變更|"
    r"生效|条件|條件|终止|終止|限制|豁免|处罚|處罰|合约|合約|合同|"
    r"上限|低于|高於|不低於|不超过|不超過|增持|减持|減持|发股|發股|"
    r"acquisition|merger|profit.warning|litigation|default|outstanding|"
    r"loan|guarantee|capital|regulat|related.party|material|condition|effective",
    re.I)
EXCEPTION_NUMERAL = re.compile(r"[0-9０-９零〇一二三四五六七八九十百千萬万億亿]|%|％|\$|¥|￥|HKD|RMB|USD", re.I)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(value)
    out["sha256"] = _sha(json.dumps(out, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))
    return out


def _check_seal(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("sha256"), str) and _seal({
        k: v for k, v in value.items() if k != "sha256"})["sha256"] == value["sha256"]


def _safe_dir(root: Path) -> Path:
    root = root.expanduser().absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("PREFILTER_STORAGE_SYMLINK_ROOT_FORBIDDEN")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_write(path: Path, record: Mapping[str, Any]) -> None:
    if path.is_symlink():
        raise ValueError("PREFILTER_STORAGE_SYMLINK_ARTIFACT_FORBIDDEN")
    raw = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _date_pair(catalog: Mapping[str, Any], body: Mapping[str, Any]) -> tuple[str, str, Mapping[str, Any]]:
    target = catalog.get("target_trade_date")
    publication = catalog.get("publication_date")
    source = catalog.get("catalog")
    if (not isinstance(target, str) or not re.fullmatch(r"\d{8}", target)
            or not isinstance(publication, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", publication)
            or datetime.strptime(target, "%Y%m%d").strftime("%Y%m%d") != target
            or datetime.strptime(publication, "%Y-%m-%d").strftime("%Y-%m-%d") != publication
            or body.get("target_notice_date") != publication
            or catalog.get("readback_status") != "VERIFIED"
            or (isinstance(source, Mapping) and (source.get("target_trade_date") not in (None, target)
                or source.get("publication_date") not in (None, publication)))
            or not isinstance(source, Mapping) or source.get("status") != "COMPLETE"
            or not re.fullmatch(r"[0-9a-f]{32}", str(source.get("run_id", "")))
            or not HASH.fullmatch(str(source.get("sha256", "")))):
        raise ValueError("PREFILTER_EXACT_DATE_CATALOG_READBACK_REQUIRED")
    return target, publication, source


def audit_catalog(catalog: Mapping[str, Any], body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One audit item per original listing row; never discard duplicate/conflict rows."""
    target, pub, source = _date_pair(catalog, body)
    listings = source.get("manager_consumer_rows")
    bodies = body.get("rows")
    if not isinstance(listings, list) or not isinstance(bodies, list):
        raise ValueError("PREFILTER_CATALOG_OR_BODY_ROWS_INVALID")
    if body.get("article_count") != len(bodies):
        raise ValueError("PREFILTER_BODY_CORPUS_COUNT_MISMATCH")
    lookup: dict[str, list[Mapping[str, Any]]] = {}
    for r in bodies:
        if not isinstance(r, Mapping) or not isinstance(r.get("art_code"), str):
            raise ValueError("PREFILTER_BODY_ROW_IDENTITY_INVALID")
        lookup.setdefault(r["art_code"], []).append(r)
    seen: dict[str, tuple[int, str]] = {}
    conflict: set[str] = set()
    result = []
    for i, listing in enumerate(listings):
        listing = listing if isinstance(listing, Mapping) else {}
        code = listing.get("art_code")
        issuer_rows = listing.get("source_issuer_codes")
        normalized_issuers = [dict(row) for row in issuer_rows] if isinstance(issuer_rows, list) and all(
            isinstance(row, Mapping) for row in issuer_rows) else []
        linked = lookup.get(code, []) if isinstance(code, str) else []
        item = linked[0] if len(linked) == 1 else None
        reason = None
        if not isinstance(code, str) or not code or not re.fullmatch(r"[A-Za-z0-9_-]+", code):
            reason = "ART_CODE_INVALID"
        elif (not normalized_issuers or any(not isinstance(x.get("code"), str) or not x["code"]
                or x.get("market_code") != "116" or x.get("ann_type") != "H" for x in normalized_issuers)):
            reason = "ISSUER_OR_MARKET_IDENTITY_INVALID"
        elif not isinstance(listing.get("notice_date"), str) or listing["notice_date"][:10] != pub:
            reason = "PUBLICATION_DATE_MISMATCH"
        elif item is None:
            reason = "BODY_ROW_MISSING_OR_CONFLICT"
        elif item.get("title") not in (None, listing.get("title")):
            reason = "BODY_TITLE_MISMATCH"
        elif not HASH.fullmatch(str(listing.get("raw_body_sha256", ""))):
            reason = "LISTING_SHA256_MISSING"
        elif not isinstance(listing.get("source_ref"), Mapping):
            reason = "LISTING_SOURCE_IDENTITY_MISSING"
        elif item.get("body_status") != "COMPLETE_CONTENT_API_BODY":
            reason = "BODY_CAPTURE_FAILED" if item.get("body_status") == "BODY_CAPTURE_FAILED" else "BODY_INCOMPLETE"
        elif (not isinstance(item.get("body_text"), str) or not item["body_text"].strip()
                or not HASH.fullmatch(str(item.get("body_text_sha256", "")))
                or _sha(item["body_text"].encode()) != item.get("body_text_sha256")):
            reason = "BODY_SHA256_MISMATCH"
        elif len(item["body_text"]) > 180_000:
            reason = "BODY_EXCEEDS_VERIFIED_CONTEXT_NO_TRUNCATION"
        identity = _sha(json.dumps({"issuers": normalized_issuers,
            "listing_sha256":listing.get("raw_body_sha256"), "source_ref":listing.get("source_ref"),
            "body_sha256":item.get("body_text_sha256") if item else None},
            sort_keys=True, ensure_ascii=False).encode())
        if isinstance(code, str) and code in seen:
            j, prev = seen[code]
            if prev != identity:
                conflict.add(code)
                reason = "IDENTITY_CONFLICT"
            elif reason is None:
                reason = "DUPLICATE_IDENTICAL"
        elif isinstance(code, str):
            seen[code] = i, identity
        result.append({"index":i,"art_code":code,"title":listing.get("title"),
            "issuer_codes":normalized_issuers,"source_ref":listing.get("source_ref"),
            "listing_raw_body_sha256":listing.get("raw_body_sha256"),
            "body_text_sha256":item.get("body_text_sha256") if item else None,
            "body_text":item.get("body_text") if item else None,
            "available_at": listing.get("available_at"),
            "error":reason,"market":"HK","target_trade_date":target,
            "publication_date":pub,"catalog_run_id":source["run_id"],"catalog_sha256":source["sha256"]})
    for row in result:
        if row["art_code"] in conflict:
            row["error"] = "IDENTITY_CONFLICT"
    # An extra source body is a completeness violation rather than silently ignored.
    unbound = set(lookup) - {r["art_code"] for r in result}
    if unbound:
        raise ValueError("PREFILTER_UNBOUND_BODY_ROWS:" + ",".join(sorted(unbound)))
    return result


def route_article(title: str, body: str) -> tuple[str, str]:
    """Only the narrow proven template can skip; all uncertainty goes to model."""
    title = title or ""
    body = body or ""
    if (ROUTINE_TITLE.fullmatch(title.strip()) and 20 <= len(body) <= 3000
            and ROUTINE_BODY.search(body) and not MATERIAL_TERMS.search(title + body)
            and not EXCEPTION_NUMERAL.search(title + body)):
        return "SKIPPED_ROUTINE", "ROUTINE_COMMUNICATION_TEMPLATE_NO_NUMERIC_OR_MATERIAL_EXCEPTION"
    return "MODEL_REQUIRED", "MATERIAL_AMBIGUOUS_OR_EXCEPTION_NOT_EXCLUDED"


@dataclass(frozen=True)
class LocalModelIdentity:
    name: str
    revision: str
    config_sha256: str
    endpoint: str
    proof_status: str
    proof_sha256: str
    alias: str = ""

    def verified(self) -> bool:
        p = urlsplit(self.endpoint)
        return bool(re.fullmatch(r"[\w.\-/]+", self.name) and "Qwen3.8" in self.name
            and re.fullmatch(r"[0-9a-f]{40}", self.revision)
            and HASH.fullmatch(self.config_sha256) and HASH.fullmatch(self.proof_sha256)
            and self.proof_status == "VERIFIED_LOCAL_PROCESS_AND_WEIGHTS"
            and p.scheme == "http" and p.hostname in {"localhost", "127.0.0.1", "::1"}
            and p.username is None and p.password is None and not p.query and not p.fragment
            and p.path == "/v1/chat/completions")


def attest_local_model(*, pid: int, model_dir: str, name: str, revision: str,
                       endpoint: str, alias: str = "") -> LocalModelIdentity:
    """Live identity gate; expensive weight hashing is intentional on first run.

    Cannot prove private in-memory weight pointers from ps alone.  If process
    executable/model binding or revision is unverifiable, caller stays blocked.
    """
    root = Path(model_dir).expanduser().absolute()
    if pid <= 0 or any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("MODEL_IDENTITY_CANNOT_CONFIRM")
    if not root.is_dir() or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("MODEL_IDENTITY_CANNOT_CONFIRM")
    cmd = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="],
                                  text=True, timeout=5).strip()
    config = root / "config.json"
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.port is None or parsed.path != "/v1/chat/completions"):
        raise ValueError("MODEL_IDENTITY_CANNOT_CONFIRM")
    listener = subprocess.check_output(["lsof", "-nP", "-a", "-p", str(pid),
        "-iTCP:" + str(parsed.port), "-sTCP:LISTEN"], text=True, timeout=5)
    if (not cmd or str(root) not in cmd or not listener.strip()
            or not config.is_file() or config.is_symlink()
            or not root.joinpath(".revision").is_file()
            or root.joinpath(".revision").read_text().strip() != revision):
        raise ValueError("MODEL_IDENTITY_CANNOT_CONFIRM")
    conf = json.loads(config.read_text(encoding="utf-8"))
    if (conf.get("model_type") not in {"qwen3_5", "qwen3"} or "Qwen3.8" not in name
            or "Qwen3.8" not in str(conf.get("_name_or_path", ""))):
        raise ValueError("MODEL_IDENTITY_CANNOT_CONFIRM")
    weights = sorted(root.glob("*.safetensors"))
    if not weights or any(f.is_symlink() or not f.is_file() for f in weights):
        raise ValueError("MODEL_IDENTITY_CANNOT_CONFIRM")
    hashes = {}
    for f in weights:
        h = hashlib.sha256()
        with f.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                h.update(chunk)
        hashes[f.name] = h.hexdigest()
    config_sha = _sha(config.read_bytes())
    proof = _seal({"pid":pid,"command":cmd,"model_root":str(root),"name":name,
        "revision":revision,"config_sha256":config_sha,"weight_sha256s":hashes})
    return LocalModelIdentity(name,revision,config_sha,endpoint,
        "VERIFIED_LOCAL_PROCESS_AND_WEIGHTS",proof["sha256"],alias)


class ProviderFailure(RuntimeError):
    def __init__(self, reason: str, usage: Mapping[str, Any] | None = None):
        super().__init__(reason)
        self.usage = usage


def parse_usage(value: Any) -> dict[str, Any]:
    usage = value if isinstance(value, Mapping) else {}
    out = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        n = usage.get(field)
        out[field] = n if type(n) is int and n >= 0 else "NOT_REPORTED"
    for target, sources in (("cached_tokens", ("cached_tokens",)),
                            ("reasoning_tokens", ("reasoning_tokens",))):
        n = next((usage.get(x) for x in sources if isinstance(usage.get(x), int)), None)
        if n is None:
            details = usage.get("prompt_tokens_details" if target == "cached_tokens" else "completion_tokens_details")
            if isinstance(details, Mapping):
                n = details.get("cached_tokens" if target == "cached_tokens" else "reasoning_tokens")
        out[target] = n if type(n) is int and n >= 0 else "NOT_REPORTED"
    out["usage_semantics"] = "total_tokens provider reported; cached/reasoning are nested, not additive"
    return out


def verify_facts(value: Any, body: str, expected_issuer: str) -> dict[str, Any]:
    if (not isinstance(value, Mapping) or value.get("issuer_code") != expected_issuer
            or type(value.get("is_material")) is not bool
            or not isinstance(value.get("classification"), str)
            or not isinstance(value.get("facts"), list) or not value["facts"]):
        raise ValueError("MODEL_FACTS_SCHEMA_OR_ISSUER_MISMATCH")
    facts = []
    for fact in value["facts"]:
        if not isinstance(fact, Mapping):
            raise ValueError("MODEL_FACT_INVALID")
        quote,claim = fact.get("quote"), fact.get("claim")
        subject,relation,status = fact.get("subject"),fact.get("relation"),fact.get("event_status")
        if (not isinstance(quote,str) or not quote or len(quote) > 600
                or quote not in body or not isinstance(claim,str) or claim not in quote
                or not isinstance(subject,str) or subject not in quote
                or relation not in {"UNKNOWN","INDEPENDENT_THIRD_PARTY","ASSOCIATE","ISSUER"}
                or status not in {"UNKNOWN","PLANNED","COMPLETED","OUTSTANDING"}):
            raise ValueError("MODEL_QUOTE_FACT_SUBJECT_INVALID")
        if (relation == "ASSOCIATE" and (re.search(r"独立第三方|獨立第三方|independent.third.party",quote,re.I)
                   or not re.search(r"联营|聯營|关联|關聯|associate|related.party", quote, re.I))
                or relation == "INDEPENDENT_THIRD_PARTY" and not re.search(
                    r"独立第三方|獨立第三方|independent.third.party",quote,re.I)):
            raise ValueError("MODEL_SUBJECT_RELATION_CONTRADICTS_QUOTE")
        if status == "COMPLETED" and (re.search(r"未偿|未償|尚未|未完成|outstanding|not.completed",quote,re.I)
                   or not re.search(r"已完成|完成|已結清|已结清|completed|repaid",quote,re.I)):
            raise ValueError("MODEL_COMPLETED_STATE_UNSUPPORTED")
        if status == "OUTSTANDING" and not re.search(r"未偿|未償|未清|outstanding",quote,re.I):
            raise ValueError("MODEL_OUTSTANDING_STATE_UNSUPPORTED")
        if status == "PLANNED" and not re.search(r"拟|擬|计划|計劃|將|将|proposed|plan",quote,re.I):
            raise ValueError("MODEL_PLANNED_STATE_UNSUPPORTED")
        number, unit = fact.get("number"), fact.get("unit")
        if re.search(r"[0-9]+",quote) and number is None:
            raise ValueError("MODEL_NUMBER_OMITTED")
        if number is not None and (not isinstance(number,str) or number not in quote):
            raise ValueError("MODEL_NUMBER_UNSUPPORTED")
        if unit is not None and (not isinstance(unit,str) or unit not in quote):
            raise ValueError("MODEL_UNIT_UNSUPPORTED")
        facts.append({**dict(fact), "quote_offset":body.index(quote), "quote_sha256":_sha(quote.encode())})
    return {"status":"QUOTE_CHECKED_REVIEW_REQUIRED", "classification":value["classification"],
            "is_material":value["is_material"],"facts":facts,
            "semantic_accuracy":"CANNOT_CONFIRM_WITHOUT_INDEPENDENT_REVIEW"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LoopbackChat:
    """Only a locally attested model; explicit timeout, no redirects/proxies/fallback."""
    def __call__(self, title: str, body: str, identity: LocalModelIdentity) -> dict[str, Any]:
        if not identity.verified():
            raise ProviderFailure("MODEL_IDENTITY_CANNOT_CONFIRM")
        instruction = ("仅根据提供的完整公告正文提取事实，不推断利好或交易指令。"
            "输出严格JSON: issuer_code,classification,is_material,facts[]。"
            "每个fact有quote,claim,subject,relation(UNKNOWN/INDEPENDENT_THIRD_PARTY/ASSOCIATE/ISSUER),"
            "event_status(UNKNOWN/PLANNED/COMPLETED/OUTSTANDING),number,unit。"
            "quote和claim须为完整原文连续子串。独立第三方不得写成联营，未偿本金不得写成已完成。")
        request = {"model":identity.name,"temperature":0,"stream":False,
            "messages":[{"role":"system","content":instruction},
                        {"role":"user","content":"标题："+title+"\n原文："+body}],
            "response_format":{"type":"json_object"}}
        raw = json.dumps(request,ensure_ascii=False).encode()
        url = identity.endpoint
        parsed = urlsplit(url)
        if parsed.hostname not in {"localhost","127.0.0.1","::1"}:
            raise ProviderFailure("CLOUD_OR_PROXY_ENDPOINT_FORBIDDEN")
        opener = build_opener(ProxyHandler({}),_NoRedirect())
        try:
            with opener.open(Request(url,method="POST",data=raw,
                headers={"Content-Type":"application/json"}),timeout=90) as res:
                if res.status != 200:
                    raise ProviderFailure("LOCAL_QWEN_HTTP_STATUS_"+str(res.status))
                data = res.read(8_000_001)
                if len(data)>8_000_000:
                    raise ProviderFailure("LOCAL_QWEN_RESPONSE_TOO_LARGE")
                payload=json.loads(data)
        except HTTPError as exc:
            usage = None
            try:
                body_json=json.loads(exc.read(1_000_000))
                usage=body_json.get("usage")
            except (ValueError,TypeError):
                pass
            raise ProviderFailure("LOCAL_QWEN_HTTP_ERROR_"+str(exc.code),usage) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise ProviderFailure("LOCAL_QWEN_TRANSPORT_OR_JSON_INVALID") from exc
        if not isinstance(payload,dict) or payload.get("model") not in {identity.name,identity.alias}:
            raise ProviderFailure("LOCAL_MODEL_RESPONSE_IDENTITY_MISMATCH",payload.get("usage") if isinstance(payload,dict) else None)
        try:
            content=payload["choices"][0]["message"]["content"]
        except (TypeError,KeyError,IndexError):
            raise ProviderFailure("LOCAL_QWEN_RESPONSE_SCHEMA_INVALID",payload.get("usage"))
        if not isinstance(content,str):
            raise ProviderFailure("LOCAL_QWEN_CONTENT_INVALID",payload.get("usage"))
        return {"content":content,"usage":payload.get("usage")}


class TriageEngine:
    def __init__(self, cache_root: str | Path, identity: LocalModelIdentity,
                 provider: Callable[[str,str,LocalModelIdentity],Mapping[str,Any]]):
        self.root = _safe_dir(Path(cache_root))
        self.identity=identity
        self.provider=provider
        for name in ("cache", "attempts"):
            directory = self.root/name
            if directory.is_symlink():
                raise ValueError("PREFILTER_STORAGE_SYMLINK_ARTIFACT_FORBIDDEN")
            directory.mkdir(exist_ok=True)

    def _analyze(self, row: Mapping[str, Any]) -> tuple[dict[str, Any], int, Any, bool]:
        issuer=row["issuer_codes"][0]["code"]
        # Semantic identity only: recaptured listing refs, owner dates and PID
        # are rebound per run, not reasons to spend model tokens again.
        key_data = {"issuer_codes":[x["code"] for x in row["issuer_codes"]],
            "art_code":row["art_code"],"title":str(row["title"] or ""),
            "body_sha256":row["body_text_sha256"],
            "parser_version":PARSER_VERSION,"rule_version":RULE_VERSION,
            "prompt_version":PROMPT_VERSION,"schema_version":SCHEMA_VERSION,
            "model_identity":{"name":self.identity.name,"revision":self.identity.revision,
                "config_sha256":self.identity.config_sha256}}
        key=_sha(json.dumps(key_data,sort_keys=True,ensure_ascii=False).encode())
        cache=self.root/"cache"/(key+".json")
        lock=self.root/"cache"/(key+".lock")
        if lock.is_symlink() or cache.is_symlink():
            raise ValueError("PREFILTER_CACHE_SYMLINK_ARTIFACT_FORBIDDEN")
        with lock.open("a+b") as guard:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
            if cache.is_symlink():
                raise ValueError("PREFILTER_CACHE_SYMLINK_ARTIFACT_FORBIDDEN")
            if cache.exists():
                stored=json.loads(cache.read_text(encoding="utf-8"))
                if (not _check_seal(stored) or stored.get("cache_key") != key
                        or stored.get("key_data") != key_data
                        or stored.get("semantic_status") != "QUOTE_CHECKED_REVIEW_REQUIRED"):
                    raise ValueError("PREFILTER_CACHE_IDENTITY_OR_SEAL_INVALID")
                return {"route":"MODEL_QUOTE_CHECKED_REVIEW_REQUIRED", "reason":"SEMANTIC_CACHE_HIT",
                        "cache_hit":True,"cache_key":key,"model_result":stored["model_result"]},0,0,True
            started=time.monotonic()
            usage=parse_usage(None)
            result=None
            error=None
            try:
                response=self.provider(row["title"] or "",row["body_text"],self.identity)
                if not isinstance(response,Mapping):
                    raise ProviderFailure("LOCAL_QWEN_RESPONSE_NOT_MAPPING")
                usage=parse_usage(response.get("usage"))
                content=response.get("content")
                if not isinstance(content,str) or len(content)>1_000_000:
                    raise ValueError("MODEL_RESPONSE_TRUNCATED_OR_INVALID")
                parsed=json.loads(content)
                result=verify_facts(parsed,row["body_text"],issuer)
            except ProviderFailure as exc:
                usage=parse_usage(exc.usage)
                error=str(exc)
            except (ValueError,TypeError,KeyError) as exc:
                error="MODEL_FACT_VERIFICATION_FAILED:"+str(exc)[:120]
            elapsed=round((time.monotonic()-started)*1000)
            attempt={"schema":"v4.announcement-model-attempt.v1", "cache_key":key,
                "art_code":row["art_code"],"body_sha256":row["body_text_sha256"],
                "model_identity":asdict(self.identity),"usage":usage,
                "call_status":"QUOTE_CHECKED_REVIEW_REQUIRED" if result else "NOT_ASSESSED",
                "error":error,"elapsed_ms":elapsed,"estimated_tokens":"NOT_CALCULATED",
                "finished_at":datetime.now(timezone.utc).isoformat(),**FLAGS}
            _atomic_write(self.root/"attempts"/(uuid.uuid4().hex+".json"),_seal(attempt))
            tokens=usage["total_tokens"]
            if result is None:
                return {"route":"NOT_ASSESSED","reason":error or "MODEL_UNKNOWN_ERROR",
                        "cache_hit":False,"cache_key":key,"model_result":None,
                        "usage":usage},1,tokens,False
            _atomic_write(cache,_seal({"schema":"v4.ann-qwen-cache.v1","cache_key":key,
                "key_data":key_data,"model_result":result,
                "semantic_status":"QUOTE_CHECKED_REVIEW_REQUIRED"}))
            return {"route":"MODEL_QUOTE_CHECKED_REVIEW_REQUIRED", "reason":"QUOTE_MATCH_NOT_SEMANTIC_APPROVAL",
                    "cache_hit":False,"cache_key":key,"model_result":result,"usage":usage},1,tokens,False

    def run(self, catalog: Mapping[str,Any], body: Mapping[str,Any]) -> dict[str,Any]:
        audited=audit_catalog(catalog,body)
        target,pub,source=_date_pair(catalog,body)
        rows=[]; calls=0; total=0; unknown=False; hits=0
        for row in audited:
            dest={k:v for k,v in row.items() if k != "body_text"}
            if row["error"] is not None:
                dest.update(route="NOT_ASSESSED",reason=row["error"],cache_hit=False)
            else:
                route,reason=route_article(str(row["title"] or ""),row["body_text"])
                if route=="SKIPPED_ROUTINE":
                    dest.update(route=route,reason=reason,cache_hit=False,
                        rule_id="COMMUNICATION_PLAIN_TEMPLATE_V1",rule_version=RULE_VERSION,
                        exception_checks={"numbers":False,"material_terms":False,"body_complete":True},
                        semantic_status="SCRIPT_ONLY_NOT_REVIEWED")
                elif not self.identity.verified():
                    dest.update(route="NOT_ASSESSED",reason="MODEL_IDENTITY_CANNOT_CONFIRM",cache_hit=False)
                else:
                    verdict, new_calls, token, hit = self._analyze(row)
                    dest.update(verdict)
                    calls+=new_calls
                    hits+=int(hit)
                    if isinstance(token,int):
                        total+=token
                    else:
                        unknown=True
            rows.append(dest)
        counted=sum(r["route"] in {"SKIPPED_ROUTINE","MODEL_QUOTE_CHECKED_REVIEW_REQUIRED"} for r in rows)
        return _seal({"schema":OUTPUT_SCHEMA,"status":"TRIAGED_NOT_OWNER_IMPORTED",
            "target_trade_date":target,"publication_date":pub,
            "catalog_run_id":source["run_id"],"catalog_sha256":source["sha256"],
            "model_identity":asdict(self.identity), "rule_version":RULE_VERSION,
            "input_article_rows":len(audited),"output_article_rows":len(rows),
            "routed_or_skipped":counted,"unassessed_rows":len(rows)-counted,
            "new_model_calls":calls,"new_model_tokens":"NOT_REPORTED" if unknown else total,
            "new_model_tokens_known_sum":total,"cache_hits":hits,"rows":rows,
            "owner_import_status":"NOT_RUN","workspace_readback_status":"NOT_RUN",
            "natural_scheduler_status":"NATURAL_SLOT_UNVERIFIED",
            "independent_semantic_review":"NOT_RUN",**FLAGS})
