# 有界源码摘录

本文件用于快速定位；完整必要模块的原始字节快照按当前部署和历史 release 分别保存在相邻 source 子树。每个片段的行号基于对应 SHA 的副本。未包含 live data。

## 当前 API workspace GET — `app/apps/api/v35_api/manager_research_router.py:207-228`

```
207:     async def read_manager_workspace(request: Request, date: str | None = None,
208:             view: Literal["auto", "historical", "dynamic"] = "auto",
209:             announcement_date: str | None = None,
210:             selection_date: str | None = None) -> dict[str, Any]:
211:         # Use the existing ASGI worker pool. A disconnect only withdraws this
212:         # subscriber; the owner cooperatively stops when no subscriber remains.
213:         # Native blocking calls cannot be preempted and retain their bounded slot.
214:         target = _date(date)
215:         cancelled = Event()
216:         workspace_args: dict[str, Any] = {"view": view, "cancel_event": cancelled}
217:         if announcement_date is not None:
218:             workspace_args["announcement_date"] = _announcement_date(announcement_date)
219:         if selection_date is not None:
220:             workspace_args["selection_date"] = _date(selection_date)
221:         task = asyncio.create_task(run_in_threadpool(
222:             service.get_workspace, target, **workspace_args))
223:         try:
224:             while not task.done():
225:                 await asyncio.wait({task}, timeout=0.1)
226:                 if not task.done() and await request.is_disconnected():
227:                     raise HTTPException(status_code=499, detail="WORKSPACE_READ_CANCELLED")
228:             return await task
```

## 当前 service.get_workspace owner bridge — `app/v4/manager_research/service.py:394-418`

```
394:     def get_workspace(self, target_trade_date: str, *, view: str = "dynamic",
395:                       now: datetime | None = None, cancel_event: threading.Event | None = None,
396:                       selection_date: str | None = None, announcement_date: str | None = None,
397:                       us_market_request_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
398:         # Legacy internal callers retain dynamic semantics. The browser GET
399:         # explicitly supplies auto (historical for past HK dates).
400:         from .workspace import get_workspace
401:         target_trade_date = strict_trade_date(target_trade_date)
402:         if view not in {"auto", "historical", "dynamic"}:
403:             raise ValueError("WORKSPACE_VIEW_INVALID")
404:         options = {}
405:         if selection_date is not None:
406:             options['selection_date'] = strict_trade_date(selection_date)
407:         if announcement_date is not None:
408:             options['announcement_date'] = strict_trade_date(announcement_date.replace('-', ''))
409:         if us_market_request_context is not None:
410:             options['us_market_request_context'] = dict(us_market_request_context)
411:         key = (target_trade_date, view, now.isoformat() if now is not None else "SERVER_CLOCK",
412:                options.get('selection_date'), options.get('announcement_date'),
413:                json.dumps(options.get('us_market_request_context'), sort_keys=True))
414:         return self._workspace_reads.run(key,
415:             lambda: get_workspace(self, target_trade_date, view=view, now=now, **options), cancelled=cancel_event)
416: 
417:     def refresh_us_mapping_research(self, target_trade_date: str, *, now: datetime,
418:                                     timeout_seconds: float | None = None,
```

## 当前 Stage readback and LIVE ledger attempt consumer — `app/v4/manager_research/workspace.py:326-360`

```
326: def _reader_value(reader: Any,date: str,lane: str) -> dict:
327:     if reader is None:
328:         return dict(status='CANNOT_CONFIRM',target_trade_date=date,cannot_confirm=[lane+'_ORIGINAL_READER_NOT_BOUND'])
329:     try:
330:         value = reader.read(date) if hasattr(reader,'read') else reader(date)
331:         if not isinstance(value,Mapping):
332:             raise ValueError('owner did not return an envelope')
333:         return dict(value)
334:     except _ERROR_TYPES as exc:
335:         return dict(status='FAILED',target_trade_date=date,cannot_confirm=[lane+'_ORIGINAL_READER_FAILED:'+type(exc).__name__])
336: 
337: 
338: def _stage_attempt(service: Any,date: str) -> tuple[dict | None,list[str]]:
339:     root = service._workspace_ledger_root
340:     if root is None:
341:         return None,['STAGE_EXECUTION_LEDGER_NOT_EXPLICITLY_BOUND']
342:     try:
343:         from infrastructure.scheduling.execution_ledger import ExecutionLedger
344:         ledger=ExecutionLedger(root)
345:         rows=ledger.list_receipts(date,mode='LIVE')
346:         valid,_=ledger.verify_receipt_chain(date,mode='LIVE')
347:         if not valid:
348:             raise ValueError('receipt chain invalid')
349:         for receipt in reversed(rows):
350:             if receipt.get('target_date')!=date or receipt.get('scheduled_date')!=date:
351:                 continue
352:             for result in receipt.get('workload_results',[]):
353:                 if not isinstance(result,Mapping) or result.get('workload_id')!='stage_workbench':
354:                     continue
355:                 # No scheduler slot -> real execution timestamp conversion.
356:                 # Preserve absence where the supplied contract does not expose it.
357:                 started=result.get('started_at') or receipt.get('started_at')
358:                 status=str(result.get('status') or '').upper()
359:                 attempt=dict(run_id=receipt.get('run_id'),started_at=started if timestamp(started) else None,
360:                              state={'FAILED':'FAILED','RUNNING':'RUNNING','SUCCEEDED':'SUCCEEDED','READY':'SUCCEEDED'}.get(status,'UNVERIFIED'),
```

## 当前 workspace lane owner and consumer branches — `app/v4/manager_research/workspace.py:666-733`

