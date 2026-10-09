"""Read-time code/name clues; never a security master or a PIT admission."""
import copy
import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from v5_shadow.contracts import exact_keys, trade_date
from v5_shadow.digests import sha256_json


def clock():
    return datetime.now(timezone.utc).isoformat()


def decode(raw, binding):
    """Explicit CSV candidate contract; source date is declared, not proven."""
    exact_keys(binding, ('root', 'files', 'source_date', 'source_label', 'format'))
    trade_date(binding['source_date'])
    if binding['format'] != 'CSV_CODE_NAME' or not isinstance(binding['source_label'], str) or not binding['source_label'].strip():
        raise ValueError('REGISTRY_FORMAT_OR_SOURCE')
    if len(binding['files']) != 1 or hashlib.sha256(raw).hexdigest() != next(iter(binding['files'].values())):
        raise ValueError('REGISTRY_RAW_SHA')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or not {'code', 'name'} <= set(reader.fieldnames):
        raise ValueError('REGISTRY_CODE_NAME_COLUMNS')
    rows = {}
    for row in reader:
        code, name = row.get('code'), row.get('name')
        if None in row or not isinstance(code, str) or not re.fullmatch(r'[0-9]{5}', code) or not isinstance(name, str) or not name.strip() or code in rows:
            raise ValueError('REGISTRY_CODE_NAME_ROW')
        # No market-cap/share prerequisites; no inferred A/H pairing.
        rows[code] = dict(code=code, name=name.strip())
    if not rows:
        raise ValueError('REGISTRY_EMPTY')
    return rows


def project(rows, binding, archive_readback, started_at):
    from v4.manager_research import workspace_discovery as discovery
    from v4.manager_research.workspace_semantics import assess, prose_sources
    from v4.manager_research.existing_materials import project_archive
    names = {code: row['name'] for code, row in rows.items()}
    aliases = {}
    for code, name in names.items():
        for alias in {name, discovery._issuer_alias(name)}:
            if len(alias) >= 2 and alias != code:
                aliases.setdefault(alias.casefold(), set()).add(code)
    probes = discovery._discovery_alias_probes(aliases)
    patterns = discovery._subject_name_patterns(names)
    materials, gaps = [], ['REGISTRY_NOT_NATIVE_SECURITY_MASTER', 'REGISTRY_SOURCE_DATE_DECLARED_NOT_OWNER_VERIFIED',
                           'RELATION_AND_PIT_NOT_ADMITTED', 'A_H_PAIRING_NOT_BOUND']
    if archive_readback is None:
        gaps.append('ARCHIVE_READER_NOT_BOUND')
    else:
        for key, record in sorted(archive_readback['records'].items()):
            if 'error' in record:
                gaps.append('ARCHIVE_READ_REJECTED:' + key + ':' + str(record['error']))
                continue
            projected, missing = project_archive(record['payload'], record['binding'], record['payload']['archive_date'])
            materials.extend(projected); gaps.extend(missing)
    ambiguous = {alias: sorted(codes) for alias, codes in aliases.items() if len(codes) > 1}
    if ambiguous:
        gaps.append('REGISTRY_AMBIGUOUS_ALIASES_EXCLUDED')
    if archive_readback is not None:
        for key, record in sorted(archive_readback.get('slots', {}).items()):
            if 'error' in record:
                gaps.append('ARCHIVE_SLOT_READ_REJECTED:' + key + ':' + str(record['error']))
    clues = []
    for material in materials:
        body = '\n'.join(text for _, text in prose_sources(material))
        folded = (material['title'] + '\n' + body).casefold()
        possible = discovery._possible_discovery_aliases(folded, probes)
        matches = discovery._select_alias_matches(folded, possible)
        body_names = discovery._body_subject_names(body, patterns)
        for code in sorted({match[3] for match in matches}):
            result = assess(material, names[code], code, names=body_names, identity_row=rows[code])
            clues.append(dict(symbol=code, name=names[code], material=copy.deepcopy(material),
                              propositions=result['propositions'], rejected=result['rejected'],
                              formal_eligible=False, fresh_catalyst_eligible=False))
    return dict(schema_version='v5.registry_observation.v1', status='CANNOT_CONFIRM',
        scope='INDEPENDENT_CURRENT_READ_NOT_SAVED_PLAN_OR_FORMAL_SELECTION',
        registry=dict(source_label=binding['source_label'], source_date=binding['source_date'],
            supplied_file_sha256=copy.deepcopy(binding['files']), code_name_set_sha256=sha256_json(sorted(names.items())),
            row_count=len(rows), ambiguous_aliases=ambiguous, coverage_basis='BOUND_CODE_NAME_SET_NOT_FULL_MARKET',
            original_retrieved_at=None, original_available_at=None),
        read_receipt=dict(observed_started_at=started_at, observed_finished_at=clock(),
                          before_after_raw_sha256_stable=False),
        material_count=len(materials), clues=clues, reason_codes=sorted(set(gaps)),
        formal_eligible=False, fresh_catalyst_eligible=False, natural_verified=False)
