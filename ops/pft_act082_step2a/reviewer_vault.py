"""Publish separate review units from an already sealed, private DEV frame."""

from argparse import ArgumentParser
from concurrent.futures import ProcessPoolExecutor
from csv import DictReader
from hashlib import sha256
from pathlib import Path
import json
from math import isfinite
import re
from time import monotonic
from uuid import UUID

from .evidence import PROTOCOL, QUALITY_TIER, canonical_json
from .pipeline import FRAME_NAME, DEV_POOL_NAME, QFQ, VAULT_A, VAULT_B, require_prepared_source
from .render import PANELS, draw_panel, environment, png_chunks
from .schema import FORM
from .sources import STEP1_SHA, STEP2_SHA, digest
from .vault import require_private_directory, write_new

REVIEW_UNITS = {"formal", "pilot", "channel_a_relabel"}
PNG_NAMES = {f"{name}.png" for name in PANELS}
REVIEW_FILES = PNG_NAMES | {"EVIDENCE.json"}
PRIVATE_TOKENS = re.compile(
    r"(?<![0-9])[0-9]{6}\.(?:SH|SZ|BJ|XSHG|XSHE|XBSE)\b"
    r"|(?<![0-9])(?:19|20)[0-9]{2}[-/][01][0-9][-/][0-3][0-9](?![0-9])"
    r"|(?:label_(?:start|end)|t(?:2|5|10|20)[_+]?(?:net|return)|mae5|max_drawdown_t20_close|standard_tail|auxiliary_tail"
    r"|security_id|company_name|bucket_eligibility|selection_rule|exec_cooldown_isolated"
    r"|first_blind_id|relabel_blind_id|mother_start_date)[\"\s:]",
    re.IGNORECASE,
)
ROOT_JSON_FILES = {"V1_1_BLANK_FORM.json", "RUN_MANIFEST_TEMPLATE.json", "ANONYMOUS_AUDIT_SUMMARY.json"}
SERIES_NUMERIC = {"o", "h", "l", "c", "v", "W", "Y", "K", "D_signal", "J"}
WEEK_DURATION = {"elapsed", "scheduled", "suspended", "missing", "invalid", "observed"}
OBSERVATION_KEYS = {
    "daily_wide", "daily_focus", "weekly", "wide_left_sessions", "root_relative_positions",
    "left_context", "weekly_context", "market_context", "price_scale", "volume_scale", "brick_reference",
}


def _uuid(token):
    try:
        uid = UUID(token)
    except ValueError as exc:
        raise ValueError("invalid anonymous identifier") from exc
    if uid.version != 4 or str(uid) != token:
        raise ValueError("noncanonical UUIDv4 on review channel")


def _scan_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("reviewer JSON must be a plain file")
    text = path.read_text(encoding="utf-8")
    if PRIVATE_TOKENS.search(text):
        raise ValueError("private/future field or identity appears in reviewer file")
    return json.loads(text)


def _numeric(value):
    return value is None or (type(value) in (int, float) and isfinite(value))


def _observations_allowed(evidence):
    if set(evidence) != OBSERVATION_KEYS:
        raise ValueError("unapproved anonymous observation keys")
    expected = {
        "price_scale": "D_CLOSE_100", "volume_scale": "ACTUAL_VOLUME_IN_COMMON_RELATIVE_UNITS",
        "brick_reference": "UNVERIFIED_CLASSROOM_VERSION_REFERENCE_ONLY", "market_context": "UNKNOWN",
    }
    if any(evidence[k] != val for k, val in expected.items()):
        raise ValueError("unapproved anonymous observation value")
    if evidence["wide_left_sessions"] not in (120, 240):
        raise ValueError("unapproved chart span")
    if any(evidence[key] not in ("AVAILABLE", "UNKNOWN") for key in ("left_context", "weekly_context")):
        raise ValueError("unapproved evidence sufficiency")
    if any(not ((type(value) is int and -240 <= value <= 0) or value == "UNKNOWN")
           for value in evidence["root_relative_positions"]):
        raise ValueError("nonrelative anchor location")
    for key in ("daily_wide", "daily_focus"):
        rows = evidence[key]
        if [row["i"] for row in rows] != list(range(1 - len(rows), 1)):
            raise ValueError("nonrelative day axis")
        if not rows or len(rows) > (36 if key == "daily_focus" else evidence["wide_left_sessions"] + 1):
            raise ValueError("invalid chart degree")
        for row in rows:
            if set(row) != SERIES_NUMERIC | {"i"} or not all(_numeric(row[column]) for column in SERIES_NUMERIC):
                raise ValueError("non-anonymous numeric series")
    week_keys = SERIES_NUMERIC | WEEK_DURATION | {"partial", "week_status", "mean_v_per_elapsed_exchange_day"}
    if len(evidence["weekly"]) > 52:
        raise ValueError("too many relative weeks")
    for row in evidence["weekly"]:
        if not (
            set(row) == week_keys and all(_numeric(row[column]) for column in SERIES_NUMERIC)
            and _numeric(row["mean_v_per_elapsed_exchange_day"]) and type(row["partial"]) is bool
            and row["week_status"] in ("PARTIAL", "CLOSED_GAPPED", "CLOSED")
            and all(type(row[column]) is int and 0 <= row[column] <= 7 for column in WEEK_DURATION)
            and row["elapsed"] == row["observed"] + row["suspended"] + row["missing"] + row["invalid"]
            and row["partial"] == (row["elapsed"] < row["scheduled"])
        ):
            raise ValueError("unapproved weekly series")