```
666: def _compute_workspace(service: Any, date: str, *, include_saved: bool = True, context: dict,
667:                        us_market_request_context: Mapping[str, Any] | None = None) -> dict:
668:     from copy import deepcopy
669:     context = deepcopy(context)
670:     try:
671:         with phase('catalyst_owner'):
672:             catalyst=service.get_catalyst_observations(date)
673:     except _ERROR_TYPES as exc:
674:         catalyst=dict(status='FAILED',target_trade_date=date,cards=[],gaps=['CATALYST_ORIGINAL_READER_FAILED:'+type(exc).__name__],**FLAGS)
675:     with phase('stage_owner'):
676:         stage=_reader_value(service.observation_reader,date,'STAGE')
677:     with phase('close_owner'):
678:         close=_reader_value(service._close_observation_reader,date,'CLOSE')
679:     with phase('close_recapture_owner'):
680:         close_recapture,requested_day_close_recapture=_read_close_recapture_inputs(
681:             service._close_observation_reader,date,context)
682:     with phase('existing_material_owners'):
683:         existing=_materials(service,date,context)
684:     with phase('discovery_owner'):
685:         discovery=_discovery(service,date,catalyst)
686:     from .workspace_announcements import read as read_announcements, read_selection_inputs
687:     from .connect_selection import read_scope, filter_cards, gate_workspace, evidence_view, selection_diagnostics
688:     # The original owner revalidates existing stored bodies before the SAME
689:     # native issuer classifier runs. This GET still never fetches or writes.
690:     with phase('announcement_source_validation'):
691:         announcement_review = read_announcements(service, date, context)
692:     with phase('announcement_body_selection_inputs'):
693:         try:
694:             announcement_inputs=read_selection_inputs(service,context,current_review=announcement_review)
695:         except _ERROR_TYPES as exc:
696:             reason='ANNOUNCEMENT_SELECTION_ORIGINAL_READER_FAILED:'+type(exc).__name__
697:             announcement_inputs=dict(materials=[],rejections=[dict(reason=reason)],gaps=[reason],captures=[],
698:                 status='CANNOT_CONFIRM',input_identity=digest([reason]),**FLAGS)
699:     with phase('target_connect_authority'):
700:         connect_scope=read_scope(context)
701:     selection_materials=[*existing['materials'],*announcement_inputs['materials']]
702:     with phase('material_discovery'):
703:         material_discovery=read_material_discovery(selection_materials,context,
704:             getattr(service,'_workspace_security_master_root',None),
705:             projection_memo=getattr(service,'_workspace_projection_memo',None))
706:     material_discovery=deepcopy(material_discovery)
707:     pre_connect_material_cards=deepcopy(material_discovery.get('cards',[]))
708:     post_connect_material_cards,connect_rejections=filter_cards(
709:         pre_connect_material_cards,connect_scope,target_date=date)
710:     research_relation_cards=_research_relation_material_cards(
711:         pre_connect_material_cards,connect_scope,connect_rejections,date)
712:     material_discovery['cards']=post_connect_material_cards
713:     material_discovery['rejected_relations']=[*material_discovery.get('rejected_relations',[]),*connect_rejections]
714:     material_discovery['coverage']['target_connect_card_count']=len(material_discovery['cards'])
715:     material_discovery['coverage']['pre_connect_card_count']=len(pre_connect_material_cards)
716:     material_discovery['coverage']['research_relation_card_count']=len(research_relation_cards)
717:     material_discovery['coverage']['target_connect_rejection_count']=len(connect_rejections)
718:     relation_material_input=_research_relation_material_input(
719:         pre_connect_cards=pre_connect_material_cards,post_connect_cards=post_connect_material_cards,
720:         relation_cards=research_relation_cards,connect_scope=connect_scope,
721:         connect_rejections=connect_rejections,material_discovery=material_discovery,
722:         selection_materials=selection_materials,existing=existing,announcement_inputs=announcement_inputs)
723:     with phase('exact_quote_owner'):
724:         quote_evidence=read_plan_quotes(service._catalyst_data_root,context,
725:             authority_root=getattr(service,'_workspace_security_master_root',None))
726:     screen_authority_root = (getattr(service, '_workspace_screen_authority_root', None)
727:                              or getattr(service, '_workspace_security_master_root', None))
728:     with phase('rebound_screen'):
729:         market_screen = read_rebound_screen(screen_authority_root, context)
730:     context['market_data_verified']=quote_evidence['verified']
731:     with phase('previous_observation'):
732:         previous,continuity_gap=_previous_observation(service,date)
733:     attempts={}
```

## 当前 exact-date daily channel construction — `app/v4/manager_research/workspace_daily_channels.py:79-170`

```
79: def build_daily_channels(value: Mapping[str, Any]) -> dict[str, Any]:
80:     """Expose stock/reason/date/run without changing owners' rows or ranking."""
81:     bindings = dict(_object(value.get('date_bindings')))
82:     target = bindings.get('plan_date') or value.get('target_trade_date')
83:     bindings.setdefault('plan_date', target)
84:     bindings.setdefault('selection_date', target)
85:     publication = str(bindings.get('announcement_date') or '').replace('-', '')
86:     reviewed = _object(value.get('announcement_reviewed_analysis'))
87:     products = _rows(reviewed.get('products'))
88:     exact = [p for p in products if p.get('target_trade_date') == target
89:         and str(p.get('publication_date') or '').replace('-', '') == publication]
90:     consumed = {p.get('product_sha256'):p for p in exact if p.get('status') == 'CONSUMED'}
91:     announcement = _base('ANNOUNCEMENT', bindings, owner='ManagerResearchJobService.import_announcement_analysis',
92:         data_date=publication or None, dependencies=['REGISTERED_REVIEWED_HANDOFF','OWNER_IMPORT_RECEIPT'])
93:     announcement_rows = []
94:     for reference in _rows(reviewed.get('research_references')):
95:         source = consumed.get(reference.get('product_sha256'))
96:         if source is None or reference.get('target_trade_date') != target or str(reference.get('publication_date') or '').replace('-', '') != publication:
97:             continue
98:         symbol = canonical_symbol(reference.get('stock_code'))
99:         if symbol is None or reference.get('research_status') not in {'SELECTED','CONDITIONAL_WATCH'}:
100:             continue
101:         reasons = _texts(reference.get('selection_reasons'))
102:         if not reasons:
103:             reasons = [reason for article in _rows(reference.get('article_refs')) for reason in _texts(article.get('reason'))]
104:         announcement_rows.append(dict(symbol=symbol, name=reference.get('stock_name') or symbol,
105:             reason='；'.join(dict.fromkeys(reasons)) or None, selection_status=reference['research_status'],
106:             data_date=publication, target_trade_date=target,
107:             product_sha256=reference.get('product_sha256'), source_manifest_sha256=reference.get('source_manifest_sha256'),
108:             run_id=source.get('evidence_run_id'), generated_at=source.get('owner_available_at') or source.get('reviewed_at'),
109:             source_refs=_references(reference.get('article_refs', []))))
110:     if consumed:
111:         assessed=all(p.get('selection_status')=='VERIFIED'
112:             and type(p.get('not_assessed_stock_count')) is int for p in consumed.values())
113:         pending=sum(p['not_assessed_stock_count'] for p in consumed.values()) if assessed else None
114:         incomplete=len(consumed)!=len(exact) or not assessed or bool(pending)
115:         selected=sum(r['selection_status']=='SELECTED' for r in announcement_rows)
116:         announcement.update(status='PARTIAL' if incomplete else 'READY',
117:             rows=announcement_rows, candidate_count=selected if selected or not incomplete else None,
118:             pending_count=pending,
119:             watch_count=sum(r['selection_status']=='CONDITIONAL_WATCH' for r in announcement_rows),
120:             execution_kind='OWNER_IMPORT_TIMING_NOT_CLASSIFIED',
121:             input_identity=digest(sorted(consumed)),
122:             product_sha256=next(iter(consumed)) if len(consumed)==1 else None)
123:         dates=[r['generated_at'] for r in announcement_rows if r['generated_at']]
124:         announcement['generated_at']=max(dates) if dates else next(iter(consumed.values())).get('owner_available_at')
125:         announcement['run_id']=next(iter(consumed.values())).get('evidence_run_id') if len(consumed)==1 else None
126:         if not announcement_rows and announcement['status']=='READY':
127:             announcement['status']='READY_EMPTY'
128:     announcement['gaps'] = sorted({gap for p in exact for gap in _texts(p.get('gaps'))})
129:     if consumed and (not assessed or pending):
130:         announcement['gaps'].append('ANNOUNCEMENT_SELECTION_NOT_ASSESSED')
131:     if not exact:
132:         announcement['gaps']=['ANNOUNCEMENT_EXACT_DATE_PRODUCT_NOT_CONSUMED']
133:     announcement['product_checks']=_checks(exact)
134:     announcement['other_product_checks']=_checks([p for p in products if p not in exact])
135: 
136:     execution = _execution(value)
137:     diagnostics = _object(value.get('selection_diagnostics'))
138:     membership = _object(diagnostics.get('membership'))
139:     focus_inputs = _object(_object(value.get('owner_chain')).get('focus_inputs'))
140:     connect = _base('HK_CONNECT', bindings, owner='EXISTING_WORKSPACE_FOCUS_AND_TARGET_HK_UNIVERSE_V2',
141:         dependencies=['TARGET_HK_UNIVERSE_V2','EXISTING_FOCUS_OWNERS'], **execution)
142:     connect['data_date']=_object(value.get('plan_context')).get('market_session')
143:     connect['input_identity']=membership.get('identity')
144:     from .connect_selection import _scope_error, filter_cards
145:     authority_error = _scope_error(membership, target)
146:     focus=set(value.get('focus_symbols', []))
147:     if authority_error is None:
148:         original_focus=[r for r in _rows(value.get('stocks')) if r.get('symbol') in focus
149:                         and r.get('connect_eligibility')=='VERIFIED_TARGET_UNIVERSE']
150:         verified_focus, rejected_focus=filter_cards(original_focus,membership,target_date=target)
151:         connect['rows']=[dict(symbol=r['symbol'],name=r.get('name') or r['symbol'],
152:             reason='；'.join(_texts(r.get('why_watch'))) or None, selection_status='SELECTED',
153:             data_date=connect['data_date'], target_trade_date=target, source_refs=_references(r.get('evidence',[])),
154:             run_id=execution['run_id'],generated_at=execution['generated_at'],product_sha256=execution['product_sha256'])
155:             for r in verified_focus]
156:         # General selection diagnostics also carry research-attention gaps.
157:         # Use the producer's channel-local dependency list here so a peripheral
158:         # US gap cannot change HK Connect readiness.
159:         connect['gaps']=sorted(set([*_texts(diagnostics.get('connect_gaps')),*_texts(focus_inputs.get('gaps')),
160:                                    *(r['reason'] for r in rejected_focus)]))
161:         if focus_inputs.get('status') != 'READY' and not focus_inputs.get('gaps'):
162:             connect['gaps'].append('FOCUS_OWNER_INPUT_STATUS_NOT_VERIFIED')
163:         incomplete=bool(connect['gaps'] or diagnostics.get('status') not in {'READY','READY_EMPTY'})
164:         connect['status']='PARTIAL' if incomplete else 'READY' if connect['rows'] else 'READY_EMPTY'
165:         if connect['rows'] or not incomplete:
166:             connect['candidate_count']=len(connect['rows'])
167:     else:
168:         connect['gaps']=sorted(set([*_texts(membership.get('gaps')),authority_error]))
169:     connect['authority']=deepcopy(membership)
170: 
```

