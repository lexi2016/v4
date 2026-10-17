# Catalog versus actual API consumer evidence

The frozen recovery catalog and overlay identify 667 Hong Kong stocks and 1,003 unique US↔HK relations. The selector's API catalog path can validate and display that overlay, but that alone does not prove that the active `NativeAdapters.us_mapping` consumer receives it.

For loaded API release `announcement-continuation-api-20261017-r11c`, the read-only reviewer reported the dynamic `us_mapping` projection contains 37 distinct relation identities: 10 evidence-backed relation identities (matching the 10 reviewed pairs), 5 reviewed seed relations, and 22 registry relations marked `PROPOSED` / `PIT_UNCONFIRMED`. The sets have no duplicate relation identities. That is 37 consumer relations, not the catalog's 1,003 and not the earlier fixed 32. This count is reported from the reviewer/controller inspection; this packet does not include or reproduce the raw relation rows.

Source excerpts, with original full-file and copied-excerpt SHA-256 values, are linked from `../SOURCE_MANIFEST.json` and `../source_context/README.md`:

- `v4/manager_workbench/inputs/native.py`: dynamic binding setup and the actual `NativeAdapters.us_mapping` call path.
- `v4/manager_workbench/inputs/source_bindings.py`: relation evidence/review/seed/proposal projection.
- `v4/manager_workbench/us_mapping_catalog.py`: separate 667/1,003 catalog validator/loader.

The repair must assert the actual consumer's loaded identities and relation count against the frozen overlay, not merely the catalog endpoint or visible UI. It must preserve each row's source, status, use scope, evidence and PIT fields. Do not promote the 757 `CLOSED_RESEARCH_SCOPE` rows to `REVIEWED` or PIT-safe; `OPEN` and `CLOSED_EXCLUDED_SCOPE` must remain non-selectable.

`real_relation_projection.json` now packages all 667 stock identities and 1,003 relation identities as a field-preserving, quote-free derived fixture. Each projected relation field matches the frozen mapping input, with status counts 757 `CLOSED_RESEARCH_SCOPE`, 221 `OPEN`, and 25 `CLOSED_EXCLUDED_SCOPE`. The fixture is not an owner artifact and is not the full 43,652,024-byte recovery overlay; it enables source-level consumer tests but does not establish actual loaded API/runtime consumption.

`CANNOT_CONFIRM`: no runtime consumer readback receipt for the canonical full overlay is present. The 37-count finding is a source inspection, and the packaged relation projection is a derived fixture; neither is proof of a natural selector run or UI/API acceptance.
