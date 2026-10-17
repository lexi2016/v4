## Source excerpt: `v4/manager_workbench/inputs/source_bindings.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-continuation-api-20261017-r11c/app/v4/manager_workbench/inputs/source_bindings.py`

Original full-file SHA-256: `3dd4e2d19aa26672851d58e4810da0afd7b054c20c7d3d6a8019cf77e8da8b51`

Release/worktree group: `api`

Exact target-date/session artifact binding and actual relation projection from evidence/review/seed/proposal sources.

### Full-source lines 499-535

```python

def us_mapping(config, context):
    session = context.source_sessions['us']
    root = config.us_root

    manifest, msha = read(root, 'research/peripherals/manifest.json')
    # The owner artifact is keyed by research trade date, while its quote rows
    # identify the preceding US session. Prefer the exact target-date artifact;
    # retain the old session-date layout only when the target artifact is absent.
    artifact_date = context.target_date
    quote_rel = f'research/peripherals/{artifact_date}/external_finance.json'
    try:
        SafeRoot(root).read_bytes(quote_rel)
    except FileNotFoundError:
        artifact_date = session
        quote_rel = f'research/peripherals/{artifact_date}/external_finance.json'
    expected_quote_sha = manifest.get(quote_rel)
    if not valid_sha(expected_quote_sha):
        raise ValueError('US_OWNER_ARTIFACT_MANIFEST_BINDING_INVALID')
    payload, qsha = read(root, quote_rel, expected_quote_sha)

    receipt_rel = f'receipts/research/peripherals/{artifact_date}/external_finance.json'
    receipt, rsha = read(root, receipt_rel)

    snapshot = payload.get('market_snapshot', {})
    checked_time(snapshot.get('captured_at'), context.cutoff)

    receipt_payload_sha = receipt.get('artifact_sha256') or receipt.get('payload_sha256')
    if (
        snapshot.get('capture_session_date') != session
        or receipt.get('trade_date') != artifact_date
        or receipt.get('source') != 'external_finance'
        or receipt.get('payload_path') != quote_rel
        or receipt_payload_sha != qsha
        or (artifact_date == context.target_date
            and receipt.get('us_session_date') != session)
    ):
        raise ValueError('US_OWNER_RECEIPT_ARTIFACT_SESSION_INVALID')

```

### Full-source lines 555-719

