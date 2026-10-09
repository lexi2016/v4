# Independent current-read registry observation candidate

Base: `074a65e100fb675581607ac033ffa861929d9afc`.
Backend only; original manager capsule, formal security master, saved plan, relation/PIT admission and UI unchanged.

Optional manager request key `registry_observation`:
```json
{"root":"/absolute/private/registry","files":{"names.csv":"<raw file SHA256>"},"source_date":"20261008","source_label":"<actual source label>","format":"CSV_CODE_NAME"}
```
This is an explicit candidate contract, not a claim about the unavailable real 10/8 file. UTF-8 CSV requires canonical five-digit `code`, nonempty `name`, unique code. Additional columns do not grant identity or acquisition evidence; A/H pairing remains unbound. Empty/invalid input is a named independent gap. Source date remains DECLARED, never OWNER_VERIFIED. Original acquisition timestamps remain null. The raw file SHA and complete sorted code/name-set digest bind the observation. A panel or 695 rows never implies full-market coverage.

Only previously verified archive-reader records are projected, through the original archive projector. Matching uses the original alias selection, ambiguity handling and subject semantic assessment. Source material IDs, original article rows, reference SHAs, publication/acquisition times, propositions and original rejection reasons are retained. No formal discovery identity is forged. All observations remain CANNOT_CONFIRM / formal_eligible=false / fresh_catalyst_eligible=false. Current observation times belong only to the separate receipt. The source raw file and private copied file are re-read and hash checked before returning; the receipt records real start/end times. The field is appended only after saved-plan independent readback.

Cloud validation: AST parse and git diff whitespace checks only. Product tests NOT_RUN here. Mac independent command from repository root:
```bash
PYTHONPATH=V5/src:V5/tests python3 -m unittest test_registry_observation.RegistryObservationTests -v
```
Nine synthetic cases: minimal columns; SHA tamper; invalid/duplicate code; actual manager noninterference + receipt; isolated invalid source; root overlap; missing A/H pair original rejection + unchanged old/null clocks; duplicate-name ambiguity; positive subject proposition without formal eligibility.

Remaining: real source format/date/acquisition evidence contract must be supplied before real-file binding. No real 1735-material run, deployment or production action performed.
