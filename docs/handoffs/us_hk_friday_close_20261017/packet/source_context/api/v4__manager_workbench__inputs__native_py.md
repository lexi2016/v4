## Source excerpt: `v4/manager_workbench/inputs/native.py`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-continuation-api-20261017-r11c/app/v4/manager_workbench/inputs/native.py`

Original full-file SHA-256: `f408a0fb6838259d7c5b12bfaa296795d267a4e4ac0078257c8eefff23480756`

Release/worktree group: `api`

Dynamic owner-binding route and the active NativeAdapters.us_mapping consumer entry.

### Full-source lines 25-37

```python

    def prepare_context(self, context):
        context = context.model_copy(deep=True)
        try:
            context.source_sessions.setdefault("hk_price", previous_session(self.calendar, context.target_date, market="hk_securities"))
        except ValueError:
            context.source_sessions.setdefault("hk_price",None)
        if "us" not in context.source_sessions:
            try: context.source_sessions["us"] = self._us_session(context.cutoff)
            except (ValueError,OSError): context.source_sessions["us"] = None
        if self.config.dynamic_source_bindings and "owner_bindings" not in context.scope_refs:
            from .source_bindings import resolve_bindings
            pins, gaps = resolve_bindings(self.config, context)
            context.scope_refs["owner_bindings"] = pins

```

### Full-source lines 90-100

```python

    def _us_session(self, cutoff):
        # Optional native dependency remains explicitly pinned until integrated.
        try:
            from contracts.us_equity_calendar import latest_completed_session
        except ModuleNotFoundError:
            import importlib.util
            import sys
            path = self.config.us_calendar_path
            if not path or raw_sha(path.read_bytes()) != self.config.us_calendar_sha256:
                raise ValueError("US_CALENDAR_DEPENDENCY_NOT_BOUND")
            spec = importlib.util.spec_from_file_location("mwb_pinned_us_calendar",path)

```

### Full-source lines 762-808

```python

    def us_mapping(self, context):
        from .us_universe import (
            LEGACY_UNIVERSE_VERSION,
            build_legacy_us_universe_contract,
            validate_us_universe_contract,
        )
        expected = context.source_sessions.get("us") or self._us_session(context.cutoff)
        pin = self._binding("us_mapping", context.target_date, context)
        # Pinned native US owner payload + reviewed registry, never old computed matches.
        quote_root = Path(pin.get("quote_local_path") or pin["quote_root"])
        quotes, qsha = self._json(quote_root, pin["quote_relative"], pin["quote_sha256"])
        snapshot=quotes.get("market_snapshot",quotes)
        if not isinstance(snapshot,dict):raise ValueError("US_NATIVE_SNAPSHOT_SHAPE_INVALID")
        registry, rsha = self._json(Path(pin.get("relation_local_path") or pin["relation_root"]), pin["relation_relative"], pin["relation_sha256"])
        registry = pin.get("relation_projection",registry)
        if snapshot.get("session_date", snapshot.get("us_session_date",snapshot.get("capture_session_date"))) != expected:
            raise ValueError("US_SESSION_MISMATCH")
        configured = pin.get("configured_symbols", [])
        contract_value = pin.get("universe_contract") or snapshot.get("universe_contract")
        if not isinstance(contract_value, dict) and len(configured) == 33:
            contract_value = build_legacy_us_universe_contract()
        universe_contract = validate_us_universe_contract(contract_value or {})
        universe_version = universe_contract["version"]
        expected_symbols = universe_contract["symbols"]
        pin_universe_version = pin.get("universe_version")
        if (pin_universe_version is None and universe_version == LEGACY_UNIVERSE_VERSION
                and snapshot.get("universe_contract") is None):
            pin_universe_version = LEGACY_UNIVERSE_VERSION
        if (pin_universe_version != universe_version or configured != expected_symbols
                or snapshot.get("universe_contract") not in (None, universe_contract)):
            raise ValueError("US_UNIVERSE_CONTRACT_IDENTITY_MISMATCH")
        expected_count = len(expected_symbols)
        if (not isinstance(configured, list) or not configured
                or len(set(configured)) != len(configured)):
            raise ValueError("US_UNIVERSE_CONTRACT_INVALID")
        if universe_version == LEGACY_UNIVERSE_VERSION and expected_count != 33:
            raise ValueError("US_LEGACY_FIXED_33_SCOPE_INVALID")
        codes, member_ref, gaps = self.membership(context)
        relation_role = ("US_HK_RELATION_PROPOSAL_REGISTRY"
            if registry.get("status") == "PROPOSED" or registry.get("pit_status") == "PIT_UNCONFIRMED"
            else "REVIEWED_US_HK_RELATIONS")
        quote_role = ("US_FIXED_33_QUOTES" if universe_version == LEGACY_UNIVERSE_VERSION
            else "US_UNIVERSE_CONTRACT_QUOTES")
        refs = [self._ref(pin["quote_owner"], quote_role, expected, qsha,
                          pin["quote_relative"], snapshot.get("available_at", snapshot.get("captured_at"))),
                self._ref(pin["relation_owner"], relation_role, expected, rsha,
                          pin["relation_relative"], registry.get("available_at"))]

```
