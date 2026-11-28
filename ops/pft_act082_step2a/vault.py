"""Vault permissions, authenticated envelopes and append-only access accounting."""

from collections import Counter
from hashlib import sha256
import fcntl
import json
from math import isfinite, log
import os
from pathlib import Path
from random import Random
from secrets import token_bytes
import stat
from statistics import median
from uuid import uuid4

from .calendar import DEV_END, SEAL_START
from .evidence import canonical_json
from .sampling import SEED
from .waves import JUNDA

AES_MAGIC = b"ACT082-A256GCM\x01"
SEALED_MAIN = 40
SEALED_PRESSURE = 10


def require_private_directory(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o700 or st.st_uid != os.getuid():
        raise PermissionError("vault directory must be directly owned and private")
    return path


def write_new(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _audit_rows(data):
    prev = "0" * 64
    rows = []
    for line in data.splitlines():
        row = json.loads(line)
        digest = row.pop("record_sha256")
        if row["previous_record_sha256"] != prev or digest != sha256(canonical_json(row)).hexdigest():
            raise ValueError("broken access-audit hash chain")
        rows.append(row)
        prev = digest
    return rows, prev


def append_audit(path, action, payload_sha):
    from datetime import datetime, timezone

    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "r+b") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        st = os.fstat(f.fileno())
        if stat.S_IMODE(st.st_mode) != 0o600 or st.st_uid != os.getuid():
            raise PermissionError("audit file not private")
        if not getattr(st, "st_flags", 0) & stat.UF_APPEND:
            os.chflags(path, getattr(st, "st_flags", 0) | stat.UF_APPEND, follow_symlinks=False)
        rows, last = _audit_rows(f.read())
        row = {
            "sequence": len(rows) + 1, "utc": datetime.now(timezone.utc).isoformat(),
            "action": action, "payload_sha256": payload_sha, "previous_record_sha256": last,
        }
        row["record_sha256"] = sha256(canonical_json(row)).hexdigest()
        f.write(canonical_json(row))
        f.flush()
        os.fsync(f.fileno())
    return row["record_sha256"]


def audit_access(path):
    path = Path(path)
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o600 or not st.st_flags & stat.UF_APPEND:
        raise PermissionError("access ledger must be a private OS-append-only file")
    rows, last = _audit_rows(path.read_bytes())
    if not rows or any(row["action"] != "SEALED_WITHOUT_OPEN" for row in rows):
        raise ValueError("opened, unsupported, or empty SEALED audit")
    return {"audit_records": len(rows), "audit_end_sha256": last, "OOT_OPEN_COUNT": 0}


def write_envelope(plaintext, destination, key_path, purpose):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    destination, key_path = map(Path, (destination, key_path))
    key_parent = require_private_directory(key_path.parent).resolve(strict=True)
    data_parent = require_private_directory(destination.parent).resolve(strict=True)
    if key_parent == data_parent or key_parent in data_parent.parents or data_parent in key_parent.parents:
        raise PermissionError("key custody must be independent of ciphertext directory")
    if destination.exists() or key_path.exists():
        raise FileExistsError("immutable key or ciphertext already exists")
    key = token_bytes(32)
    nonce = token_bytes(12)
    aad = AES_MAGIC + purpose.encode("ascii")
    ciphertext = AES_MAGIC + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)
    write_new(key_path, key)
    write_new(destination, ciphertext)
    return {
        "cipher": "AES-256-GCM", "ciphertext_sha256": sha256(ciphertext).hexdigest(),
        "ciphertext_bytes": len(ciphertext), "key_sha256_fingerprint": sha256(key).hexdigest(),
        "key_path": str(key_path.resolve(strict=True)),
    }


def _profile(row):
    if row["asof"] > DEV_END:
        raise ValueError("postcutoff row reached SEALED selector")
    try:
        cap, volatility = float(row["market_cap"]), float(row["volatility"])
    except (TypeError, ValueError) as e:
        raise ValueError("invalid frozen size/volatility stratum") from e
    if not all(isfinite(x) and x > 0 for x in (cap, volatility)) or not row["industry"]:
        raise ValueError("incomplete frozen industry/size/volatility stratum")
    return row["industry"], log(cap), log(volatility)