## 当前 announcement exact product/readback validation — `app/v4/manager_research/workspace_announcements.py:2338-2406`

```
2338: def read_analysis_consumption(service: Any, target_trade_date: str, publication_date: str,
2339:                               *, cutoff: str | None = None,
2340:                               analysis_readback: Mapping[str, Any] | None = None) -> dict[str, Any]:
2341:     """Validate one exact imported product through the same API/plan read contract.
2342: 
2343:     This is a read only projection. In particular, a legacy product may remain
2344:     readable by the R3 analysis API while its missing judgment prevents plan
2345:     consumption. Observed identities survive rejection so that a failed older
2346:     pair cannot be confused with the current product.
2347:     """
2348:     from .announcement_analysis import _publication_date, product_path
2349:     target = date_token(target_trade_date)
2350:     publication = _publication_date(publication_date)
2351:     item = dict(schema_version='v4.manager_research.announcement_analysis_consumption.v1',
2352:         target_trade_date=target, publication_date=publication,
2353:         status='NOT_IMPORTED', validation_status='NOT_IMPORTED', consumed=False,
2354:         product_sha256=None, source_manifest_sha256=None, catalog_product_sha256=None,
2355:         source_run_id=None, evidence_run_id=None, handoff_manifest_sha256=None,
2356:         agent_judgment_receipt_sha256=None, owner_import_receipt_sha256=None,
2357:         owner_handoff_binding_status='NOT_VERIFIED', decision_status=None,
2358:         selection_status='NOT_ASSESSED', stock_count=None, selected_stock_count=None,
2359:         conditional_watch_count=None, not_selected_stock_count=None,
2360:         not_assessed_stock_count=None, reviewed_at=None, owner_available_at=None,
2361:         latest_source_or_review_at=None, plan_cutoff=cutoff,
2362:         cutoff_status='NOT_REQUESTED' if cutoff is None else 'NOT_EVALUATED',
2363:         failure_stage=None, gaps=[], research_references=[], **FLAGS)
2364:     stage = 'PRODUCT_READ'
2365:     try:
2366:         path = product_path(service.store, target, publication)
2367:         product = service.store._read(path)
2368:         if product is None:
2369:             item.update(gaps=['ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED'])
2370:             return item
2371:         if not isinstance(product, Mapping):
2372:             raise ValueError('ANNOUNCEMENT_ANALYSIS_PRODUCT_IDENTITY_INVALID')
2373:         manifest = product.get('source_manifest')
2374:         manifest = manifest if isinstance(manifest, Mapping) else {}
2375:         judgment = product.get('agent_judgment_receipt')
2376:         judgment = judgment if isinstance(judgment, Mapping) else {}
2377:         item.update(product_sha256=product.get('sha256'),
2378:             source_manifest_sha256=product.get('source_manifest_sha256'),
2379:             catalog_product_sha256=manifest.get('catalog_product_sha256'),
2380:             source_run_id=manifest.get('catalog_run_id'),
2381:             evidence_run_id=judgment.get('evidence_run_id'),
2382:             agent_judgment_receipt_sha256=judgment.get('sha256'))
2383:         stage = 'SOURCE_READBACK'
2384:         readback = (analysis_readback if analysis_readback is not None
2385:                     else service.get_announcement_analysis(target, publication))
2386:         analysis = readback.get('analysis') if isinstance(readback, Mapping) else None
2387:         if (not isinstance(analysis, Mapping) or analysis.get('status') != 'VERIFIED'
2388:                 or analysis.get('product_sha256') != product.get('sha256')):
2389:             raise ValueError('ANNOUNCEMENT_ANALYSIS_OWNER_READBACK_INVALID')
2390:         if (product.get('target_trade_date') != target
2391:                 or product.get('publication_date') != publication
2392:                 or readback.get('target_trade_date') != target
2393:                 or readback.get('publication_date') != publication
2394:                 or analysis.get('source_manifest_sha256') != product.get('source_manifest_sha256')
2395:                 or readback.get('source_catalog', {}).get('catalog_product_sha256') != manifest.get('catalog_product_sha256')):
2396:             raise ValueError('ANNOUNCEMENT_ANALYSIS_SOURCE_IDENTITY_INVALID')
2397:         stage = 'JUDGMENT_RECEIPT'
2398:         agent_receipt = validate_agent_judgment_receipt(product.get('agent_judgment_receipt'), product)
2399:         item.update(decision_status=agent_receipt['decision_status'], reviewed_at=agent_receipt['reviewed_at'])
2400:         stage = 'OWNER_IMPORT_RECEIPT'
2401:         owner_raw = service.store._read(path.with_name('owner_import_receipt.v1.json'))
2402:         if isinstance(owner_raw, Mapping):
2403:             item.update(owner_import_receipt_sha256=owner_raw.get('sha256'),
2404:                 owner_available_at=owner_raw.get('available_at'),
2405:                 handoff_manifest_sha256=owner_raw.get('handoff_manifest_sha256'))
2406:         owner_receipt = validate_owner_analysis_import_receipt(owner_raw, product)
```

