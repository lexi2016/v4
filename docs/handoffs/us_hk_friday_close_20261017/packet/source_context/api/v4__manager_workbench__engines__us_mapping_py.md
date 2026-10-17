## Source excerpt: `v4/manager_workbench/engines/us_mapping.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-continuation-api-20261017-r11c/app/v4/manager_workbench/engines/us_mapping.py`

Original full-file SHA-256: `e2242b8e18b7f67edcd7aad07aeca805c14214d99924ad1cb374c623e1ad345f`

Release/worktree group: `api`

Current selector requires its existing verified universe and REVIEWED relation semantics; PROPOSED/PIT_UNCONFIRMED remain observation-only.

### Full-source lines 54-100

```python

def run_us_mapping(context, batch):
    u = context["scope_refs"].get("US_MAPPING") or {}
    configured = u.get("configured_symbols")
    session = u.get("source_session")
    source_session = context["source_sessions"].get("US") or context["source_sessions"].get("us")
    gaps = []
    declared_version = u.get("universe_version")
    universe_contract = u.get("universe_contract")
    universe_version = declared_version
    expected_symbols = None
    if universe_contract is not None:
        try:
            universe_contract = validate_us_universe_contract(universe_contract)
            universe_version = universe_contract["version"]
            if (declared_version not in (None, universe_version)
                    or u.get("universe_contract_sha256") not in (None, universe_contract["contract_sha256"])):
                gaps.append("US_UNIVERSE_CONTRACT_IDENTITY_MISMATCH")
            else:
                expected_symbols = universe_contract["symbols"]
        except (TypeError, ValueError):
            gaps.append("US_UNIVERSE_CONTRACT_INVALID")
    elif declared_version in (None, LEGACY_UNIVERSE_VERSION, "LEGACY_US_UNIVERSE_V1"):
        legacy_contract = build_legacy_us_universe_contract()
        if configured == legacy_contract["symbols"]:
            universe_version = declared_version or "LEGACY_US_UNIVERSE_V1"
            expected_symbols = legacy_contract["symbols"]
        else:
            gaps.append("US_LEGACY_FIXED_33_SCOPE_INVALID")
    elif declared_version == UNIVERSE_VERSION:
        gaps.append("US_UNIVERSE_CONTRACT_MISSING")
    else:
        gaps.append("US_UNIVERSE_CONTRACT_VERSION_UNSUPPORTED")
    expected_count = len(expected_symbols) if expected_symbols is not None else 0
    legacy_gap = universe_version in (LEGACY_UNIVERSE_VERSION, "LEGACY_US_UNIVERSE_V1")
    good_universe = (expected_symbols is not None and isinstance(configured, list)
        and configured == expected_symbols and len(configured) == len(set(configured))
        and len(configured) == expected_count and all(isinstance(x, str) and x for x in configured)
        and u.get("verification") == "VERIFIED"
        and valid_sha(u.get("sha256"))
        and u.get("universe_ref")==batch.get("universe_ref") and session == source_session
        and isinstance(session, str) and u.get("calendar_verified") is True)
    if not good_universe:
        gaps.append("US_UNIVERSE_CONTRACT_OR_SESSION_NOT_VERIFIED")
    found = [item.get("us_symbol") for item in batch["records"] if isinstance(item, dict)]
    if good_universe and (len(found) != expected_count or len(found) != len(configured) or set(found) != set(configured)):
        gaps.append("US_SOURCE_33_COVERAGE_INCOMPLETE" if legacy_gap else "US_SOURCE_UNIVERSE_COVERAGE_INCOMPLETE")
    rows = []

```

### Full-source lines 101-182