def validate_review_channel(root, *, locked_archive=False):
    seen = set()
    total_png = 0
    roots = {p.name for p in root.iterdir()}
    allowed = REVIEW_UNITS | ROOT_JSON_FILES | {"CHANNEL_A_RELABEL.aesgcm", "RELABEL_ROSTER.json"}
    if roots - allowed:
        raise ValueError("unexpected public review path")
    if locked_archive and "channel_a_relabel" in roots:
        raise ValueError("raw channel A relabel materials cannot accompany first-pass review")
    for phase in REVIEW_UNITS & roots:
        unit = root / phase
        if unit.is_symlink() or not unit.is_dir():
            raise ValueError("review unit must be a plain directory")
        roster = _scan_json(unit / "ROSTER.json")
        if set(roster) != {"review_items"}:
            raise ValueError("unapproved review roster structure")
        phase_ids = set()
        for item in roster["review_items"]:
            if set(item) != {"blind_id", "batch"}:
                raise ValueError("private fields in reviewer roster")
            ident = item["blind_id"]
            _uuid(ident)
            if ident in seen:
                raise ValueError("blind ID collision across review contexts")
            seen.add(ident)
            phase_ids.add(ident)
            folder = unit / ident
            if folder.is_symlink() or not folder.is_dir() or {p.name for p in folder.iterdir()} != REVIEW_FILES:
                raise ValueError("noncanonical reviewer panel members")
            evidence = _scan_json(folder / "EVIDENCE.json")
            if set(evidence) != {"blind_id", "observations"} or evidence["blind_id"] != ident:
                raise ValueError("reviewer evidence schema/identity mismatch")
            _observations_allowed(evidence["observations"])
            for png in sorted(folder.glob("*.png")):
                if png.is_symlink():
                    raise ValueError("unsafe review image")
                png_chunks(png.read_bytes())
                total_png += 1
        if {x.name for x in unit.iterdir()} != phase_ids | {"ROSTER.json"}:
            raise ValueError("unexpected review unit file")
    for name in ROOT_JSON_FILES & roots:
        _scan_json(root / name)
    return {"review_groups": len(seen), "png_count": total_png, "identity_leaks": 0, "future_data_leaks": 0}


def _panels(job):
    payload = job["evidence"]
    base = canonical_json(payload)
    # Independently instantiate the pre-cutoff/perturbed equivalent payload. The DEV
    # stage first proved complete canonical numeric equality on the raw bar variants.
    replay = json.loads(base)
    second = json.loads(base)
    images = {}
    for panel in PANELS:
        png = draw_panel(payload, panel)
        if png != draw_panel(replay, panel) or png != draw_panel(second, panel):
            raise ValueError("canonical PNG differs for equal numeric evidence")
        images[panel] = png
    return job, images


def _write_job(unit, ident, payload, images):
    _uuid(ident)
    group = require_private_directory(unit / ident)
    write_new(group / "EVIDENCE.json", canonical_json({"blind_id": ident, "observations": payload}))
    for name, data in images.items():
        write_new(group / f"{name}.png", data)


