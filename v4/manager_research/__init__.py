"""Independent, date keyed manager research backfill.

The package owns only research jobs and their evidence receipts.  It receives
the exact stage observations and the source provider through ports so it does
not import or write any V3/V3.5 producer state.
"""

from .contracts import (
    CUTOFF_LOCAL_TIME,
    FOUR_FLAGS,
    JOB_SCHEMA_VERSION,
    PRODUCT_SCHEMA_VERSION,
    TARGET_STAGE_ID,
    ContractError,
    normalise_observation_input,
)
from .hkex_provider import HkexOfficialProvider
from .material_transport import MaterialTransport
from .materials import MaterialStore
from .service import ManagerResearchJobService
from .store import ManagerResearchStore

__all__ = [
    "CUTOFF_LOCAL_TIME",
    "FOUR_FLAGS",
    "JOB_SCHEMA_VERSION",
    "PRODUCT_SCHEMA_VERSION",
    "TARGET_STAGE_ID",
    "ContractError",
    "HkexOfficialProvider",
    "ManagerResearchJobService",
    "ManagerResearchStore",
    "MaterialStore",
    "MaterialTransport",
    "normalise_observation_input",
]
