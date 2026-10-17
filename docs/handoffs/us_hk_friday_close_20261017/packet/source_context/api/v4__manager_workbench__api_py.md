## Source excerpt: `v4/manager_workbench/api.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-continuation-api-20261017-r11c/app/v4/manager_workbench/api.py`

Original full-file SHA-256: `138e67441bf3eb8d15b378c645317f415fe5568ba7144bdad21bf8568bfb38c8`

Release/worktree group: `api`

API mapping-catalog route and configured catalog/overlay paths.

### Full-source lines 24-30

```python

from .us_mapping_catalog import CatalogValidationError, CatalogStore

PREFIX = "/api/v4/manager-workbench"
_US_MAPPING_CATALOG_STORE = CatalogStore()
US_MAPPING_REVIEW_OVERLAY_PATH = Path(__file__).resolve().parent / "research_data" / "us_hk_667_review_overlay_20261015.json"
US_MAPPING_CATALOG_PATH = Path(__file__).resolve().parent / "research_data" / "us_hk_667_catalog_20261015.json"


```

### Full-source lines 156-171

```python

    @router.get("/mapping-catalog")
    def read_us_hk_mapping_catalog(
        q: str | None = Query(None, max_length=128),
        research_use: str | None = Query(None, pattern="^(PENDING_REVIEW|CONDITIONAL_OBSERVATION|BACKGROUND_HISTORICAL|EXCLUDED_CURRENT)$"),
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=200),
    ):
        def read():
            try:
                data = _US_MAPPING_CATALOG_STORE.search(
                    US_MAPPING_CATALOG_PATH, US_MAPPING_REVIEW_OVERLAY_PATH, q,
                    offset=offset, limit=limit, research_use=research_use)
            except CatalogValidationError as exc:
                raise HTTPException(503, "US_HK_MAPPING_CATALOG_INVALID") from exc
            return envelope("STRUCTURE_VALID", data, [
                "SOURCE_FACTS_NOT_INDEPENDENTLY_VERIFIED",

```