## 当前 HK target V2 authority and membership reader — `app/v4/manager_research/connect_selection.py:73-155`

```
73: def read_scope(context: Mapping[str, Any]) -> dict:
74:     date=date_token(context['plan_trade_date'])
75:     result=dict(status='CANNOT_CONFIRM',target_trade_date=date,codes=[],source=None,
76:                 identity=None,gaps=[],read_only=True,
77:                 calendar_applicability=calendar_applicability(context),**FLAGS)
78:     configured=os.environ.get('V4_MANAGER_UNIVERSE_ROOT','').strip()
79:     if not configured:
80:         result['gaps']=['HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND'];return result
81:     root=Path(configured).expanduser()
82:     if not root.is_absolute() or '..' in root.parts or root.is_symlink():
83:         result['gaps']=['HK_CONNECT_TARGET_AUTHORITY_ROOT_INVALID'];return result
84:     # Only the exact target-date V2 authority can grant formal eligibility.
85:     # A prior-session capture is retained separately as source evidence.
86:     owner_text=os.environ.get('V4_MANAGER_UNIVERSE_OWNER_ROOT','').strip()
87:     owner_sha=os.environ.get('V4_MANAGER_UNIVERSE_OWNER_SHA256','').strip()
88:     owner_kwargs={}
89:     target_failure='HK_CONNECT_TARGET_AUTHORITY_OWNER_BINDING_REQUIRED'
90:     try:
91:         if not owner_text or not owner_sha:
92:             raise ValueError(target_failure)
93:         owner_root=Path(owner_text)
94:         valid=(owner_root.is_absolute() and '..' not in owner_root.parts
95:             and owner_root.resolve()==owner_root and not owner_root.is_symlink()
96:             and re.fullmatch(r'[0-9a-f]{64}',owner_sha) is not None)
97:         if not valid:
98:             raise ValueError('HK_CONNECT_TARGET_AUTHORITY_OWNER_BINDING_INVALID')
99:         owner_kwargs=dict(authority_owner_root=owner_root,authority_owner_sha256=owner_sha)
100:         result['authority_reader_binding']=dict(mode='EXPLICIT_SOURCE_PIN',
101:             owner_root=str(owner_root),source_code_ref='stage_center/hk_universe_preflight.py',
102:             source_code_sha256=owner_sha)
103:         from domains.manager_research_evidence import read_universe_evidence
104:         # Do not inject the plan cutoff as a fake clock into this reader.
105:         # This invokes native readback only, never ensure/capture/materialize.
106:         universe=read_universe_evidence(root,date,require_v2=True,**owner_kwargs)
107:         source=dict(universe.source)
108:         cutoff=timestamp(context.get('research_cutoff'))
109:         acquired=timestamp(source.get('acquired_at'))
110:         available=timestamp(source.get('available_at'))
111:         if (source.get('source_date')!=date or source.get('market')!='HK_CONNECT'
112:                 or acquired is None or available is None or cutoff is None
113:                 or acquired>cutoff or available>cutoff):
114:             raise ValueError('HK_CONNECT_TARGET_AUTHORITY_AFTER_CUTOFF_OR_WRONG_DATE')
115:         codes=sorted(set(universe.codes))
116:         if not codes or any(canonical_symbol(c)!=c for c in codes):
117:             raise ValueError('HK_CONNECT_TARGET_AUTHORITY_CODES_INVALID')
118:         result.update(status='OWNER_VERIFIED',codes=codes,source=source,
119:             identity=digest([date,codes,source['sha256']]),
120:             membership_semantics='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',
121:             availability_semantics='PERSISTED_ACQUIRED_AND_PUBLICATION_TIMES_MUST_PRECEDE_RESEARCH_CUTOFF')
122:         return result
123:     except (ImportError,OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
124:         reason=str(exc)
125:         if not re.fullmatch(r'[A-Z0-9_:. -]{1,180}',reason):reason=type(exc).__name__
126:         target_failure='HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:'+reason
127:         diagnostic=getattr(exc,'diagnostic',None)
128:         if isinstance(diagnostic,Mapping):
129:             result['authority_diagnostic']=deepcopy(dict(diagnostic))
130:     capture_root=os.environ.get('V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT','').strip()
131:     dispatch_root=os.environ.get('V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT','').strip()
132:     market_session=context.get('market_session')
133:     if capture_root and dispatch_root and market_session:
134:         from .connect_capture_adapter import read_d1_scope
135:         d1=read_d1_scope(context,security_master_root=root,
136:             capture_receipt_root=capture_root,dispatch_receipt_root=dispatch_root)
137:         result['previous_session_capture']=d1
138:         result['gaps']=[target_failure,*d1.get('gaps',[])]
139:     else:
140:         result['gaps']=[target_failure]
141:     return result
142: 
143: 
144: def _scope_error(scope: Mapping[str,Any], target_date: str) -> str | None:
145:     source=scope.get('source');codes=scope.get('codes')
146:     if (scope.get('status')!='OWNER_VERIFIED' or not isinstance(source,Mapping)
147:             or not isinstance(codes,list) or any(not isinstance(c,str) for c in codes)
148:             or codes!=sorted(set(codes))
149:             or any(canonical_symbol(c)!=c for c in codes)
150:             or not re.fullmatch(r'[0-9a-f]{64}',str(source.get('sha256','')))):
151:         return 'TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED'
152:     if (scope.get('target_trade_date')!=target_date
153:             or source.get('market')!='HK_CONNECT' or source.get('role')!='HK_CONNECT_FULL_MARKET_AUTHORITY'):
154:         return 'TARGET_HK_CONNECT_MEMBERSHIP_DATE_OR_ROLE_MISMATCH'
155:     semantics=scope.get('membership_semantics')
```

## 当前 oversold original panel witness — `app/v4/manager_research/workspace_plan.py:217-258`

