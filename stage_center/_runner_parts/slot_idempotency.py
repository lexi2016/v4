"""stage_center.runner: slot_idempotency (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


_MAX_PENDING_RUNS_PER_LANE = 32


def _pending_runs(scope, root, prefix, error):
    """Bound lookup to one exact date/role; never scan data roots recursively."""
    from itertools import islice
    path = _v4_global(scope, '_safe_recovery_path')(root, prefix)
    if not path.exists():
        return ()
    entries = list(islice(path.iterdir(), _MAX_PENDING_RUNS_PER_LANE + 1))
    if len(entries) > _MAX_PENDING_RUNS_PER_LANE:
        raise error('pending publication lane exceeds bounded run count')
    for item in entries:
        if item.is_symlink() or not item.is_dir():
            raise error('pending publication lane has unsafe entry')
    return tuple(entries)


def _assert_raw_latest_pointer(error, pointer, verified, market, *, context='existing'):
    fields = (
        'owner', 'trade_date', 'stage_id', 'market', 'role', 'run_id', 'status',
        'idempotency_key', 'artifact_relative', 'manifest_relative', 'receipt_relative',
        'artifact_sha256', 'manifest_sha256', 'receipt_sha256', 'row_count',
    )
    if not isinstance(pointer, dict):
        raise error(f'{context} raw pointer is malformed: {market}')
    for field in fields:
        if pointer.get(field) != verified.get(field):
            raise error(f'{context} raw pointer {field} mismatch: {market}')


def _recover_pending_lanes(scope, runner, trade_date, stage_id, markets, expected_sha):
    """Restore only same-authority publications under their original locks.

    Historical namespaces are never changed here. Missing CSV or durable
    identity remains an explicit failure and cannot trigger a fresh capture.
    """
    from stage_center import raw_store as raw_module, selection as selection_module
    from stage_center._raw_store_parts.transaction_publish import _finish_pending_trio, _pending_trio_manifest
    from stage_center._selection_parts.store_publication import _selection_request_identity
    error = _v4_global(scope, 'RunnerError')
    if getattr(runner.config, "backfill_run_id", None):
        return {}, []
    raw_store = raw_module.RawStore(runner.config.raw_root)
    selection_store = selection_module.SelectionStore(runner.config.selection_root)
    safe_scope = dict(scope, _safe_recovery_path=raw_module._safe_relative)
    pending_errors = {}
    recovered = []
    for market in markets:
        try:
            key = f'{trade_date}/{stage_id}/{market}'
            with raw_store._lock():
                latest = raw_store._load_latest()
                if key not in latest['entries']:
                    dirs = _pending_runs(safe_scope, raw_store.root,
                        f'runs/{trade_date}/{raw_store._role(stage_id, market)}', error)
                    if len(dirs) > 1:
                        raise error('ambiguous pending raw publications')
                    for run_dir in dirs:
                        manifest = _pending_trio_manifest(raw_module.__dict__, run_dir, error_type=error)
                        if expected_sha.get(market) is None or not _v4_global(scope, '_existing_binding_matches')(
                            manifest.get('source_evidence', ()), market=market, expected_sha=expected_sha[market]):
                            raise error('pending raw candidate authority mismatch')
                        for field, value in (('owner', 'stage_center'), ('trade_date', trade_date), ('stage_id', stage_id), ('market', market), ('run_id', run_dir.name)):
                            if manifest.get(field) != value:
                                raise error('pending raw identity mismatch')
                        artifact_relative = f"{run_dir.relative_to(raw_store.root).as_posix()}/artifact.csv"
                        idem = raw_module.canonical_sha({'owner': 'stage_center', 'trade_date': trade_date,
                            'stage_id': stage_id, 'market': market, 'source_id': manifest.get('source_id'),
                            'input_sha256': manifest.get('input_sha256')})
                        expected_run_id = f'{trade_date}-{raw_store._role(stage_id, market).lower()}-{idem[:16]}'
                        if (manifest.get('artifact_relative') != artifact_relative
                                or run_dir.name != expected_run_id):
                            raise error('pending raw request identity mismatch')
                        intent_path = run_dir / 'publication-intent.json'
                        receipt = (raw_module._read_json(intent_path).get('receipt')
                                   if intent_path.exists() else raw_module._read_json(run_dir / 'receipt.json'))
                        if (not isinstance(receipt, dict)
                                or receipt.get('input_sha256') != manifest.get('input_sha256')
                                or receipt.get('idempotency_key') != idem
                                or receipt.get('source_id') != manifest.get('source_id')
                                or receipt.get('source_evidence') != manifest.get('source_evidence')):
                            raise error('pending raw receipt request identity mismatch')
                        for field in ('status', 'source_status', 'artifact_relative', 'artifact_sha256',
                                      'row_count', 'temporal_cutoff_safe', 'requested_rows', 'source_rows',
                                      'coverage_ratio', 'missing_symbols', 'cannot_confirm', 'calendar'):
                            if receipt.get(field) != manifest.get(field):
                                raise error('pending raw receipt manifest mismatch')
                        _finish_pending_trio(raw_module.__dict__, run_dir, error_type=error)
                        verified = raw_store.verify_run(trade_date, stage_id, market, run_dir.name)
                        receipt = raw_module._read_json(run_dir / 'receipt.json')
                        if verified.get('idempotency_key') != idem:
                            raise error('pending raw request identity mismatch')
                        entry = {field: verified[field] for field in ('owner', 'trade_date', 'stage_id', 'market', 'role', 'run_id', 'status', 'idempotency_key', 'artifact_relative', 'manifest_relative', 'receipt_relative', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256', 'row_count')}
                        entry.update(raw_module.SAFETY_FLAGS)
                        raw_store._merge_latest(latest, key, entry)
                        raw_module._atomic_write_json(raw_store.latest_path, latest)
                        recovered.append(f"RAW:{market}")
            # Selection recovery consumes a specific immutable raw generation.
            # Keep that pointer stable through validation and selection pointer
            # publication. When both stores are locked, use raw then selection;
            # no Stage path acquires these locks in the reverse order.
            with raw_store._lock():
                with selection_store._lock():
                    latest = selection_store._latest()
                    if key not in latest['entries']:
                        dirs = _pending_runs(safe_scope, selection_store.root,
                            f'selection_runs/{trade_date}/{selection_store._role(stage_id, market)}', error)
                        if len(dirs) > 1:
                            raise error('ambiguous pending selection publications')
                        for run_dir in dirs:
                            manifest = _pending_trio_manifest(selection_module.__dict__, run_dir, error_type=error)
                            envelope = manifest.get('selection_envelope') or {}
                            if expected_sha.get(market) is None or not _v4_global(scope, '_existing_binding_matches')(
                                envelope.get('source_evidence', ()), market=market, expected_sha=expected_sha[market]):
                                raise error('pending selection candidate authority mismatch')
                            raw_entry = raw_store._load_latest()['entries'].get(key)
                            if not isinstance(raw_entry, dict):
                                raise error('pending selection raw pointer unavailable')
                            raw = raw_store.verify_run(trade_date, stage_id, market, str(raw_entry.get('run_id')))
                            _assert_raw_latest_pointer(error, raw_entry, raw, market, context='pending selection')
                            if envelope.get('raw_artifact_sha256') != raw['artifact_sha256']:
                                raise error('pending selection raw identity mismatch')
                            for field, value in (('owner', 'stage_center'), ('trade_date', trade_date), ('stage_id', stage_id), ('market', market), ('run_id', run_dir.name)):
                                if manifest.get(field) != value:
                                    raise error('pending selection identity mismatch')
                            artifact_relative = f"{run_dir.relative_to(selection_store.root).as_posix()}/artifact.csv"
                            expected_artifact_id, expected_run_id = selection_module._selection_identity_ids(
                                trade_date, stage_id, market, str(envelope.get('raw_artifact_sha256') or ''),
                                str(envelope.get('algorithm_sha256') or ''), envelope.get('rows') or [])
                            _input_sha, idem = _selection_request_identity(
                                selection_module.__dict__,
                                selection_store._key(trade_date, stage_id, market),
                                envelope.get('raw_artifact_sha256'),
                                envelope.get('algorithm_sha256'),
                                envelope.get('rows') or [],
                                envelope.get('source_evidence') or (),
                            )
                            intent_path = run_dir / 'publication-intent.json'
                            receipt = (selection_module._read_json(intent_path).get('receipt')
                                       if intent_path.exists() else selection_module._read_json(run_dir / 'receipt.json'))
                            if (not isinstance(receipt, dict)
                                    or manifest.get('artifact_relative') != artifact_relative
                                    or expected_run_id != run_dir.name
                                    or envelope.get('run_id') != expected_run_id
                                    or envelope.get('artifact_id') != expected_artifact_id
                                    or manifest.get('raw_artifact_sha256') != envelope.get('raw_artifact_sha256')
                                    or manifest.get('algorithm_sha256') != envelope.get('algorithm_sha256')
                                    or manifest.get('selection_status') != envelope.get('selection_status')
                                    or manifest.get('row_count') != len(envelope.get('rows') or [])
                                    or receipt.get('idempotency_key') != idem):
                                raise error('pending selection request identity mismatch')
                            for field in ('artifact_relative', 'artifact_sha256', 'row_count',
                                          'selection_status', 'raw_artifact_sha256', 'algorithm_id',
                                          'algorithm_sha256'):
                                if receipt.get(field) != manifest.get(field):
                                    raise error('pending selection receipt manifest mismatch')
                            _finish_pending_trio(selection_module.__dict__, run_dir, error_type=error)
                            verified = selection_store._verify_run(trade_date, stage_id, market, run_dir.name)
                            entry = {field: verified[field] for field in ('owner', 'trade_date', 'stage_id', 'market', 'role', 'run_id', 'artifact_relative', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256', 'idempotency_key')}
                            entry.update(selection_module.SAFETY_FLAGS)
                            latest['entries'][key] = entry
                            selection_module._atomic_write_json(selection_store.latest_path, latest)
                            recovered.append(f"SELECTION:{market}")
        except (OSError, ValueError) as exc:
            pending_errors[market] = f"PENDING_PUBLICATION_UNRECOVERABLE:{type(exc).__name__}:{exc}"
    if pending_errors:
        return pending_errors, recovered
    # Bundle is only recovered after every original market has verified raw.
    with raw_store._lock():
        latest = raw_store._load_bundle_latest()
        key = f'{trade_date}/{stage_id}'
        if key not in latest['entries']:
            dirs = _pending_runs(safe_scope, raw_store.root, f'bundle_runs/{trade_date}/{stage_id}', error)
            if len(dirs) > 1:
                raise error('ambiguous pending bundle publications')
            for run_dir in dirs:
                verified = raw_store._verify_bundle(trade_date, stage_id, run_dir.name)
                receipt = verified['receipt']
                # Scoped recovery may not adopt a sibling outside its grant.
                if set(receipt['markets']) != set(markets):
                    raise error('pending bundle market scope mismatch')
                for market, entry in receipt['markets'].items():
                    raw = raw_store.verify_run(trade_date, stage_id, market, str(entry.get('run_id')))
                    if expected_sha.get(market) is None or not _v4_global(scope, '_existing_binding_matches')(
                        raw.get('source_evidence', ()), market=market, expected_sha=expected_sha[market]):
                        raise error('pending bundle candidate authority mismatch')
                    current = raw_store._load_latest()['entries'].get(f'{key}/{market}')
                    if not current or current.get('receipt_sha256') != raw['receipt_sha256']:
                        raise error('pending bundle raw pointer mismatch')
                latest['entries'][key] = {field: receipt[field] for field in ('owner', 'trade_date', 'stage_id', 'bundle_id', 'status', 'receipt_relative')}
                latest['entries'][key].update(receipt_sha256=verified['receipt_sha256'], **raw_module.SAFETY_FLAGS)
                raw_module._atomic_write_json(raw_store.root / 'bundle_latest.json', latest)
                recovered.append('BUNDLE')
    return pending_errors, recovered


def _StageCenterRunner__existing_slot_body(_v4_scope, /, self, trade_date, stage_id, markets, candidate_sha_by_market):
    """Read reusable slot lanes against their own authority bindings.

        The old slot identity carried one candidate SHA for the whole stage.
        That made a missing A current turn the HK D-1 SHA into a global
        mismatch (and made a good HK lane unreusable).  Keep malformed store
        trios fail-closed, while treating a candidate mismatch as a lane-local
        cache miss so the other market can be reused safely.
        """
    if _v4_global(_v4_scope, 'isinstance')(candidate_sha_by_market, _v4_global(_v4_scope, 'str')):
        expected_sha = {market: candidate_sha_by_market for market in markets}
    else:
        expected_sha = {market: candidate_sha_by_market.get(market) for market in markets}
    pending_errors, recovered = _recover_pending_lanes(_v4_scope, self, trade_date, stage_id, markets, expected_sha)
    raw_bundle_entry = _v4_global(_v4_scope, '_latest_entry')(self.config.raw_root, "bundle_latest.json", f"{trade_date}/{stage_id}")
    selection_entries: dict[str, Mapping[str, Any] | None] = {
        market: _v4_global(_v4_scope, '_latest_entry')(self.config.selection_root, "selection_latest.json", f"{trade_date}/{stage_id}/{market}")
        for market in markets
    }
    raw_market_present = _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, '_latest_entry')(self.config.raw_root, "latest.json", f"{trade_date}/{stage_id}/{market}") is not None for market in markets)
    present = raw_bundle_entry is not None or raw_market_present or _v4_global(_v4_scope, 'any')(value is not None for value in selection_entries.values())
    if not present and not pending_errors:
        return "ABSENT", None
    raw_store = _v4_global(_v4_scope, 'RawStore')(self.config.raw_root)
    selection_store = _v4_global(_v4_scope, 'SelectionStore')(self.config.selection_root)
    raw_verified: dict[str, Mapping[str, Any]] = {}
    selections: dict[str, Mapping[str, Any]] = {}
    candidate_binding_errors: dict[str, str] = {}
    for market in markets:
        if market in pending_errors:
            continue
        raw_entry = _v4_global(_v4_scope, '_latest_entry')(self.config.raw_root, "latest.json", f"{trade_date}/{stage_id}/{market}")
        if raw_entry is not None:
            try:
                verified = raw_store.verify_run(trade_date, stage_id, market, _v4_global(_v4_scope, 'str')(raw_entry.get("run_id")))
            except (_v4_global(_v4_scope, 'RawStoreError'), _v4_global(_v4_scope, 'ValueError')) as error:
                raise _v4_global(_v4_scope, 'RunnerError')(f"existing raw market integrity failure: {market}") from error
            _assert_raw_latest_pointer(
                _v4_global(_v4_scope, 'RunnerError'), raw_entry, verified, market
            )
            expected = expected_sha.get(market)
            if expected is None:
                candidate_binding_errors[market] = "existing raw candidate SHA cannot be verified: market binding unavailable"
            elif _v4_global(_v4_scope, '_existing_binding_matches')(
                verified.get("source_evidence", ()),
                market=market,
                expected_sha=expected,
            ):
                raw_verified[market] = verified
            else:
                candidate_binding_errors[market] = f"existing raw candidate SHA mismatch: {market}"
        selection_entry = selection_entries.get(market)
        if selection_entry is not None:
            try:
                envelope = selection_store.read_verified(trade_date, stage_id, market)
            except (_v4_global(_v4_scope, 'SelectionError'), _v4_global(_v4_scope, 'ValueError')) as error:
                raise _v4_global(_v4_scope, 'RunnerError')(f"existing selection integrity failure: {market}") from error
            expected = expected_sha.get(market)
            if expected is None:
                candidate_binding_errors[market] = "existing selection candidate SHA cannot be verified: market binding unavailable"
            elif _v4_global(_v4_scope, '_existing_binding_matches')(
                envelope.get("source_evidence", ()),
                market=market,
                expected_sha=expected,
            ):
                verified_raw = raw_verified.get(market)
                if verified_raw is None or envelope.get("raw_artifact_sha256") != verified_raw.get("artifact_sha256"):
                    pending_errors[market] = (
                        f"EXISTING_SELECTION_RAW_IDENTITY_MISMATCH:{market}:"
                        f"selection={envelope.get('raw_artifact_sha256')}:"
                        f"raw={(verified_raw or {}).get('artifact_sha256', 'CANNOT_CONFIRM')}"
                    )
                else:
                    selections[market] = envelope
            else:
                candidate_binding_errors[market] = f"existing selection candidate SHA mismatch: {market}"
    if raw_bundle_entry is not None and _v4_global(_v4_scope, 'len')(raw_verified) == _v4_global(_v4_scope, 'len')(markets):
        try:
            raw = raw_store.read_verified_bundle(trade_date, stage_id)
        except (_v4_global(_v4_scope, 'RawStoreError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'RunnerError')("existing raw bundle integrity failure") from error
    else:
        raw = {"receipt": {"markets": {market: _v4_global(_v4_scope, 'dict')(entry) for market, entry in raw_verified.items()}}}
    if raw_bundle_entry is not None and _v4_global(_v4_scope, 'len')(raw_verified) == _v4_global(_v4_scope, 'len')(markets) and _v4_global(_v4_scope, 'len')(selections) == _v4_global(_v4_scope, 'len')(markets):
        return "VERIFIED", {"raw": raw, "selections": selections, "raw_verified": raw_verified, "candidate_binding_errors": candidate_binding_errors, "pending_errors": pending_errors, "commit_recovery_performed": bool(recovered), "recovered_publications": recovered}
    if not raw_verified and not selections and not pending_errors:
        return "ABSENT", None
    return "PARTIAL", {"raw": raw, "selections": selections, "raw_verified": raw_verified, "candidate_binding_errors": candidate_binding_errors, "pending_errors": pending_errors, "commit_recovery_performed": bool(recovered), "recovered_publications": recovered}
