FROZEN_STAGE_IDS: tuple[str, ...] = (
    "STAGE_0925",
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
    "STAGE_0945_1030",
    "STAGE_1300_1315",
    "STAGE_1445_1500",
    "STAGE_1545_1555",
)

STAGE_CONTRACT_VERSION = "v3_5.eight_stage_contract.v1"

STAGE_MARKET_SCOPES: dict[str, tuple[str, ...]] = {
    stage_id: (("HK",) if stage_id == "STAGE_1545_1555" else ("A", "HK"))
    for stage_id in FROZEN_STAGE_IDS
}

STAGE_DEFINITIONS: dict[str, dict[str, str]] = {
    "STAGE_0925": {"label": "09:20/09:25竞价参考", "window": "09:20-09:25", "start": "09:20:00", "cutoff": "09:25:05"},
    "STAGE_0930_0935": {"label": "09:30-09:35", "window": "09:30-09:35", "start": "09:30:00", "cutoff": "09:35:05"},
    "STAGE_0935_0940": {"label": "09:35-09:40", "window": "09:35-09:40", "start": "09:35:00", "cutoff": "09:40:05"},
    "STAGE_0940_0945": {"label": "09:40-09:45", "window": "09:40-09:45", "start": "09:40:00", "cutoff": "09:45:05"},
    "STAGE_0945_1030": {"label": "09:45-10:30", "window": "09:45-10:30", "start": "09:45:00", "cutoff": "10:30:00"},
    "STAGE_1300_1315": {"label": "13:00-13:15", "window": "13:00-13:15", "start": "13:00:00", "cutoff": "13:15:00"},
    "STAGE_1445_1500": {"label": "14:45-15:00", "window": "14:45-15:00", "start": "14:45:00", "cutoff": "15:00:00"},
    "STAGE_1545_1555": {"label": "15:45-15:55港股", "window": "15:45-15:55", "start": "15:45:00", "cutoff": "15:55:00"},
}

# V3 stage_materializer.py uses the minute bars after each labelled boundary.
STAGE_BAR_WINDOWS: dict[str, tuple[str, str, int]] = {
    "STAGE_0930_0935": ("09:31:00", "09:35:00", 5),
    "STAGE_0935_0940": ("09:36:00", "09:40:00", 5),
    "STAGE_0940_0945": ("09:41:00", "09:45:00", 5),
    "STAGE_0945_1030": ("09:46:00", "10:30:00", 45),
    "STAGE_1300_1315": ("13:01:00", "13:15:00", 15),
    "STAGE_1445_1500": ("14:46:00", "15:00:00", 15),
}

if tuple(STAGE_DEFINITIONS) != FROZEN_STAGE_IDS:
    raise RuntimeError("stage definitions must preserve the frozen chronological sequence")
