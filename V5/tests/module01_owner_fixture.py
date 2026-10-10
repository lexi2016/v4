"""Synthetic announcement inputs made by the pinned original V5 owner.

The provider-injection pattern is adapted from the fixed original fixture:
  commit 1a699a040c0b2cd467726bca5ccc7847182cb975
  V5/handoff/announcement-budget-red-20261009/tests/test_v5_private_owner.py
  Git blob d77163606682a83313487453aa599ed97bea1703

Only the transport response is synthetic. Catalog parsing, body persistence,
handoff registration, review binding, import, and subsequent consumer reads
use the target source capsules. No actual network or original Mac data is used.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]
SRC = BASE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TARGET = "20261009"
PUBLICATION = "2026-10-08"
SYNTHETIC_REASON = "SYNTHETIC_MODULE01_CONTRACT_FIXTURE_NOT_INVESTMENT_RESEARCH"
FIXTURE_SOURCE = {
    "commit": "1a699a040c0b2cd467726bca5ccc7847182cb975",
    "path": "V5/handoff/announcement-budget-red-20261009/tests/test_v5_private_owner.py",
    "git_blob_sha": "d77163606682a83313487453aa599ed97bea1703",
    "adapted_function": "V5PrivateOwnerTests.test_complete_catalog_and_all_21_bodies_share_one_budget",
    "target_commit": "f7cb731c384ee6890a87d16c19a5b5a621779477",
    "fixture_kind": "SYNTHETIC_ORIGINAL_OWNER_INPUTS",
    "real_392_reused": False,
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _worker(root: Path) -> dict:
    """Run original owner setup in a fresh process, keeping its imports local."""
    from v5_shadow.announcement_offline_reader import APP, sources, install_consumer_contract

    sources()
    sys.path.insert(0, str(APP))
    from ops.run_v5_private_announcement import PrivateOwner, SENTINEL_BASE
    from ops import run_manager_daily_announcement as daily
    from v4.manager_research import workspace_announcements as announcements
    from v4.manager_research.hkex_provider import HkexOfficialProvider
    from v4.manager_research.ports import SourceResponse
    from v4.manager_research.workspace_projection import digest
    from urllib.parse import parse_qs, urlencode, urlsplit
    from types import SimpleNamespace

    install_consumer_contract(announcements)

    def deny_network(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system"}:
            raise RuntimeError("MODULE01_SYNTHETIC_FIXTURE_NETWORK_FORBIDDEN")

    sys.addaudithook(deny_network)
    private_parent = root / "private"
    private_parent.mkdir()
    forbidden = root / "untouched"
    forbidden.mkdir()
    (forbidden / "sentinel").write_bytes(b"UNTOUCHED_SYNTHETIC_BOUNDARY\n")
    owner_root = private_parent / "owner"
    rows = [dict(art_code=f"AN202610080001{i:04d}", notice_date=PUBLICATION + " 00:00:00",
        display_time=PUBLICATION + " 12:00:00:000", title=f"Synthetic Module 01 notice {i}",
        codes=[dict(market_code="116", ann_type="H", stock_code=f"{i:05d}",
                    short_name=f"Synthetic Issuer {i}")]) for i in range(1, 5)]

    def transport(url, **kwargs):
        query = parse_qs(urlsplit(url).query)
        if urlsplit(url).path == "/api/security/ann":
            page = int(query["page_index"][0])
            data = dict(list=rows if page == 1 else [], page_index=page, page_size=20, total_hits=len(rows))
        elif urlsplit(url).path == "/api/content/ann":
            article = query["art_code"][0]
            row = next(row for row in rows if row["art_code"] == article)
            code = row["codes"][0]["stock_code"]
            data = dict(art_code=article, notice_title=row["title"], notice_date=row["notice_date"],
                notice_content=f"{SYNTHETIC_REASON}. Synthetic article {article}.", page_size=1,
                security=[dict(market_uni="116", stock=code)])
        else:
            raise AssertionError("UNEXPECTED_SYNTHETIC_PROVIDER_ROUTE:" + urlsplit(url).path)
        return SourceResponse(url=url, final_url=url, status_code=200,
            body=json.dumps({"success": 1, "data": data}).encode(),
            headers={"Content-Type": "application/json"}, retrieved_at="2026-10-09T00:00:00+00:00")

    def factory(**kwargs):
        return HkexOfficialProvider(transport=lambda *args, **kw: (_ for _ in ()).throw(
            AssertionError("UNEXPECTED_HKEX_TRANSPORT")), eastmoney_transport=transport, **kwargs)

    owner = PrivateOwner(owner_root, private_parent, [forbidden], provider_factory=factory,
                         initialize=True, capture_enabled=True)
    captured = owner.execute(["capture", "--target-date", TARGET, "--publication-date", PUBLICATION])
    if captured["status"] != "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS":
        raise AssertionError(captured)
    evidence = owner_root / "announcement_agent_runs" / captured["evidence_run_id"] / "evidence"
    catalog = owner.get_announcement_date_catalog(TARGET, PUBLICATION)
    semantic_path = owner_root / "synthetic_semantic_catalog.json"
    semantic = dict(schema="v4.announcement-semantic-catalog.v2", status="PASS_SYNTHETIC_TEST_ONLY",
        target_research_date=TARGET, target_notice_date=PUBLICATION, row_count=len(rows), records=[
            dict(art_code=row["art_code"], title=row["title"], issuer_codes=row["source_issuer_codes"],
                 security_scope="HK_EQUITY", factual_summary=SYNTHETIC_REASON,
                 classification="SYNTHETIC_TEST_ONLY")
            for row in catalog["catalog"]["manager_consumer_rows"]])
    _dump(semantic_path, semantic)
    terminal = announcements.validate_terminal_body_capture(evidence, catalog, TARGET, PUBLICATION,
        expected_run_id=captured["evidence_run_id"])
    build_args = SimpleNamespace(target_date=TARGET, publication_date=PUBLICATION,
        catalog_read=str(evidence / "catalog_read.json"), semantic_catalog=str(semantic_path),
        body_corpus=str(evidence / "body_corpus.json"), out=None, decisions=None, review_receipt=None)
    base = daily._build(build_args, reviewed=False, include_product=True,
                        terminal_body_capture=terminal)["product"]
    outcomes = [("SELECTED_EVENT", "OPERATING_EVENT"), ("CONDITIONAL_WATCH", "CONDITIONAL_WATCH"),
                ("NOT_SELECTED", "NOT_SELECTED"), ("NOT_ASSESSED", "NOT_ASSESSED")]
    decisions = [dict(art_code=row["art_code"], issuer_codes=[i["code"] for i in row["issuer_codes"]],
        security_scope=row["security_scope"], semantic_record_sha256=row["semantic_record_sha256"],
        body_record_sha256=row["body_record_sha256"], disposition=disposition,
        selection_basis=basis, reason=f"{SYNTHETIC_REASON}: {disposition}", risk_notes=["SYNTHETIC_ONLY"])
        for row, (disposition, basis) in zip(base["records"], outcomes, strict=True)]
    decisions_path = owner_root / "synthetic_decisions.json"
    _dump(decisions_path, {"article_decisions": decisions})
    reviewer_path = owner_root / "synthetic_reviewer.json"
    _dump(reviewer_path, dict(schema_version="v4.manager_research.announcement_agent_review.v1",
        review_conclusion="PASS", target_trade_date=TARGET, publication_date=PUBLICATION,
        evidence_run_id=captured["evidence_run_id"], decision_status="EXPLICIT_DISPOSITIONS",
        decision_payload_sha256=digest(decisions), reader_identity="synthetic-module01-reader",
        reviewer_identity="synthetic-module01-independent-reviewer", reviewed_at="2026-10-09T00:01:00+00:00",
        catalog_product_sha256=catalog["catalog"]["sha256"], semantic_catalog_sha256=_sha(semantic_path.read_bytes()),
        body_corpus_sha256=_sha((evidence / "body_corpus.json").read_bytes())))
    registered = owner.execute(["register-handoff", "--target-date", TARGET,
        "--publication-date", PUBLICATION, "--evidence-run-id", captured["evidence_run_id"],
        "--semantic-catalog", str(semantic_path), "--reviewer-output", str(reviewer_path),
        "--decisions", str(decisions_path), "--parent-task-id", "synthetic-module01-fixture",
        "--reader-identity", "synthetic-module01-reader",
        "--reviewer-identity", "synthetic-module01-independent-reviewer"])
    imported = owner.execute(["import", "--evidence-run-id", captured["evidence_run_id"]])
    owner_readback = owner.request(SENTINEL_BASE, "/api/v4/manager/research/announcements/analysis?" +
        urlencode({"date": TARGET, "publication_date": PUBLICATION}))
    consumption = announcements.read_analysis_consumption(owner, TARGET, PUBLICATION,
        cutoff=datetime.now(timezone.utc).isoformat(), analysis_readback=owner_readback)
    if consumption["status"] != "CONSUMED":
        raise AssertionError(consumption)
    # Root binding is declared once. Only bytes actually needed by the original
    # announcement readers are copied into the independent bound input roots.
    manager = root / "manager"
    manager.mkdir()
    for name in ("workspace_announcements", "workspace_announcement_runs", "announcement_agent_runs"):
        shutil.copytree(owner_root / name, manager / name)
    materials = root / "materials"
    shutil.copytree(owner_root / "materials", materials)
    source_bytes = {}
    for relative in ("ops/run_v5_private_announcement.py", "ops/run_manager_daily_announcement.py",
            "v4/manager_research/workspace_announcements.py", "v4/manager_research/announcement_analysis.py",
            "v4/manager_research/announcement_selection.py"):
        raw = (APP / relative).read_bytes()
        source_bytes[relative] = dict(sha256=_sha(raw), git_blob_sha=hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest())
    if (forbidden / "sentinel").read_bytes() != b"UNTOUCHED_SYNTHETIC_BOUNDARY\n":
        raise AssertionError("SYNTHETIC_BOUNDARY_CHANGED")
    sources()
    return dict(owner_readback=owner_readback, consumption=consumption, catalog=catalog,
        provenance=dict(FIXTURE_SOURCE, target_owner_files=source_bytes,
            capture_status=captured["status"], register_status=registered["status"], import_status=imported["status"],
            decisions={key: sum(d["disposition"] == key for d in decisions)
                       for key in ("SELECTED_EVENT", "SELECTED_PERFORMANCE", "CONDITIONAL_WATCH", "NOT_SELECTED", "NOT_ASSESSED")}))


def create_manager_fixture(root: Path) -> dict:
    """Create reusable synthetic owner inputs; return manager and bridge requests."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    child = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker", str(root)],
                           capture_output=True, text=True, timeout=120)
    if child.returncode:
        raise AssertionError("MODULE01_ORIGINAL_OWNER_FIXTURE_FAILED\n" + child.stdout + child.stderr)
    result = json.loads(child.stdout.splitlines()[-1])
    inputs = {}
    for name in ("manager", "materials", "us"):
        path = root / name
        path.mkdir(exist_ok=True)
        inputs[name] = dict(root=str(path), files={str(p.relative_to(path)): _sha(p.read_bytes())
                           for p in path.rglob("*") if p.is_file() and (name != "materials" or re.fullmatch(
                               r"(?:blobs/[0-9a-f]{64}|index/[0-9a-f]{64}\.json)", str(p.relative_to(path))))})
    output = root / "plans"
    output.mkdir()
    (output / ".v5-manager-plan-root").write_text("v5.manager-plan-root.v1\n")
    request = dict(target_date=TARGET, now=datetime.now(timezone.utc).isoformat(), action="refresh", view="dynamic",
        selection_date=None, announcement_date=None, inputs=inputs, rebound=None, manager_output_root=str(output))
    # The bridge's public binding intentionally admits a smaller input set.
    bridge_manager = {name: digest for name, digest in inputs["manager"]["files"].items()
        if name.startswith(("workspace_announcements/", "workspace_announcement_runs/")) or re.fullmatch(
            r"announcement_agent_runs/[0-9a-f]{32}/evidence/(?:[A-Za-z0-9_.-]+\.json|body_batch/bodies/AN[A-Z0-9]{8,32}\.json)", name)}
    bridge_request = dict(target_date=TARGET, publication_date=PUBLICATION, manager_root=inputs["manager"]["root"],
        materials_root=inputs["materials"]["root"], manager_files=bridge_manager, material_files=inputs["materials"]["files"])
    result.update(request=request, announcement_request=bridge_request)
    return result


def create_manager_dto(root: Path) -> dict:
    """Return the actual target run_manager_plan result and its synthetic inputs."""
    from v5_shadow.manager_plan import run_manager_plan
    fixture = create_manager_fixture(root)
    result = run_manager_plan(copy.deepcopy(fixture["request"]))
    return dict(fixture=fixture, result=result)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        print(json.dumps(_worker(Path(sys.argv[2])), ensure_ascii=False))
    else:
        raise SystemExit("Use create_manager_fixture(root) or create_manager_dto(root) from tests.")
