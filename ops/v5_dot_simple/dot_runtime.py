"""Pin the original V5 runtime and bind observations to the actual China session."""
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import importlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

from dot_state import atomic, digest, mkdir, read_pin, require, sync_dir

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "dot_manifest.json").read_bytes())
BJT = ZoneInfo("Asia/Shanghai")
SLOTS = {"close": ("16:20", "16:50"), "evening": ("18:30",)}


def today():
    return datetime.now(BJT)


def parse_day(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9]{8}", value), "BUSINESS_DATE")
    return date.fromisoformat(value)


def admit_slot(phase, now):
    require(now.utcoffset() is not None, "CLOCK_WITHOUT_OFFSET")
    local = now.astimezone(BJT)
    for slot in SLOTS[phase]:
        start = datetime.fromisoformat(local.date().isoformat() + "T" + slot).replace(tzinfo=BJT)
        if start <= local < start + timedelta(minutes=5):
            return slot, start + timedelta(minutes=5)
    raise ValueError("OUTSIDE_DOT_" + phase.upper() + "_WINDOW")


def load_runtime(intake, state):
    raw = read_pin(intake, CONFIG["release"])
    map_raw = read_pin(intake, CONFIG["asset_map"])
    map_data = json.loads(map_raw)
    require(map_data["asset_count"] == 92 and map_data["denominator"] == 21, "FROZEN_MAP_SCOPE")
    release = state / ("release-" + CONFIG["release"]["sha256"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            require(path.parts and not path.is_absolute() and ".." not in path.parts
                    and str(path) == entry.filename and chr(92) not in entry.filename
                    and not stat.S_ISLNK(entry.external_attr >> 16) and not entry.flag_bits & 1,
                    "FROZEN_ARCHIVE_PATH")
        require(sum(entry.file_size for entry in entries) <= 64_000_000, "FROZEN_ARCHIVE_BOUNDS")
        manifest = archive.read("MANIFEST_SHA256.json")
        require(digest(manifest) == CONFIG["frozen_manifest_sha256"], "FROZEN_MANIFEST_SHA")
        pins = json.loads(manifest)["files"]
        names = {"MANIFEST_SHA256.json", *pins}
        require(len(entries) == len(names) == 114 and set(archive.namelist()) == names, "FROZEN_SCOPE")
        members = {name: archive.read(name) for name in names}
    require(all(len(members[name]) == ref["bytes"] and digest(members[name]) == ref["sha256"]
                for name, ref in pins.items()), "FROZEN_MEMBER_PIN")
    vendors = {name: pin["sha256"] for name, pin in pins.items() if name.startswith("vendor/")}
    require(len(vendors) == 32, "VENDOR_SCOPE")
    if not release.exists():
        with tempfile.TemporaryDirectory(prefix="release-stage-", dir=state) as temporary:
            path = Path(temporary) / "release"
            path.mkdir()
            for name, member in members.items():
                target = path / name
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic(target, member)
            os.rename(path, release)
            sync_dir(state)
    require(release.resolve() == release and release.is_dir()
            and {p.relative_to(release).as_posix() for p in release.rglob("*") if not p.is_dir()} == names,
            "FROZEN_RELEASE_PATHS")
    for name, member in members.items():
        require(read_pin(release, {"path": name, "bytes": len(member), "sha256": digest(member)}) == member,
                "FROZEN_MATERIALIZED_MEMBER")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(release))
    modules = {}
    for name in ("main", "sources", "top200", "evening", "w10_board", "driveio", "par", "wave11c_calendar"):
        module = importlib.import_module(name)
        require(Path(module.__file__) == release / (name + ".py"), "FROZEN_MODULE_SCOPE")
        modules[name] = module
    require(modules["main"].MAP_SHA == CONFIG["asset_map"]["sha256"], "ORIGINAL_MAP_PIN")
    require(modules["driveio"].PARENT == CONFIG["parent"], "ORIGINAL_DRIVE_PARENT")
    return SimpleNamespace(**modules, map_raw=map_raw, proof={
        "manifest_files": len(pins), "vendor_files": len(vendors), "vendor_sha256": vendors,
        "archive_sha256": CONFIG["release"]["sha256"],
        "manifest_sha256": CONFIG["frozen_manifest_sha256"],
    })


def market_day(value, runtime, intake):
    """An annual addition is an official notice plus its reviewed URL and SHA pin."""
    day = parse_day(value)
    used = {}

    def closures(year):
        if str(year) in used:
            return used[str(year)]["closures"]
        pin = CONFIG["calendar"].get(str(year))
        root = HERE
        if pin is None:
            root = intake / "calendars"
            pin_path = root / f"SZSE_{year}.json"
            require(pin_path.is_file() and not pin_path.is_symlink(), f"SZSE_CALENDAR_UNAVAILABLE:{year}")
            pin = json.loads(pin_path.read_bytes())
            require(pin["schema"] == "V5_DOT_SZSE_ANNUAL_V1" and type(pin["year"]) is int and pin["year"] == year
                    and pin["path"] == f"SZSE_{year}.html" and type(pin["bytes"]) is int
                    and 0 < pin["bytes"] <= 512 * 1024
                    and re.fullmatch(r"https://www\.szse\.cn/disclosure/notice/t[0-9]{8}_[0-9]+\.html", pin["url"]),
                    "SZSE_CALENDAR_PIN")
        closed = runtime.wave11c_calendar.cn_days(read_pin(root, pin), year)
        used[str(year)] = {"url": pin["url"], "sha256": pin["sha256"], "closures": closed}
        return closed

    def open_day(candidate):
        closed = closures(candidate.year)
        return candidate.weekday() < 5 and candidate not in closed

    require(open_day(day), "SSE_SZSE_CLOSED_SESSION")
    previous = day - timedelta(days=1)
    while not open_day(previous):
        previous -= timedelta(days=1)
    return previous.strftime("%Y%m%d"), {
        year: {k: val[k] for k in ("url", "sha256")} | {"closure_dates": len(val["closures"])}
        for year, val in used.items()
    }


def stage_observation(root, day, kind, runtime, ref, raw):
    sources = runtime.sources
    pin = sources.immutable(root, f"{kind}_{day}_{digest(raw)}.zip", raw)
    pinned = {**ref, **pin}
    sources.inspect(root, day, kind, pinned)
    return pinned


def stage_g4(root, day, runtime, ref, raw):
    return stage_observation(root, day, "G4", runtime, ref, raw)


def capture_source(root, day, kind, runtime, deadline, *, clock=today, opener=None):
    """Capture official bytes in a scheduled slot, or the true session during backfill."""
    source = runtime.sources
    require(kind in source.LIMIT, "SOURCE_KIND")
    start = clock()
    require(start.utcoffset() is not None, "CLOCK_WITHOUT_OFFSET")
    start = start.astimezone(BJT)
    require(parse_day(day) == start.date(), "SOURCE_CAPTURE_CLOCK")
    if deadline is None:
        source.admit_clock(start.isoformat(), day, kind)
    else:
        _, allowed_until = admit_slot("close", start)
        require(deadline == allowed_until, "SOURCE_CAPTURE_CLOCK")
    url = source.RAWSOURCE.format(date=day) if kind == "G4" else source.GBBQ
    open_url = opener or urllib.request.build_opener(source.NoRedirect()).open
    query = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    try:
        with open_url(query, timeout=20) as response:
            require(response.geturl() == url and response.status == 200, kind + "_HTTP_IDENTITY")
            raw = response.read(source.LIMIT[kind] + 1)
            observed = clock()
            require(observed.utcoffset() is not None, "CLOCK_WITHOUT_OFFSET")
            observed = observed.astimezone(BJT)
            require(start <= observed and observed.date() == start.date()
                    and (deadline is None or observed < deadline), kind + "_OBSERVED_SLOT")
            modified = response.headers.get("Last-Modified")
    except (urllib.error.URLError, TimeoutError):
        raise ValueError("WAITING_INPUT_" + kind) from None
    require(0 < len(raw) <= source.LIMIT[kind], kind + "_SOURCE_SIZE")
    source.zip_check(raw, day, kind)
    ref = {
        "url": url, "http_status": 200, "observed_at": observed.isoformat(),
        "last_modified": modified,
    }
    if kind == "RIGHTS":
        ref["rights_snapshot_finality"] = "OBSERVED_NOT_FINAL"
    return stage_observation(root, day, kind, runtime, ref, raw)


def capture_g4(root, day, runtime, deadline, *, clock=today, opener=None):
    return capture_source(root, day, "G4", runtime, deadline, clock=clock, opener=opener)


def backfill_source(cache, stage, root, day, kind, runtime, clock):
    """Reuse a verified original observation or capture a new one on the actual day."""
    source = runtime.sources
    cache_receipt = cache / f"{kind}_RECEIPT.json"
    key = {"G4": "g4", "RIGHTS": "gbbq"}[kind]
    staged_receipt = stage / "SAME_DAY_SOURCE_RECEIPT.json"
    now = clock()
    require(now.utcoffset() is not None, "CLOCK_WITHOUT_OFFSET")
    same_day = now.astimezone(BJT).date() == parse_day(day)
    if cache_receipt.exists() or cache_receipt.is_symlink():
        ref_path = cache_receipt
    elif staged_receipt.exists() or staged_receipt.is_symlink():
        ref_path = staged_receipt
    else:
        ref_path = None
    if ref_path is not None:
        require(ref_path.resolve() == ref_path and ref_path.is_file()
                and ref_path.stat().st_size <= 16384, kind + "_BACKFILL_RECEIPT_PATH")
        receipt = json.loads(ref_path.read_bytes())
        require(receipt.get("business_date") == day, kind + "_BACKFILL_RECEIPT_DATE")
        ref = receipt.get(key)
        if ref_path == staged_receipt and same_day and key not in receipt:
            ref_path = None
    if ref_path is None:
        require(same_day, "WAITING_INPUT_" + kind)
        ref = capture_source(cache, day, kind, runtime, None, clock=clock)
        raw = source.read_pin(cache, ref, kind)
    else:
        require(isinstance(ref, dict), "WAITING_INPUT_" + kind)
        observed = source.admit_clock(ref.get("observed_at"), day, kind)
        require(observed <= now, kind + "_FUTURE_OBSERVATION")
        if kind == "RIGHTS":
            require(ref.get("rights_snapshot_finality") == "OBSERVED_NOT_FINAL", "RIGHTS_BACKFILL_FINALITY")
        source.inspect(ref_path.parent, day, kind, ref)
        raw = source.read_pin(ref_path.parent, ref, kind)
    if ref_path == staged_receipt:
        ref = stage_observation(cache, day, kind, runtime, ref, raw)
    if ref_path != cache_receipt:
        source.immutable(cache, cache_receipt.name, source.json_bytes({"business_date": day, key: ref}))
    return stage_observation(root, day, kind, runtime, ref, raw)
