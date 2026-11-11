def qfq_registry_summary(result):
    """Reference the original complete owner receipts, never copy stock detail.

    Candidate publication precedes registry recording. Both the immutable
    candidate evidence and its READY completion must match this exact result.
    The normal Claim.finish artifact validation and metadata budget still apply.
    """
    from ops.research_storage_retention import FLAGS
    run = safe_path(result['run_dir'])
    refs = {}
    documents = {}
    for name in ('candidate_receipt', 'stage_status'):
        path = safe_path(run / (name + '.json'))
        before = stamp(path)
        raw = path.read_bytes()
        if stamp(path) != before:
            raise RetentionError('QFQ_OWNER_RECEIPT_CHANGED')
        documents[name] = json.loads(raw)
        refs[name] = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    candidate, ready = documents['candidate_receipt'], documents['stage_status']
    if (result.get('status') != 'READY' or ready.get('status') != 'READY'
            or candidate.get('status') not in {'CANDIDATE_READY', 'READY'}
            or not result.get('generation_id')
            or set(result.get('candidates', {})) != {'selector', 'backtest'}
            or set(result.get('candidate_sha256', {})) != {'selector', 'backtest'}
            or any(result.get(role) != result['candidates'][role] for role in ('selector', 'backtest'))
            or ready.get('selector_pointer_ready') is not True
            or ready.get('backtest_pointer_ready') is not True):
        raise RetentionError('QFQ_OWNER_RECEIPT_NOT_READY')
    for document in (result, candidate, ready):
        if (any(document.get(key) != result.get(key) for key in
                ('generation_id', 'target_date', 'run_dir', 'candidates', 'candidate_sha256'))
                or any(document.get(key) != value for key, value in FLAGS.items())):
            raise RetentionError('QFQ_OWNER_RECEIPT_CONFLICT')
    return dict(schema='qfq_registry_owner_receipt_summary.v1', status='READY',
        generation_id=result['generation_id'], target_date=result['target_date'],
        selector=result['selector'], backtest=result['backtest'],
        candidate_sha256=result['candidate_sha256'],
        complete_owner_receipt=refs['candidate_receipt'],
        ready_owner_receipt=refs['stage_status'], **FLAGS)