def render_dev(root, *, workers=14):
    started = monotonic()
    private = root / VAULT_B
    lock = json.loads((private / "PRE_RENDER_LOCK.json").read_bytes())
    live_source = require_prepared_source(lock)
    if digest(private / QFQ) != lock["qfq_basis_sha256"]:
        raise ValueError("QFQ basis lock changed before rendering")
    audit = json.loads((root / "DEV_PREPARATION_RECEIPT.json").read_bytes())
    if digest(private / FRAME_NAME) != lock["sha256"] or audit["sampling_frame_sha256"] != lock["sha256"]:
        raise ValueError("sampling frame lock verification failed prior to renderer")
    if audit["numeric_prefix_differences"] or audit["numeric_perturbation_differences"]:
        raise ValueError("raw-bar invariance gate failed prior to renderer")
    job_path = root / DEV_POOL_NAME / "NUMERIC_RENDER_JOB.jsonl"
    if digest(job_path) != audit["numeric_render_job_sha256"]:
        raise ValueError("numerical evidence changed after physical lock")
    with (private / "PREREGISTERED_RELABEL_JOIN.csv").open() as f:
        relabels = list(DictReader(f))
    if digest(private / "PREREGISTERED_RELABEL_JOIN.csv") != lock["direct_join_sha256"]:
        raise ValueError("relabel mapping changed after preregistration")
    aliases = {row["first_blind_id"]: row["relabel_blind_id"] for row in relabels}
    if len(aliases) != 40 or len(set(aliases.values())) != 40:
        raise ValueError("relabel design cardinality")
    public = require_private_directory(root / VAULT_A)
    relabel_root = require_private_directory(root / "PRIVATE_RELABEL_REVIEW")
    delivery = {
        "formal": require_private_directory(public / "formal"),
        "pilot": require_private_directory(public / "pilot"),
        "channel_a_relabel": require_private_directory(relabel_root / "channel_a_relabel"),
    }
    rosters = {phase: [] for phase in delivery}
    png_digest_binding = sha256()
    with job_path.open() as jobs, ProcessPoolExecutor(max_workers=workers) as pool:
        for job, images in pool.map(_panels, map(json.loads, jobs), chunksize=2):
            phase = job["phase"]
            ident = job["blind_id"]
            _write_job(delivery[phase], ident, job["evidence"], images)
            rosters[phase].append({"blind_id": ident, "batch": job["batch"]})
            if ident in aliases:
                _write_job(delivery["channel_a_relabel"], aliases[ident], job["evidence"], images)
            for _, png in sorted(images.items()):
                png_digest_binding.update(sha256(png).digest())
    rosters["channel_a_relabel"] = [{"blind_id": row["relabel_blind_id"], "batch": 1} for row in relabels]
    if {p: len(rows) for p, rows in rosters.items()} != {"formal": 240, "pilot": 20, "channel_a_relabel": 40}:
        raise ValueError("review group cardinalities disagree with preregistration")
    for phase, entries in rosters.items():
        write_new(delivery[phase] / "ROSTER.json", canonical_json({"review_items": entries}))
    write_new(public / "V1_1_BLANK_FORM.json", canonical_json(FORM))
    write_new(public / "RUN_MANIFEST_TEMPLATE.json", canonical_json({
        "protocol_id": PROTOCOL, "quality_tier": QUALITY_TIER,
        "reference_schema_sha256": STEP1_SHA, "reference_protocol_sha256": STEP2_SHA,
        "channel_A_model_version": None, "channel_B_model_version": None, "temperature": None,
        "generation_params": None, "review_prompt_sha256": None,
        "same_evidence_snapshot_both_channels": True, "independent_clean_contexts": True,
        "external_browse_rights": False, "review_form_sent": False, "fit": 0,
    }))
    original = validate_review_channel(public, locked_archive=True)
    retest = validate_review_channel(relabel_root)
    receipt = {
        **environment(), **original, "private_channel_A_relabel_groups": retest["review_groups"],
        "private_channel_A_relabel_png_count": retest["png_count"],
        "batch_numeric_prefix_differences": 0, "batch_numeric_perturbation_differences": 0,
        "batch_canonical_png_differences": 0, "candidate_png_hash_chain": png_digest_binding.hexdigest(),
        "input_lock_sha256": lock["sha256"], "qfq_data_version_sha256": audit["vol2_sha256"],
        "verified_prepared_source_sha256": live_source, "qfq_basis_sha256": lock["qfq_basis_sha256"],
        "PIT": "CANNOT_CONFIRM", "workers": workers, "wall_seconds": round(monotonic() - started, 6),
        "unqualified_release": False,
    }
    require_prepared_source(lock)
    write_new(public / "ANONYMOUS_AUDIT_SUMMARY.json", canonical_json(receipt))
    validate_review_channel(public, locked_archive=True)
    write_new(root / "DEV_RENDER_RECEIPT.json", canonical_json(receipt))
    return receipt


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=14)
    args = parser.parse_args()
    print(json.dumps(render_dev(args.root, workers=args.workers), ensure_ascii=False))


if __name__ == "__main__":
    main()