def select_sealed(profiles, dev_profiles, exposure, *, seed=SEED):
    """40 matched pre-cut profiles plus 10 heterogeneous cases. No outcome arguments."""
    if len(dev_profiles) != 40 or JUNDA not in exposure:
        raise ValueError("DEV stratum or exposure universe incomplete")
    if not {row["security_id"] for row in dev_profiles} <= exposure:
        raise ValueError("all DEV instruments must be in the exclusion universe")
    dev = [_profile(row) for row in dev_profiles]
    for row in profiles:
        if row["asof"] > DEV_END:
            raise ValueError("postcutoff profile in frozen inventory")
    eligible = {row["security_id"]: _profile(row) for row in profiles if row["security_id"] not in exposure}
    if len(eligible) != sum(row["security_id"] not in exposure for row in profiles) or len(eligible) < 50:
        raise ValueError("insufficient or duplicate eligible securities")
    rng = Random(seed)
    ordered = sorted(eligible)
    rng.shuffle(ordered)
    tie = {stock: rank for rank, stock in enumerate(ordered)}
    scales = [max(1e-9, median(abs(row[i] - median(v[i] for v in dev)) for row in dev)) for i in (1, 2)]
    domain = Counter(row[0] for row in dev)
    main = []
    for target in dev:
        def score(stock):
            profile = eligible[stock]
            return (profile[0] != target[0], sum(
                abs(profile[i] - target[i]) / scales[i - 1] for i in (1, 2)
            ), tie[stock])
        stock = min(eligible, key=score)
        main.append(stock)
        del eligible[stock]
    pressure = []
    pressure_industries = Counter()
    for _ in range(SEALED_PRESSURE):
        def pressure_score(stock):
            industry, cap, vol = eligible[stock]
            return (pressure_industries[industry], domain[industry], -min(
                abs(cap - old_cap) / scales[0] + abs(vol - old_vol) / scales[1]
                for _, old_cap, old_vol in dev
            ), tie[stock])
        stock = min(eligible, key=pressure_score)
        pressure_industries[eligible.pop(stock)[0]] += 1
        pressure.append(stock)
    universe = [*main, *pressure]
    if len(main) != SEALED_MAIN or len(set(universe)) != SEALED_MAIN + SEALED_PRESSURE or set(universe) & exposure:
        raise AssertionError("SEALED population isolation failed")
    return {
        "evaluation_min_D": SEAL_START, "profile_max_D": DEV_END, "intersection_count": 0,
        "rows": [{"security_id": stock, "opaque_id": str(uuid4()),
                  "stratum": "MAIN" if rank < SEALED_MAIN else "HETEROGENEOUS"}
                 for rank, stock in enumerate(universe)],
    }


def seal_mapping(mapping, cipher_dir, key_path):
    target = require_private_directory(cipher_dir)
    if any(path.suffix.lower() == ".png" for path in target.rglob("*")):
        raise ValueError("SEALED cannot receive renders")
    result = write_envelope(
        canonical_json(mapping), target / "SEALED_OOT_V2_MAPPING.aesgcm", key_path, "SEALED_OOT_V2",
    )
    log_path = target / "ACCESS_AUDIT.jsonl"
    append_audit(log_path, "SEALED_WITHOUT_OPEN", result["ciphertext_sha256"])
    if set(target.iterdir()) != {target / "SEALED_OOT_V2_MAPPING.aesgcm", log_path}:
        raise ValueError("unexpected SEALED directory members")
    return {**result, **audit_access(log_path), "sealed_png_count": 0}


def require_sealed_provenance(receipt):
    """Guard before touching a real SEALED selection, ciphertext, or key directory."""
    if not (
        receipt.get("exposure_complete") is True and receipt.get("official_calendar_verified") is True
        and receipt.get("frozen_all_a_qfq_verified") is True
        and receipt.get("precut_stratification_provenance_verified") is True
        and receipt.get("first_valid_stratum_source_date") is not None
        and receipt["first_valid_stratum_source_date"] <= DEV_END
        and receipt.get("all_candidate_strata_max_source_date") is not None
        and receipt["all_candidate_strata_max_source_date"] <= DEV_END
        and int(receipt.get("proven_precut_dev_profile_count", 0)) == 40
        and int(receipt.get("proven_precut_eligible_full_a_count", 0)) >= 50
    ):
        raise ValueError("SEALED_BLOCKED_BY_INCOMPLETE_VERIFIED_PRECUT_STRATA_OR_EXPOSURE")


def encrypt_directory(source, destination, key_path, purpose, *, extra=None):
    """Form an authenticated private envelope in memory, without a plaintext export ZIP."""
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    source = require_private_directory(source)
    out = BytesIO()
    names = set()
    with ZipFile(out, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError("vault source may not contain symlinks")
            if path.is_file():
                if stat.S_IMODE(path.stat().st_mode) != 0o600:
                    raise PermissionError("vault member is not private")
                name = path.relative_to(source).as_posix()
                names.add(name)
                archive.writestr(name, path.read_bytes())
        for name, data in (extra or {}).items():
            if name in names or Path(name).name != name:
                raise ValueError("invalid supplemental private vault member")
            archive.writestr(name, data)
            names.add(name)
        if not names:
            raise ValueError("empty authenticated vault")
    details = write_envelope(out.getvalue(), destination, key_path, purpose)
    return {"encrypted_file_count": len(names), **details}