```
217: def _read_hk02_panel_witness(authority_root: Path | None, day: str, *,
218:                              research_cutoff: str | None = None,
219:                              required_history_date: str | None = None) -> tuple[dict | None, list[str]]:
220:     """Read the existing owner's immutable exact-date panel, never later prices.
221: 
222:     The original owner's panel_latest pointer may identify a same-target
223:     correction whose directory also records the history date it repaired.
224:     Read that pointer before the older YYYYMMDD-<sha12> directory, but use the
225:     pointer's revision only when its manifest and panel verify and its
226:     manifest-prepared time is no later than the plan cutoff. Earlier plans may
227:     use the one immutable exact-date revision that was already available then.
228:     Multiple exact-date revisions stay ambiguous; mtime is never a selector.
229:     """
230:     if authority_root is None:
231:         return None, ['PLAN_HK_02_PANEL_AUTHORITY_ROOT_NOT_BOUND']
232:     try:
233:         import os
234:         import stat
235:         from infrastructure.owned_io import SafeRoot
236:         from .workspace_read_control import checkpoint, count
237:         if not re.fullmatch(r'\d{8}', day):
238:             return None, ['PLAN_HK_02_EXACT_DATE_INVALID']
239:         cutoff = None
240:         if research_cutoff is not None:
241:             cutoff = timestamp(research_cutoff)
242:             if cutoff is None:
243:                 return None, ['PLAN_HK_02_RESEARCH_CUTOFF_INVALID']
244:         if (required_history_date is not None
245:                 and (not re.fullmatch(r'\d{8}', required_history_date)
246:                      or required_history_date >= day)):
247:             return None, ['PLAN_HK_02_HISTORY_REQUIRED_DATE_INVALID']
248:         root = Path(authority_root).expanduser().absolute()
249:         asset_root = root / 'assets' / 'hk_0_2'
250:         io = SafeRoot(asset_root)
251:         candidates = []
252:         same_day_directories = []
253:         try:
254:             with io.directory('panels') as fd:
255:                 with os.scandir(fd) as entries:
256:                     for index, entry in enumerate(entries):
257:                         if index >= 4096:
258:                             return None, ['PLAN_HK_02_PANEL_DIRECTORY_BOUND_EXCEEDED']
```

## 当前 oversold native unit attestation — `app/v4/manager_research/workspace_plan.py:766-845`

```
766: def rebound_native_evidence(manifest: Mapping[str, Any], *, required_session: str,
767:                             observed_at: datetime, master_captured_at: str | None = None) -> dict:
768:     """Interpret ORIGINAL-owner metadata without promoting a bare unit string.
769: 
770:     v1 records byte layout, source hashes and read times ONLY. Its explicit
771:     unknowns are not vendor attestations, and its increment scope cannot certify
772:     all inherited history. No conversion to shares/HKD is licensed by v1.
773:     """
774:     from datetime import timezone
775:     if observed_at.tzinfo is None:
776:         raise ValueError('REBOUND_NATIVE_OBSERVATION_CLOCK_NAIVE')
777:     observed = observed_at.astimezone(timezone.utc)
778:     if manifest.get('panel_max_date') != required_session:
779:         raise ValueError('REBOUND_NATIVE_PANEL_SESSION_MISMATCH')
780:     native = manifest.get('native_observation')
781:     gaps = ['REBOUND_HISTORY_VOLUME_UNIT_NOT_PROVEN', 'REBOUND_HISTORY_PRICE_CURRENCY_NOT_PROVEN']
782:     if any(manifest.get(k) is not None for k in ('volume_unit','currency','price_currency','amount_unit')):
783:         gaps.append('REBOUND_BARE_UNIT_DECLARATION_NOT_ATTESTED')
784:     dates = dict(data_session=required_session, reader_observed_at=observed.isoformat(),
785:                  manifest_available_at=None, manifest_prepared_at=None,
786:                  observation_status='LEGACY_NO_NATIVE_OBSERVATION',
787:                  provider_session_finality='NOT_ATTESTED_BY_PROVIDER',
788:                  master_captured_at=master_captured_at)
789:     if master_captured_at is not None:
790:         master_time = timestamp(master_captured_at)
791:         if master_time is None or master_time > observed:
792:             raise ValueError('REBOUND_NATIVE_MASTER_AFTER_READ')
793:     if native is not None:
794:         fail = lambda: ValueError('REBOUND_NATIVE_OBSERVATION_CONTRACT_INVALID')
795:         if not isinstance(native, Mapping): raise fail()
796:         if (native.get('schema_version') != 'v3_shared_data.hk02_native_observation.v1'
797:             or native.get('scope') != 'NEW_INCREMENT_ONLY'
798:             or native.get('requested_through_date') != required_session
799:             or native.get('session_finality') != 'NOT_ATTESTED_BY_PROVIDER'
800:             or not re.fullmatch(r'[0-9a-f]{64}', str(native.get('owner_source_sha256') or ''))):
801:             raise fail()
802:         started, completed = timestamp(native.get('read_started_at')), timestamp(native.get('read_completed_at'))
803:         prepared = timestamp(manifest.get('manifest_prepared_at'))
804:         if (started is None or completed is None or prepared is None
805:             or not started <= completed <= prepared <= observed):
806:             raise ValueError('REBOUND_NATIVE_OBSERVATION_TIME_INVALID')
807:         expected_fields = {
808:             'trade': dict(native_field='trade_v',byte_offset=24,storage_type='uint32_le',
809:                           scale_applied=1,unit=None,unit_status='NOT_PROVEN'),
810:             'amount': dict(native_field='amount_v',byte_offset=20,storage_type='float32_le',
811:                            scale_applied=1,unit=None,currency=None,unit_status='NOT_PROVEN'),
812:             'price': dict(native_fields=['open_v','high_v','low_v','close_v'],byte_offsets=[4,8,12,16],
813:                           storage_type='float32_le',scale_applied=1,currency=None,
814:                           currency_status='NOT_PROVEN',transform='NONE')}
815:         # JSON equality is type-sensitive (True must not impersonate 1).
816:         if json.dumps(native.get('fields'),sort_keys=True,allow_nan=False) != json.dumps(expected_fields,sort_keys=True):
817:             raise fail()
818:         sources = native.get('source_files')
819:         selected = native.get('selected_dates')
820:         after = native.get('requested_after_date')
821:         if (not isinstance(sources,list) or not sources or not isinstance(selected,list)
822:             or selected != sorted(set(selected)) or not re.fullmatch(r'\d{8}',str(after or ''))
823:             or not selected or not all(isinstance(d,str) and re.fullmatch(r'\d{8}',d)
824:                                       and after < d <= required_session for d in selected)
825:             or selected != manifest.get('new_dates')): raise fail()
826:         names = set(); row_count = 0
827:         for source in sources:
828:             if not isinstance(source,Mapping): raise fail()
829:             name = str(source.get('source_relative') or '')
830:             size, count = source.get('size_bytes'), source.get('selected_rows')
831:             if (not re.fullmatch(r'vipdoc/ds/lday/71#\d{5}\.day',name) or name in names
832:                 or not re.fullmatch(r'[0-9a-f]{64}',str(source.get('sha256') or ''))
833:                 or type(size) is not int or size <= 0 or size % 32
834:                 or type(count) is not int or not 0 < count <= size//32): raise fail()
835:             names.add(name);row_count+=count
836:         # The original updater deduplicates selected date/code rows; this is a
837:         # bound, NOT a claim that the raw selection and final row count are equal.
838:         count = manifest.get('new_row_count')
839:         if type(count) is not int or not 0 < count <= row_count: raise fail()
840:         dates.update(observation_status='NATIVE_SOURCE_READ_RECORDED',
841:                      read_started_at=started.isoformat(),read_completed_at=completed.isoformat(),
842:                      manifest_prepared_at=prepared.isoformat())
843:     else:
844:         gaps.append('REBOUND_NATIVE_PUBLISHER_OBSERVATION_MISSING')
845:     return dict(volume_unit=None,price_currency=None,price_basis='RAW',
```

