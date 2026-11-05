"""Write the pre-outcome source, rule and 87D mapping evidence."""
import hashlib,json
import common as c

c.bindings();features=c.feature_map();assert len(features)==87 and len({x['feature'] for x in features})==87
s={'status':'PRE_OUTCOME_SOURCE_AND_FEATURE_MAPPING_FROZEN','feature_order_sha256':c.ORDER_SHA,'features':features,
 'source_identities':{'panel_generation':c.GEN,'panel_sha256_producer_declared':c.PANEL_SHA,'panel_receipt_sha256':c.MANIFEST_SHA,'parent_model_sha256':c.PARENT_SHA,'profile_sha256':c.PROFILE_SHA,'calendar_sha256':c.CALENDAR_SHA,'canonical_formula_sha256':c.CANON_SHA,
   'p52_rule_member_sha256':'67ecd38826a633bf79be3a804f42716ec5afe72590d7844d68c706f4a68e2637',
   'p52_personal_member_sha256':'c5111ff2f91a72944d701f4723bf34d6c3c7be09a2cc42bf7247e3971d7b3a95',
   'p58_step5_member_sha256':'2dd05ec69ca3cb082dc66d6a2acccf42ae0b418350443cf52f4f83d85adb8c12',
   'v192_fast_builder_member_sha256':'21aa7ec6bbd0698d056a8b8137cdc9ebfd08e73f8f8223030263a16504698348'},
 'cohort':{'version':'P52_CAUSAL_BY_STOCK_RISK_FIRST_MAPPED_V1','source':'P5_2_PULLBACK_RULE_ENGINE.py',
   'anchors':'ACT_FUND_K OR VIOLENT_K OR BREAKOUT_K OR CONFIRMED_BUILDUP_WAVE; strictly previous stock bar, most recent qualifying anchor',
   'candidate':'original P52 A_SHALLOW_STRONG/B_NORMAL_SHRINK/C_DEEP_WASH_RECLAIM with stock-local lagged q35 and bars-since-anchor 1..15',
   'risk_priority':'original D/E or HIGH_CLIMAX risk recorded before candidate inclusion; unknown input remains UNKNOWN',
   'boundary':'P52 source flat rolling/shift/ffill is made per-stock; P52 warmup respected; QFQ valid-price, volume and finite reference masks',
   'groups':'ts_code + anchor_date; after train fit, any target test row sharing a new-fit event_group excluded from main OOS; counts retained',
   'limitations':'current-asof panel, P52 source, original P59 model and domain differ; exact 87D C-event parity CANNOT_CONFIRM'},
 'score':{'uniform':'same updated backbone + 0.42*(shared alpha + sum(shared beta * observed P59 Z))',
          'personal':'same updated backbone + 0.42*(stock alpha + sum(stock beta * observed P59 Z))',
          'original':'parent model.predict on identical mapped features, with original default behavior explicitly reported',
          'unknown_dimension':'excluded from sum as unobserved; not an observed zero','z_dim_missing_policy':'if any input required by a Z coordinate is unknown, omit that whole coordinate for both uniform and personal',
          'uniform_prior':'parent global_prior_intercept_ and global_prior_slopes_; train one pooled direct-rank ridge posterior',
          'personal_prior':'same parent per-stock alpha/beta; update only matured 10/16 stock events, original tau, low sample shrink and beta clips',
          'fusion_scale':0.42,'primary_comparison':'personal versus uniform, identical updated backbone'},
 'causal_cutoff':'all features <= signal close; W2 posteriors labels through 20241231 and upstream market snapshot <=20261015, first availability CANNOT_CONFIRM',
 'no_test_y_read':'TRUE until post-registration scores/Top10 slots are written and hashed','source_formula_parity':'V192 canonical structural formula matches by source; warmups and domain differences documented, not certified C-event parity'}
path=c.ROOT/'FEATURE_MAP_PREFLIGHT.json';path.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
missing=[x['feature'] for x in features if x['mapping']=='UNKNOWN_NAMED_V31_PRODUCER_NOT_DELIVERED'];req={'status':'UPSTREAM_SOURCE_REQUEST_NO_BLOCKING_WAIT','missing_function':'engineer_phase5_9_transfer_columns','missing_exact_model_features':missing,
 'request':'provide actual source bytes/sha for each 19 P53/JCB/tactic output and original P56 C-event KB production, required inputs, feature as-of and per-symbol semantics; never backfill from post-test data.',
 'known_absence':'search P5.2/P5.3/P5.8/P5.9 delivered py members; lineage points to a function absent from delivered CPU/full engine',
 'temporary_use':'NaN + frozen imputer for backbone; corresponding structural Z coordinates unobserved'}
(c.ROOT/'UPSTREAM_MISSING_SOURCE_REQUEST.json').write_text(json.dumps(req,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'features':len(features),'mapped_or_conditional':sum(not x['mapping'].startswith('UNKNOWN') for x in features),'unknown':sum(x['mapping'].startswith('UNKNOWN') for x in features),'missing_p59_named':len(missing),'sha256':c.sha(path)},ensure_ascii=False))