```python

    for index, item in enumerate(batch["records"]):
        if not isinstance(item, dict):
            rows.append(row({}, "UNASSESSED", "US_RECORD_INVALID", source_index=index));continue
        source_ok = (good_universe and item.get("us_symbol") in configured and
            item.get("source_session") == session and item.get("owner") and
            valid_sha(item.get("source_sha256")) and
            current(context, item.get("available_at")))
        relations = item.get("relations")
        if not isinstance(relations, list) or not relations:
            # No relationship is never an implicit HK winner.
            assessments=[a for a in item.get("reviewed_assessments",[]) if isinstance(a,dict)
                and reviewed_diagnostic(context,item,a)] if source_ok else []
            proxies=[p for p in item.get('proxy_metadata',[]) if isinstance(p,dict) and p.get('mapping_type') in ('etf_proxy','etf_basket_proxy')
                and p.get('source_sha256')==item.get('source_sha256') and p.get('owner')==item.get('owner')
                and current(context,p.get('available_at'))] if source_ok else []
            quote_missing_reason=item.get("quote_missing_reason")
            unmapped_disposition=item.get("unmapped_disposition")
            reason=(quote_missing_reason or ("US_RELATION_UNMAPPED_CANNOT_CONFIRM" if unmapped_disposition
                else 'US_REVIEWED_ASSESSMENT_WITH_GAPS' if assessments else 'US_ETF_THEME_PROXY_ONLY' if proxies else 'US_REVIEWED_RELATION_ABSENT'))
            observation_conditions=(['OBSERVATION_ONLY','NOT_STRICT_SELECTION']
                if quote_missing_reason or unmapped_disposition else [])
            no_relation_gaps=list(item.get("source_gaps", [])) if isinstance(item.get("source_gaps"), list) else []
            if unmapped_disposition:
                no_relation_gaps.append(unmapped_disposition.get("reason", "US_RELATION_UNMAPPED_CANNOT_CONFIRM"))
            rows.append(dict(row(item, "UNASSESSED", reason, source_index=index,
                                 us_symbol=item.get("us_symbol"), relation_type=None,quote=item.get('quote'),
                                 quote_missing_reason=quote_missing_reason,source_gaps=no_relation_gaps,
                                 unmapped_disposition=unmapped_disposition,conditions=observation_conditions,
                                 diagnostic_gaps=no_relation_gaps,reviewed_assessments=assessments,proxy_metadata=proxies,
                                 absence_scope='CHECKED_FROZEN_REVIEWED_RELATIONS_AND_SEED_ONLY'), symbol=None))
            continue
        for relation in relations:
            priority=relation.get("research_priority",item.get("source_status")) if isinstance(relation,dict) else None
            change=positive_change(item) if item.get("positive_change_required") else True
            base = dict(item, symbol=relation.get("target_symbol") if isinstance(relation, dict) else None,
                        name=relation.get("target_name") if isinstance(relation, dict) else None,
                        membership=relation.get("membership") if isinstance(relation, dict) else None,
                        evidence_ids=(item.get("evidence_ids") or []) + (relation.get("evidence_ids") or [] if isinstance(relation, dict) else []))
            extra = dict(source_index=index, us_symbol=item.get("us_symbol"),
                         relation_type=relation.get("relation_type") if isinstance(relation, dict) else None,
                         source_status=priority, publication_time_gaps=relation.get("publication_time_gaps",[]) if isinstance(relation,dict) else [], research_basis=relation.get("research_basis") if isinstance(relation,dict) else None, relation_source_refs=relation.get("relation_source_refs",[]) if isinstance(relation,dict) else [], relation_limitations=relation.get("relation_limitations",[]) if isinstance(relation,dict) else [],quote=item.get("quote"), relation_status=relation.get("status") if isinstance(relation, dict) else None,
                         relation_pit_status=relation.get("pit_status") if isinstance(relation,dict) else None,quote_missing_reason=item.get("quote_missing_reason"),
                         source_gaps=item.get("source_gaps",[]),unmapped_disposition=item.get("unmapped_disposition"))
            if isinstance(relation,dict) and relation.get('priority_assessment'):
                extra.update(research_priority_reason=relation.get('research_priority_reason'),
                             priority_assessment=relation['priority_assessment'])
            quote_missing_reason=item.get("quote_missing_reason")
            if isinstance(quote_missing_reason, str) and quote_missing_reason.startswith("QUOTE_SYMBOL_MISSING:"):
                conditions=["OBSERVATION_ONLY", "NOT_STRICT_SELECTION"]
                if isinstance(relation,dict) and relation.get("pit_status") == "PIT_UNCONFIRMED":
                    conditions.append("PIT_UNCONFIRMED")
                diagnostic_gaps=list(item.get("source_gaps", [])) if isinstance(item.get("source_gaps"), list) else []
                if isinstance(relation,dict) and relation.get("pit_status") == "PIT_UNCONFIRMED":
                    diagnostic_gaps.append("US_RELATION_PROPOSED_PIT_UNCONFIRMED")
                rows.append(row(base, "UNASSESSED", quote_missing_reason, conditions=conditions,
                    diagnostic_gaps=diagnostic_gaps, **extra))
                continue
            if isinstance(relation, dict) and (
                relation.get("status") == "PROPOSED"
                or relation.get("pit_status") == "PIT_UNCONFIRMED"
            ):
                rows.append(row(base, "UNASSESSED", "US_RELATION_PROPOSED_PIT_UNCONFIRMED",
                    conditions=["OBSERVATION_ONLY", "NOT_STRICT_SELECTION"], **extra))
                continue
            relation_ok=(source_ok and isinstance(relation, dict) and hk_symbol(relation.get("target_symbol")) and
                    relation.get("status") == "REVIEWED" and valid_sha(relation.get("sha256")) and
                    relation.get("review_owner") and current(context, relation.get("available_at")) and
                    publication_before_cutoff(context, relation) and relation.get("relation_type"))
            eligible=membership(base,context)
            if not (relation_ok and priority in ("PRIORITY","WATCH","NONE") and change is not None and eligible is True):
                blockers=[]
                if relation_ok and priority not in ('PRIORITY','WATCH','NONE'):blockers.append('AUDITED_RESEARCH_PRIORITY_UNAVAILABLE')
                if eligible is False:blockers.append('TARGET_NOT_IN_CURRENT_CONNECT_MEMBERSHIP')
                reason='US_RELATION_PRIORITY_NOT_REVIEWED' if relation_ok and priority not in ('PRIORITY','WATCH','NONE') else 'US_SESSION_RELATION_OR_CONNECT_UNVERIFIED'
                rows.append(row(base, "UNASSESSED", reason,diagnostic_gaps=blockers, **extra))
            elif change is False:
                rows.append(row(base,"NOT_SELECTED","US_SOURCE_CHANGE_NOT_POSITIVE",**extra))
            elif priority == "NONE":
                rows.append(row(base, "NOT_SELECTED", "US_ORIGINAL_SOURCE_NOT_PRIORITY_OR_WATCH", **extra))
            else:
                rows.append(row(base, "CONDITIONAL_WATCH", "US_REVIEWED_RELATION_CONDITIONAL_ONLY",
                    conditions=["RELATION_NOT_A_STRICT_SELECTION_RULE"], **extra))

```