## 当前 oversold panel volume evidence and screen consumer — `app/v4/manager_research/workspace_plan.py:920-1059`

```
920: def _screen_panel_volume_evidence(panel: Mapping[str, Any], context: Mapping[str, Any],
921:                                   required_sessions: list[str]) -> dict:
922:     """Read original volume provenance without inventing an owner attestation.
923: 
924:     The current HK02 native observation v1 proves byte fields and increment
925:     read times. It explicitly does not attest units or inherited-history scale.
926:     A bare SHARES/LOTS string or security-master lot size cannot upgrade it.
927:     """
928:     result = dict(status='NOT_PROVEN', unit_status='NOT_PROVEN', unit=None,
929:         scale_applied=None, source=panel['owner'], native_field='trade',
930:         required_sessions=list(required_sessions), scope='ALL_SIX_REQUIRED_SESSIONS',
931:         source_sha256=panel['panel_sha256'], manifest_sha256=panel['panel_manifest_sha256'],
932:         same_source_status='PANEL_ONLY_INHERITED_HISTORY_SCALE_NOT_ATTESTED',
933:         gaps=['SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN'])
934:     try:
935:         from infrastructure.owned_io import SafeRoot
936:         manifest_path = Path(panel['panel_manifest_path'])
937:         raw = SafeRoot(manifest_path.parent).read_bytes(manifest_path.name, max_bytes=1024*1024)
938:         if hashlib.sha256(raw).hexdigest() != panel['panel_manifest_sha256']:
939:             raise ValueError('SCREEN_VOLUME_MANIFEST_CHANGED_DURING_READ')
940:         manifest = json.loads(raw)
941:         audit = rebound_native_evidence(manifest,
942:             required_session=str(context['market_session']),
943:             observed_at=timestamp(context['research_cutoff']))
944:         result['owner_unit_evidence'] = audit['unit_evidence']
945:         result['native_observation_status'] = audit['date_evidence']['observation_status']
946:         result['gaps'].extend(gap for gap in audit['gaps']
947:                              if gap != 'REBOUND_HISTORY_PRICE_CURRENCY_NOT_PROVEN')
948:         if audit['date_evidence']['observation_status'] == 'NATIVE_SOURCE_READ_RECORDED':
949:             native = audit['native_observation']
950:             result['native_scale_applied'] = native['fields']['trade']['scale_applied']
951:             result['scale_scope'] = native['scope']
952:             result['native_selected_dates'] = list(native['selected_dates'])
953:         # The existing owner reader deliberately returns NOT_PROVEN. Future
954:         # owner attestations need an explicit reader-contract change; arbitrary
955:         # extra manifest keys are never treated as a verified source contract.
956:     except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
957:         code = str(exc)
958:         if not re.fullmatch(r'(?:SCREEN|REBOUND)_[A-Z0-9_]+', code):
959:             code = type(exc).__name__
960:         result['gaps'].append('SCREEN_VOLUME_NATIVE_EVIDENCE_UNVERIFIED:' + code)
961:     result['gaps'] = sorted(set(result['gaps']))
962:     return result
963: 
964: 
965: def _screen_supplement_volume_evidence(supplement: Mapping[str, Any],
966:                                        required_sessions: list[str]) -> dict:
967:     """The native six-bar reader verifies identity, while units stay unknown."""
968:     return dict(status='NOT_PROVEN', unit_status='NOT_PROVEN', unit=None,
969:         scale_applied=1, source='PYTDX_EXHQ_CATEGORY_4_MARKET_71', native_field='trade',
970:         required_sessions=list(required_sessions), scope='ALL_SIX_REQUIRED_SESSIONS',
971:         source_sha256=supplement['raw_capture_sha256'],
972:         manifest_sha256=supplement['manifest_sha256'],
973:         same_source_status='SIX_NATIVE_BARS_SAME_SOURCE_UNIT_NOT_ATTESTED',
974:         gaps=['SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN'])
975: 
976: 
977: def read_rebound_screen(authority_root: Path | None, context: Mapping[str, Any]) -> dict:
978:     """Recompute the bounded REBOUND_V3 screen from the existing HK panel.
979: 
980:     The panel, its manifest and the date-specific security master are only
981:     read.  No task output, static longlist, symbol list or new market producer
982:     participates in this calculation. Every row from the supplied completed
983:     session is evaluated; only the 80%-of-prior-60-high and previous-five-day
984:     volume-ratio conditions decide strict/near qualification. Fully known rows
985:     failing both existing gates are also returned as exclusions with their
986:     exact gate values. Amount and close-to-low rebound remain observations.
987:     """
988:     if ('market_session' in context
989:             and not re.fullmatch(r'\d{8}', str(context.get('market_session') or ''))):
990:         return _screen_empty(context, ['SCREEN_MARKET_SESSION_UNVERIFIED'])
991:     try:
992:         context = screen_context(context)
993:     except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
994:         code = str(exc)
995:         if not re.fullmatch(r'(?:SCREEN|WORKSPACE)_[A-Z0-9_]+', code):
996:             code = type(exc).__name__
997:         return _screen_empty(context, ['SCREEN_SESSION_CONTEXT_UNVERIFIED:' + code])
998:     day = str(context.get('market_session') or '')
999:     if not re.fullmatch(r'\d{8}', day):
1000:         return _screen_empty(context, ['SCREEN_MARKET_SESSION_UNVERIFIED'])
1001:     if authority_root is None:
1002:         return _screen_empty(context, ['SCREEN_AUTHORITY_ROOT_NOT_BOUND'])
1003:     try:
1004:         root = Path(authority_root).expanduser().resolve()
1005:         try:
1006:             history_sessions = rebound_history_sessions(day)
1007:             prior60_session_dates = list(history_sessions.get('prior60') or [])
1008:             previous5_session_dates = list(history_sessions.get('previous5') or [])
1009:             if (len(prior60_session_dates) != 60 or len(set(prior60_session_dates)) != 60
1010:                     or any(not re.fullmatch(r'\d{8}', str(value)) for value in prior60_session_dates)
1011:                     or len(previous5_session_dates) != 5 or len(set(previous5_session_dates)) != 5
1012:                     or any(not re.fullmatch(r'\d{8}', str(value)) for value in previous5_session_dates)
1013:                     or not set(previous5_session_dates).issubset(prior60_session_dates)):
1014:                 return _screen_empty(context, ['SCREEN_HISTORY_CALENDAR_SESSIONS_INVALID'])
1015:         except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
1016:             return _screen_empty(context, ['SCREEN_HISTORY_CALENDAR_UNVERIFIED:' + type(exc).__name__])
1017:         panel, panel_gaps = _read_hk02_panel_witness(
1018:             root, day, research_cutoff=context.get('research_cutoff'),
1019:             required_history_date=previous5_session_dates[-1])
1020:         if panel is None:
1021:             return _screen_empty(context, ['SCREEN_PANEL_AUTHORITY_UNVERIFIED', *panel_gaps])
1022:         try:
1023:             from v3_shared_data.shared_data.store import StoreError
1024:             from upstreams.v3_shared_data.shared_data.hk_security_master import HKSecurityMasterReadError
1025:         except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
1026:             return _screen_security_master_failure(context, exc)
1027:         try:
1028:             master, master_manifest = _screen_security_master_witness(root, day)
1029:         except HKSecurityMasterReadError as exc:
1030:             return _screen_security_master_failure(context, exc, exc.diagnostic)
1031:         except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, StoreError) as exc:
1032:             return _screen_security_master_failure(context, exc)
1033:         if isinstance(master.get('read_diagnostic'), Mapping):
1034:             context = dict(context, security_master_read=dict(master['read_diagnostic']))
1035:         master_captured_at = timestamp(master.get('captured_at'))
1036:         if master_captured_at is None or master_captured_at > timestamp(context['research_cutoff']):
1037:             if isinstance(context.get('security_master_read'), Mapping):
1038:                 context = dict(context, security_master_read=dict(context['security_master_read'],
1039:                     status='INVALID', reason_code='HK_SECURITY_MASTER_AFTER_CUTOFF_OR_UNVERIFIED',
1040:                     validation_stage='RESEARCH_CUTOFF'))
1041:             return _screen_empty(context, ['SCREEN_SECURITY_MASTER_AFTER_CUTOFF_OR_UNVERIFIED'])
1042:         required_volume_sessions = [*previous5_session_dates, day]
1043:         panel_volume_evidence = _screen_panel_volume_evidence(panel, context, required_volume_sessions)
1044:         master_names = master.get('names') or {}
1045:         try:
1046:             import pandas as pd
1047:             frame = pd.read_parquet(panel['panel_path'], columns=[
1048:                 'trade_date_compact', 'code_norm', 'name', 'open', 'high', 'low',
1049:                 'close', 'amount', 'trade', 'pre_close',
1050:             ])
1051:         except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
1052:             return _screen_empty(context, ['SCREEN_PANEL_READ_FAILED:' + type(exc).__name__])
1053:         required = {'trade_date_compact', 'code_norm', 'high', 'low', 'close', 'amount', 'trade', 'pre_close'}
1054:         if not required.issubset(set(frame.columns)):
1055:             return _screen_empty(context, ['SCREEN_PANEL_SCHEMA_INVALID'])
1056:         frame = frame.copy()
1057:         frame['trade_date_compact'] = frame['trade_date_compact'].astype(str).str.zfill(8)
1058:         frame['code_norm'] = frame['code_norm'].astype(str).str.upper()
1059:         target = frame.loc[frame['trade_date_compact'] == day].copy()
```

