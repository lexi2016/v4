## Source excerpt: `v4/manager_workbench/us_mapping_catalog.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-continuation-api-20261017-r11c/app/v4/manager_workbench/us_mapping_catalog.py`

Original full-file SHA-256: `ec327cb99e72b9dd982f1238e459b79b657697501f02ac66a598752a94245031`

Release/worktree group: `api`

Catalog validator and loader pin the 667/1,003 recovery projection and status split.

### Full-source lines 19-55

```python

SCHEMA_VERSION = "v4.us_hk_mapping_catalog.v1"
SOURCE_PACKAGE_SHA256 = "dac3c820fcd6919fabdccc9c37ee9055b729b200fcde5e48f0dcf527de81bc6d"
MEMBERSHIP_SHA256 = "9b799c0b74ac5047f4e44a1b3dfd1dfa5ca9ce978fa3b8e7877913c423424c9c"
BASE_FILE_SHA256 = "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671"
OVERLAY_FILE_SHA256 = "d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69"
REVIEW_PACKAGE_SHA256 = "2894b3bca475965aa3553977a654b10fa4c6750bbcb80f70f1bea17bdde649b0"
REVIEW_MANIFEST_SHA256 = "8ba8ea7ef7c351bcd5a1b72ad8f449b7acf555a54a172ea66084248f28e26ab9"
PRIOR_220_OVERLAY_SHA256 = "72a0f074e6412036cd103c7f73ccf15230eb3d1633c09742c88653b863eba384"
RECOVERY_OVERLAY_NAME = "us_hk_667_recovery_overlay_20261016.json"
RECOVERY_OVERLAY_SHA256 = "3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c"
RECOVERY_MANIFEST_SHA256 = "6500e67d2d85e208b0f32c8c2ce5aeaf40298d8629f81ad414f050a29f913646"
RECOVERY_MEMBER_HASHES = {
    "CURRENT/01A_full_667_original_and_history_plus_v2.csv": "312423a9bc4036b24e393bb7ca14295c91997cb6dede3c2cb0fa334dffd6eb3c",
    "CURRENT/01B_full_1003_original_and_history_plus_v2.csv": "f27d4977a653ab981c12e5b5d523ee53f9777ff06410e66ef83608ca763184c5",
    "CURRENT/ACCEPTANCE_LEDGER.json": "98ae5272c2f5f81e6666d44464ce76f25d1ba73d3c4a1373097688a3c0d8577b",
    "CURRENT/A_URL_OCCURRENCES_UNATTEMPTED_62.csv": "07db9f282156f29cbfc6295280dec6a7cdc8c6660e5eb63e5ec8db38f0505173",
    "CURRENT/BASELINE_MANIFEST_REFERENCE.json": "966a329bfa143da1347475885d4b7d19f18feb76fda7cc763a7e562ed31af406",
    "CURRENT/EFFECTIVE_RESEARCH_1003.json": "43813adcdb39b81c45a827906f8a872af82bec1c11a0e2282153085d96a7b944",
    "CURRENT/FIELD_ASSESSMENTS_1003x7.csv": "f8d2985252d3a920f8cc52890a9e6bb720d68f242a07c7532ca5b43171525576",
    "CURRENT/METRICS.json": "a60ce260b7820a5e33fc335b26a2733c875311379bedc026b57d2bdc30609b0f",
    "CURRENT/NO_ORIGINAL_B_RELATIONS_18.csv": "b2500fe952951bbb45314b2ab270a8edf388cc4e67d87615c751e667f7dd3157",
    "CURRENT/OPEN_RELATIONS_221.csv": "811140d315c7701ef96a6be5db294afd962956bc9d2fbbaa826fbdbd20223030",
    "CURRENT/ORIGINAL_URL_ACCESS_ACCOUNTING.json": "c49b52a1899062b9ce70ef8a21d62beeb7656feb6441b751dcc32de0f9e69e2f",
    "CURRENT/RELATION_SUMMARY_1003.csv": "6e9dd2613ee6a6391c38f81651b7ee3f379b167b8d9545f86d840a89983fe345",
    "CURRENT/SIX_LAYERS_1003x6.csv": "596228bc4e37b5d69dab13c749930e131ce43f3ad26044d4c0dcfb8f988f38d0",
    "CURRENT/VERSION_PRECEDENCE.json": "ed3b1dbbee64683a187be53fb2a965608373768bd9617231ce4473a789ad0f95",
}
RECOVERY_STATUS_COUNTS = {
    "CLOSED_RESEARCH_SCOPE": 757,
    "CLOSED_EXCLUDED_SCOPE": 25,
    "OPEN": 221,
}
EXPECTED_REVIEWED_RELATION_COUNT = 700
RESEARCH_USES = {"PENDING_REVIEW", "CONDITIONAL_OBSERVATION", "BACKGROUND_HISTORICAL", "EXCLUDED_CURRENT"}
EXPECTED_STOCK_COUNT = 667
EXPECTED_RELATION_COUNT = 1003
_CODE_RE = re.compile(r"^[0-9]{5}$")

```