```python

    # Keep the frozen reviewed evidence and its independent receipt intact.
    evidence, esha = read(config.relation_root, config.relation_evidence_relative)
    review, vsha = read(config.relation_root, config.relation_review_relative)
    # Candidate business links are a separate, versioned proposal registry.
    # Their source dates and PIT availability remain explicitly unknown.
    registry_root = Path(__file__).resolve().parents[1] / "data"
    registry_relative = "us_mapping_business_relations_20261014_v3.json"
    registry_source, registry_sha = read(registry_root, registry_relative)
    if (registry_source.get("status") != "PROPOSED"
            or registry_source.get("pit_status") != "PIT_UNCONFIRMED"
            or registry_source.get("strict_selection_eligible") is not False
            or registry_source.get("decision_use") != "OBSERVATION_ONLY"):
        raise ValueError("US_RELATION_PROPOSAL_SAFETY_INVALID")
    registry = normalize_relation_registry(registry_source)

    registry_contract_version = registry.get("contract_version")
    if (registry_contract_version not in {universe_contract["version"], UNIVERSE_VERSION}
            or (universe_contract["version"] == UNIVERSE_VERSION
                and registry_contract_version != UNIVERSE_VERSION)):
        raise ValueError("US_RELATION_UNIVERSE_CONTRACT_MISMATCH")

    if not isinstance(
        registry.get("relations"),
        list,
    ):
        raise ValueError(
            "US_RELATION_REGISTRY_INVALID"
        )

    registry_relations = registry["relations"]

    review_sha = vsha
    checked_time(review.get("reviewed_at"), context.cutoff)
    if (review.get('status')!='PASS' or review.get('evidence_file_sha256')!=esha
        or review.get('declared_artifact_sha256')!=evidence.get('artifact_sha256')
        or owner_digest({k:v for k,v in evidence.items() if k!='artifact_sha256'})!=evidence.get('artifact_sha256')
        or review.get('recomputed_artifact_sha256')!=evidence.get('artifact_sha256') or not review.get('reviewer_identity')
        or review.get('safety',{}).get('production_allowed') is not False):
        raise ValueError('US_RELATION_INDEPENDENT_REVIEW_INVALID')
    reviewed_pairs = (
        review.get("reviewed_pairs", [])
        if isinstance(review, dict)
        else []
    )

    pairs = {
        tuple(
            r.get(k)
            for k in (
                "us_symbol",
                "hk_symbol",
                "relationship_type",
                "direction",
            )
        )
        for r in reviewed_pairs
        if isinstance(r, dict)
    }
    inherited_sources=priority_review(config,evidence,review)
    assessments=[]
    reviewed_assessments={a['us_symbol']:a for a in review.get('reviewed_symbol_assessments',[])}
    if len(reviewed_assessments)!=len(review.get('reviewed_symbol_assessments',[])):
        raise ValueError('US_ASSESSMENT_REVIEW_IDENTITY_INVALID')
    seen_assessments=set()
    for assessment in evidence.get('symbol_assessments',[]):
        us=assessment.get('us_symbol');audited=reviewed_assessments.get(us)
        if (us not in US_SYMBOLS or us in seen_assessments or not audited
                or owner_digest(assessment)!=audited.get('assessment_sha256')
                or any(assessment.get(k)!=audited.get(k) for k in ('status','conclusion','candidate_hk_code'))
                or assessment.get('status')!='ASSESSED_WITH_GAPS' or assessment.get('conclusion')!='CANNOT_CONFIRM'
                or assessment.get('candidate_hk_symbol')!='HK.'+str(assessment.get('candidate_hk_code'))):
            raise ValueError('US_ASSESSMENT_REVIEW_IDENTITY_INVALID')
        checked_time(assessment.get('available_at'),review['reviewed_at'])
        seen_assessments.add(us)
        assessments.append(dict(original=assessment,assessment_sha256=audited['assessment_sha256'],
            verification='REVIEWED',review_owner=review['reviewer_identity'],available_at=review['reviewed_at'],
            source_refs=[dict(relative=rel,sha256=sha,owner=review['reviewer_identity'],available_at=review['reviewed_at'])
                for rel,sha in [(config.relation_evidence_relative,esha),(config.relation_review_relative,vsha)]]))
    if seen_assessments!=set(reviewed_assessments):raise ValueError('US_ASSESSMENT_REVIEW_IDENTITY_INVALID')
    cards=[]
    for card in evidence.get('relations',evidence.get('cards',[])):
        if tuple(card.get(k) for k in ('us_symbol','hk_symbol','relationship_type','direction')) not in pairs:
            raise ValueError('US_RELATION_PAIR_NOT_REVIEWED')
        checked_time(card.get('available_at'),review['reviewed_at'])
        cards.append({**card,'relation_source_refs':[dict(relative=config.relation_evidence_relative,sha256=esha,owner=review['reviewer_identity'],available_at=review['reviewed_at'])],'evidence_review_status':'REVIEWED','reviewer_identity':review['reviewer_identity'],
            'available_at':review['reviewed_at'],'review_receipt_sha256':vsha})
    seed_cards, seed_sources = reviewed_seed(config,context)
    joined={}
    for card in [*cards,*seed_cards]:
        key=tuple(card.get(k) for k in ('us_symbol','hk_symbol','relationship_type','direction'))
        if key not in joined:joined[key]=card
        else:
            # Retain both independently bound sources without duplicate decisions.
            original=joined[key]
            original['relation_source_refs']=[*original.get('relation_source_refs',[]),*card.get('relation_source_refs',[])]
            original['reviewed_variants']=[*original.get('reviewed_variants',[]),card]
    proposal_cards = []
    registry_universe_symbols = set(build_us_universe_contract()["symbols"])
    for relation in registry_relations:
        us = relation.get("us_symbol")
        hk = relation.get("hk_symbol")
        if (us not in registry_universe_symbols or not isinstance(hk, str) or not hk.startswith("HK.")
                or relation.get("status") != "PROPOSED"
                or relation.get("pit_status") != "PIT_UNCONFIRMED"):
            raise ValueError("US_RELATION_PROPOSAL_IDENTITY_INVALID")
        sources = relation.get("sources") or []
        if not sources or any(
            not str(source.get("url", "")).startswith("https://")
            or not str(source.get("supports", "")).strip()
            for source in sources
        ):
            raise ValueError("US_RELATION_PROPOSAL_SOURCE_INVALID")
        if us not in universe_contract["symbols"]:
            continue
        proposal_cards.append({
            **relation,
            "relation_source_refs": [dict(
                title=source.get("title"), url=source.get("url"),
                reporting_period=source.get("reporting_period"), supports=source.get("supports"),
            ) for source in sources],
            "evidence_review_status": "PROPOSED",
            "strict_selection_supported": False,
        })
    unmapped_symbols = list(registry_source.get("unmapped_symbols", []))
    unmapped_by_symbol = {
        item.get("us_symbol"): item
        for item in unmapped_symbols
        if isinstance(item, dict) and item.get("us_symbol")
    }
    relation_symbols = {
        card.get("us_symbol")
        for card in [*joined.values(), *proposal_cards]
        if isinstance(card, dict)
    }
    for symbol in universe_contract.get("additional_symbols", []):
        if symbol not in relation_symbols and symbol not in unmapped_by_symbol:
            unmapped_symbols.append({
                "us_symbol": symbol,
                "status": "CANNOT_CONFIRM",
                "reason": "No HK target relationship is established for this configured US symbol.",
            })
    projection=dict(cards=[*joined.values(),*proposal_cards],symbol_assessments=assessments,
        available_at=registry.get('available_at'),limitations=review.get('limitations',[]),
        status=registry.get("status"),pit_status=registry.get("pit_status"),
        decision_use=registry_source.get("decision_use"),
        strict_selection_eligible=registry_source.get("strict_selection_eligible") is True,
        unmapped_symbols=unmapped_symbols,
        additional_relation_sources=[*seed_sources,*inherited_sources])
    factor, factor_files, factor_gap = us_factor_exposure(config, context)
    industry = hk_industry_classification(config, context)
    return dict(quote_local_path=str(root),quote_relative=quote_rel,quote_sha256=qsha,
        quote_artifact_date=artifact_date,quote_source_session=session,
        quote_owner='research_peripheral.external_finance',
        relation_local_path=str(registry_root),relation_relative=registry_relative,relation_sha256=registry_sha,
        relation_owner='US_MAPPING_BUSINESS_RELATION_PROPOSAL_REGISTRY',relation_projection=projection,
        configured_symbols=list(universe_contract["symbols"]),universe_contract=universe_contract,
        universe_version=universe_contract["version"],source_gaps_by_symbol=source_gaps_by_symbol,
        relation_registry_version=US_RELATION_REGISTRY_VERSION,
        factor_exposure=factor,factor_exposure_gap=factor_gap,hk_industry_classification=industry,
        checked_files=[dict(source_local_path=str(root),relative=receipt_rel,sha256=rsha),
            dict(source_local_path=str(config.relation_root),relative=config.relation_evidence_relative,sha256=esha),
            dict(source_local_path=str(config.relation_root),relative=config.relation_review_relative,sha256=vsha),
            dict(source_local_path=str(registry_root),relative=registry_relative,sha256=registry_sha),
            *seed_sources,*inherited_sources,*factor_files,*industry.get('checked_files',[])],
        owner_manifest_ref='research/peripherals/manifest.json',owner_manifest_sha256=msha)

```