## 当前 UI readback render — `app/apps/web/src/manager-selection/catalystObservationPanel.ts:471-478`

```
471:   function render(value: ManagerWorkspace): void {
472:     // Input identity is retained for audit; it is not a stock ranking.
473:     currentValue=value;loadedView=view;
474:     // Both fields came through the same workspace response/date/run validator.
475:     renderDailyChannels(dailyChannelsSection,value.daily_channels,value.date_bindings);
476:     renderResearchAttention(researchAttentionSection,value.research_attention as ResearchAttention|undefined,value.us_market_attention as UsMarketAttention|undefined,
477:       value.selection_diagnostics,value.us_mapping_research as UsMappingResearch|undefined);
478:     panel.dataset.inputIdentity=value.input_identity; panel.dataset.targetDate=value.target_trade_date;panel.dataset.readState='READY';
```

## 历史 CLI import and handoff registration — `app/ops/run_manager_daily_announcement.py:436-455`

```
436: def _import(args: argparse.Namespace) -> dict[str, Any]:
437:     run_id = args.evidence_run_id
438:     state_root = Path(args.research_state_root).expanduser().resolve(strict=True)
439:     from v4.manager_research.workspace_announcements import _handoff_root, validate_registered_handoff
440:     evidence_root = _handoff_root(SimpleNamespace(root=state_root), run_id)
441:     manifest = _load(evidence_root / "handoff_manifest.v1.json")
442:     product = _load(evidence_root / "analysis_product.json")
443:     validate_registered_handoff(SimpleNamespace(root=state_root), run_id,
444:         manifest.get("sha256"), product.get("sha256"), product)
445:     query = urlencode({"date": product["target_trade_date"],
446:                        "publication_date": product["publication_date"].replace("-", "")})
447:     envelope = {"schema_version": "v4.manager_research.announcement_analysis_import_ref.v1",
448:         "evidence_run_id": run_id, "handoff_manifest_sha256": manifest["sha256"],
449:         "product_sha256": product["sha256"]}
450:     body = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
451:     result = _request(args.api_base, "/api/v4/manager/research/announcements/analysis/import",
452:                       method="POST", payload=body)
453:     analysis = result.get("analysis")
454:     owner_receipt = validate_owner_analysis_import_receipt(result.get("owner_import_receipt"), product)
455:     if (not isinstance(analysis, dict) or analysis.get("status") != "VERIFIED"
```

## 历史 CLI registered handoff validation — `app/ops/run_manager_daily_announcement.py:481-500`

```
481: def _register_handoff(args: argparse.Namespace) -> dict[str, Any]:
482:     target = date_token(args.target_date)
483:     publication = _publication_iso(args.publication_date)
484:     if len(args.evidence_run_id) != 32 or any(c not in "0123456789abcdef" for c in args.evidence_run_id):
485:         raise ValueError("ANNOUNCEMENT_AGENT_EVIDENCE_RUN_ID_INVALID")
486:     state_root = Path(args.research_state_root).expanduser().resolve(strict=True)
487:     from v4.manager_research.workspace_announcements import _handoff_root, validate_registered_handoff
488:     from v4.manager_research.workspace_projection import digest
489:     store_ref = SimpleNamespace(root=state_root)
490:     evidence = _handoff_root(store_ref, args.evidence_run_id)
491:     capture = _load(evidence / "capture_receipt.json")
492:     catalog_path = evidence / "catalog_read.json"
493:     body_path = evidence / "body_corpus.json"
494:     catalog_read = _load(catalog_path)
495:     catalog = catalog_read.get("catalog") if isinstance(catalog_read.get("catalog"), dict) else {}
496:     terminal_capture = validate_terminal_body_capture(
497:         evidence, catalog_read, target, publication, expected_run_id=args.evidence_run_id)
498:     if (capture.get("status") != terminal_capture.get("status")
499:             or capture.get("evidence_run_id") != args.evidence_run_id
500:             or capture.get("target_trade_date") != target
```