### Full-source lines 302-350

```python

def load_recovery_overlay(path: Path | str, catalog: Mapping[str, Any],
                          legacy_overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Load the complete v2r1 projection without merging it into legacy states."""
    try:
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != RECOVERY_OVERLAY_SHA256:
            raise CatalogValidationError("recovery overlay pinned SHA mismatch")
        value = json.loads(raw, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
        if (value.get("schema_version") != "v4.us_hk_mapping_recovery_overlay.v1" or
                value.get("integrity_sha256") != integrity_sha256(value) or
                value.get("base_catalog_sha256") != BASE_FILE_SHA256 or
                value.get("source_package_sha256") != "48f1124c10ed3440c22910a9125038748c08d673fc3ec543635cc9aae0b344d4" or
                value.get("source_manifest_sha256") != RECOVERY_MANIFEST_SHA256 or
                value.get("source_manifest_member_count") != 3637 or
                {key: item.get("sha256") for key, item in value.get("source_member_hashes", {}).items()} != RECOVERY_MEMBER_HASHES):
            raise CatalogValidationError("recovery overlay source identity is invalid")

        old_records = legacy_overlay.get("records", [])
        old_ids = [record.get("relation_id") for record in old_records]
        prior = value.get("prior_700_history")
        if (not isinstance(prior, dict) or prior.get("sha256") != OVERLAY_FILE_SHA256 or
                prior.get("record_count") != EXPECTED_REVIEWED_RELATION_COUNT or
                prior.get("relation_ids") != old_ids or
                prior.get("retained_as_separate_history") is not True or
                prior.get("status_crosswalk") != "NOT_ESTABLISHED"):
            raise CatalogValidationError("separate legacy 700 history binding is invalid")

        if value.get("counts") != {
            "snapshot_stocks": 667,
            "original_relations": 1003,
            "processed_relations": 1003,
            "closure_status_counts": RECOVERY_STATUS_COUNTS,
            "research_scope_closed": 757,
            "excluded_scope_closed": 25,
            "closed_total_including_exclusions": 782,
            "open_relations": 221,
            "stocks_with_relations": 649,
            "stocks_without_relations": 18,
            "company_independent_acceptance": 0,
        }:
            raise CatalogValidationError("recovery closure count contract is invalid")
        if value.get("research_safety") != {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "fact_validation": "INDEPENDENT_ACCEPTANCE_0",
            "prediction_validation": "UNTESTED",
            "historical_PIT": "NOT_VALIDATED",

```

### Full-source lines 466-488

```python

    def search(self, catalog_path: Path | str, overlay_path: Path | str, query=None, **kwargs):
        with self._lock:
            try:
                paths = [Path(catalog_path), Path(overlay_path)]
                recovery_path = paths[1].with_name(RECOVERY_OVERLAY_NAME)
                paths.append(recovery_path)
                signature = tuple((str(p.resolve()), s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                                  for p in paths for s in [p.stat()])
                if signature != self._signature:
                    self._signature = self._catalog = self._overlay = self._recovery_overlay = None
                    if hashlib.sha256(paths[0].read_bytes()).hexdigest() != BASE_FILE_SHA256:
                        raise CatalogValidationError("catalog pinned SHA mismatch")
                    catalog = load_catalog(paths[0])
                    overlay = load_review_overlay(paths[1], catalog)
                    recovery_overlay = load_recovery_overlay(paths[2], catalog, overlay)
                    # Reject a concurrent writer rather than cache mixed file versions.
                    after = tuple((str(p.resolve()), s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                                  for p in paths for s in [p.stat()])
                    if signature != after:
                        raise CatalogValidationError("catalog changed while loading")
                    self._catalog, self._overlay, self._recovery_overlay, self._signature = catalog, overlay, recovery_overlay, signature
                return _search_validated(self._catalog, query, overlay=self._overlay,
                                         recovery_overlay=self._recovery_overlay, **kwargs)

```