## 历史 product builder — `app/v4/manager_research/announcement_analysis.py:936-960`

```
936: def build_product(semantic_catalog: Mapping[str, Any], body_corpus: Mapping[str, Any],
937:                   catalog_read: Mapping[str, Any], *, semantic_sha256: str,
938:                   body_sha256: str, verified_inputs: list[Mapping[str, Any]],
939:                   pdf_derivative_sha256s: Mapping[str, str] | None = None,
940:                   target_trade_date: str | None = None,
941:                   publication_date: str | None = None,
942:                   terminal_body_capture: Mapping[str, Any] | None = None) -> dict[str, Any]:
943:     """Build an analysis projection bound to the supplied exact-date catalog.
944: 
945:     The sealed 2026-09-29 product remains readable through its original input
946:     checks. New dates require raw input hashes plus canonical JSON hashes and
947:     are validated against the source catalog's exact article and issuer IDs.
948:     """
949:     if (target_trade_date is None and publication_date is None
950:             and catalog_read.get("target_trade_date") == SUPPORTED_TARGET_DATE
951:             and catalog_read.get("publication_date") == SUPPORTED_PUBLICATION_DATE
952:             and semantic_catalog.get("target_research_date") == "2026-09-30"):
953:         return _build_legacy_product(semantic_catalog, body_corpus, catalog_read,
954:             semantic_sha256=semantic_sha256, body_sha256=body_sha256,
955:             verified_inputs=verified_inputs,
956:             pdf_derivative_sha256s=pdf_derivative_sha256s or {})
957: 
958:     target = _date_field(target_trade_date or catalog_read.get("target_trade_date"),
959:                          "ANNOUNCEMENT_ANALYSIS_TARGET_DATE_INVALID")
960:     publication = _publication_date(publication_date or catalog_read.get("publication_date"))
```

## 历史 exact owner import/readback — `app/v4/manager_research/announcement_analysis.py:1092-1120`

```
1092: def import_product(service: Any, product: Mapping[str, Any]) -> dict[str, Any]:
1093:     """Atomically import one validated analysis under the existing owner.
1094: 
1095:     Identical bytes are an idempotent no-op. A different existing product is
1096:     preserved and requires a separate reviewed replacement workflow.
1097:     """
1098:     if not isinstance(product, Mapping):
1099:         raise ValueError("ANNOUNCEMENT_ANALYSIS_PRODUCT_IDENTITY_INVALID")
1100:     target = date_token(product.get("target_trade_date"))
1101:     publication = _publication_date(product.get("publication_date"))
1102:     catalog_read = service.get_announcement_date_catalog(target, publication)
1103:     catalog = _assert_catalog_readback(catalog_read, target, publication)
1104:     checked = validate_product(product, target_trade_date=target,
1105:         publication_date=publication, catalog=catalog)
1106:     path = product_path(service.store, target, publication)
1107:     with service.store._transaction(target, "announcement-analysis-" + publication.replace("-", "")):
1108:         previous = service.store._read(path)
1109:         if previous is not None:
1110:             previous = validate_product(previous, target_trade_date=target,
1111:                 publication_date=publication, catalog=catalog)
1112:             if previous.get("sha256") != checked.get("sha256"):
1113:                 raise ValueError("ANNOUNCEMENT_ANALYSIS_PRODUCT_EXISTS")
1114:             state = "ALREADY_IMPORTED"
1115:         else:
1116:             service.store._write_atomic(path, checked)
1117:             state = "IMPORTED"
1118:     result = read(service, target, publication)
1119:     if result.get("analysis", {}).get("status") != "VERIFIED":
1120:         raise ValueError("ANNOUNCEMENT_ANALYSIS_IMPORT_READBACK_FAILED")
```

## 历史 import API and owner receipt branch — `app/apps/api/v35_api/manager_research_router.py:350-380`

```
350:     async def import_announcement_analysis(request: Request) -> dict[str, Any]:
351:         if not request.headers.get("origin"):
352:             raise HTTPException(status_code=403, detail="same-origin header is required")
353:         _same_origin(request)
354:         content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
355:         if content_type != "application/json":
356:             raise HTTPException(status_code=415, detail="announcement analysis import requires application/json")
357:         envelope = await _bounded_json_body(request, limit=16 * 1024 * 1024)
358:         if set(envelope) != {"schema_version", "evidence_run_id", "handoff_manifest_sha256", "product_sha256"} or envelope.get("schema_version") != "v4.manager_research.announcement_analysis_import_ref.v1":
359:             raise HTTPException(status_code=422, detail="announcement analysis import envelope is invalid")
360:         try:
361:             from v4.manager_research.workspace_announcements import validate_registered_handoff
362:             registered = validate_registered_handoff(service.store, envelope.get("evidence_run_id"),
363:                 envelope.get("handoff_manifest_sha256"), envelope.get("product_sha256"))
364:             product = registered["product"]
365:             from v4.manager_research.workspace_announcements import validate_agent_judgment_receipt
366:             agent_receipt = validate_agent_judgment_receipt(product.get("agent_judgment_receipt"), product)
367:             imported = await run_in_threadpool(service.import_announcement_analysis, product)
368:             analysis = imported.get("analysis") if isinstance(imported, dict) else None
369:             if not isinstance(analysis, dict) or analysis.get("status") != "VERIFIED" or analysis.get("product_sha256") != product.get("sha256"):
370:                 raise ValueError("ANNOUNCEMENT_ANALYSIS_IMPORT_READBACK_FAILED")
371:             from v4.manager_research.announcement_analysis import product_path
372:             owner_path = product_path(service.store, product["target_trade_date"], product["publication_date"]).with_name("owner_import_receipt.v1.json")
373:             existing = service.store._read(owner_path)
374:             if existing is not None:
375:                 from v4.manager_research.workspace_announcements import validate_owner_analysis_import_receipt
376:                 owner_receipt = validate_owner_analysis_import_receipt(existing, product)
377:                 if (owner_receipt.get("parent_task_id") != agent_receipt.get("parent_task_id")
378:                         or owner_receipt.get("parent_run_id") != agent_receipt.get("parent_run_id")):
379:                     raise ValueError("ANNOUNCEMENT_ANALYSIS_OWNER_RECEIPT_CONFLICT")
380:             else:
```

## 历史 service owner — `app/v4/manager_research/service.py:433-436`

```
433:     def import_announcement_analysis(self, product: Mapping[str, Any]) -> dict[str, Any]:
434:         """Atomically import one reviewed, exact-source analysis product."""
435:         from .announcement_analysis import import_product
436:         return import_product(self, product)
```
