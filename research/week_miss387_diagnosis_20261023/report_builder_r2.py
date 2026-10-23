"""Presentation-only deterministic projection; consumes frozen diagnostics only."""
import json,re
from collections import Counter,defaultdict
from registry_bridge import w
from diagnose import OUT,HERE,PRIOR,readcsv
from reference import render

def funcs(node):
 out={node.value} if node.kind=='call' else set()
 for child in node.children:out|=funcs(child)
 return out

def mapping():
 b=w.load(PRIOR/'EXECUTION_CONTRACT.json')['input_identity'];a=w.module(b['model_a'],'report_source_a');k=w.module(b['model_b'],'report_source_b');ap=dict(a.compile_original(b['formula_a']));bp,_,rev=k.program()
 texta=__import__('pathlib').Path(b['formula_a']).read_text(encoding='utf-8-sig');source_a=re.findall(r'(?:^|;)\s*([A-Z_][A-Z_0-9]*)\s*(?::=|:)',texta)
 textb=__import__('pathlib').Path(k.FORMULA).read_text(encoding='utf-8-sig');source_b=re.findall(r'(?:^|;)\s*([^\W\d]\w*)\s*(?::=|:)\s*([^;]*)',textb)
 assert source_a==list(ap)
 bf=sorted(set().union(*(funcs(n) for n in bp.values())));af=sorted(set().union(*(funcs(n) for n in ap.values())))
 assert 'NOT' not in bf and 'HHVBARS' not in bf
 proof=dict(a_assignment_count=len(ap),a_source_order_matches_ast_names=True,b_assignment_count=len(bp),a_reachable_functions=af,b_reachable_functions=bf,b_NOT_HHVBARS_unreachable=True,b_source_assignment_names=[n for n,_ in source_b],shared_parser=True,source_text_to_ast_full_semantic_equivalence='INDEPENDENT_SOURCE_MAPPING.json verifies normalized AST structure; native runtime not verified',platform_engine_equivalence='CANNOT_CONFIRM',duplicate_date_guard={'projection':'engine.reconstruct asserts sorted(set(dates)) before dates.index','native_day':'engine.day asserts sorted(set(dates))','original_selector':'count retained; duplicate issue enters DATA_INVALID_OR_UNKNOWN'},noncausal_metadata={'NAME_MISSING':'FORMULAS_DO_NOT_READ_NAME; identity risk only','SHORT_HISTORY_LT200':'FLAG_ONLY_NOT_AUTOMATIC_CAUSE; actual dependency values/unknown separately checked'})
 return ap,bp,rev,proof

def category(expr,owner):
 out=[]
 if re.search(r'JVAL|KVAL|DVAL|BKRSI|ZRSI|\bJ\b|\bK\b|\bD\b',expr):out.append('J_KDJ_RSI条件')
 if re.search(r'WHT0|YEL0|白线|黄线',expr):out.append('白黄线趋势或距离')
 if re.search(r'BBI',expr):out.append('BBI位置或趋势')
 if re.search(r'VOL|AMOUNT|AMTR|VMA|放量|缩|量|SHR',expr):out.append('成交量额或缩放量')
 if re.search(r'PCT|PCLOSE|涨幅|突破|HIGH20|BRKPH|FUND',expr):out.append('涨幅突破或阳线结构')
 if 'brick_' in expr or re.search(r'BRKTYPE|BKSTRRED|BKRED|BKRES|BKBUY|BRKV',expr):out.append('砖图反包结构')
 if re.search(r'RISK|FRESH|CONT0|FCON|CCON|HOTFAR|GAIN60|RET20|MULTI|STABLE|VOLSTB',expr):out.append('分数角色风险或热度')
 if not out:out.append('其他冻结形态或时序门')
 return out

def blockers(row,model,nodes,reverse,root):
 assignments=row['signal']['a_assignments' if model=='A' else 'b_assignments'];visited=set();leaves=[]
 def val(node,owner,path):
  ats={x['path'].removeprefix(owner):x for x in assignments[owner]['atoms']}
  if path in ats:return ats[path]['value']
  if node.kind=='name':return assignments.get(reverse.get(node.value,node.value),{}).get('value')
  if node.kind=='number':return node.value
  if node.kind=='binary' and node.value in ['AND','OR']:
   x,y=[val(c,owner,path+'/'+str(i)) for i,c in enumerate(node.children)]
   if node.value=='AND':return 0 if x==0 or y==0 else None if x is None or y is None else 1
   return 1 if (x is not None and x!=0) or (y is not None and y!=0) else None if x is None or y is None else 0
  return None
 def walk(node,owner,path='',trail=()):
  key=(owner,path)
  if key in visited:return
  visited.add(key);v=val(node,owner,path)
  if node.kind=='name':
   name=reverse.get(node.value,node.value)
   if name in nodes:walk(nodes[name],name,'',trail+(owner,))
   return
  if node.kind=='binary' and node.value in ['AND','OR']:
   for i,child in enumerate(node.children):
    cv=val(child,owner,path+'/'+str(i))
    # False AND: failed conjuncts; false OR: every disjunct. True
    # nodes occur through negation; retain only actual true witnesses.
    if v==0 and cv==0 or v is not None and v!=0 and cv is not None and cv!=0:walk(child,owner,path+'/'+str(i),trail)
   return
  atom=next((x for x in assignments[owner]['atoms'] if x['path']==owner+path),None)
  if atom:
   margin=None if atom['lhs'] is None or atom['rhs'] is None else atom['lhs']-atom['rhs']
   leaves.append(dict(model=model,root=root,owner=owner,dependency_trail=list(trail),**atom,numeric_margin_lhs_minus_rhs=margin,margin_interpretation='Use operator and value; equality uses exact comparison, not margin tolerance',categories=category(atom['expression'],owner),causal_scope='LOGICAL_WITNESS_WITHIN_SAVED_FALSE_GATE_NOT_MARKET_CAUSALITY'))
  else:leaves.append(dict(model=model,root=root,owner=owner,dependency_trail=list(trail),path=path,expression=render(node,reverse),operator='VALUE',lhs=v,rhs=0,value=v,numeric_margin_lhs_minus_rhs=v,categories=category(render(node,reverse),owner),causal_scope='OPAQUE_VALUE_GATE_FULL_DEPENDENCIES_IN_DETAILS'))
 walk(nodes[root],root);return leaves

def main():
 rows=[json.loads(x) for x in (OUT/'DETAILS.jsonl').read_text().splitlines()];summary=w.load(OUT/'SUMMARY.json');priorrows={(x['selection_date'],x['code']):x for x in readcsv(OUT/'DIAGNOSIS_387.csv')};ap,bp,rev,proof=mapping();data=[];atomsout=[];PUB=OUT/'presentation_r2';PUB.mkdir(exist_ok=False);counts=defaultdict(Counter);overall=Counter();nameissues=Counter()
 for r in rows:
  a=r['signal']['a_key_values'];root='ENTRYPOOL' if a['ENTRYPOOL']==0 else 'B2ROLE';a_atoms=blockers(r,'A',ap,{},root)
  if root!='ENTRYPOOL':a_atoms+=blockers(r,'A',ap,{},'B3ROLE')
  b_atoms=[]
  for rule in r['signal']['b_rules']:
   if rule['rule_id']=='BRICK_FANBAO':
    for at in rule['atoms']:
     if at['value']==0:b_atoms.append(dict(model='B',root='BRICK_FANBAO',owner='BRICK_FANBAO',**at,numeric_margin_lhs_minus_rhs=at['lhs']-at['rhs'],categories=['砖图反包结构'],causal_scope='FAILED_REQUIRED_BRICK_CONJUNCT'))
   else:b_atoms+=blockers(r,'B',bp,rev,rule['source_name'])
  allats=a_atoms+b_atoms;tags=sorted({c for x in allats for c in x['categories']})
  overall.update(tags);counts[r['selection_date']].update(tags);nameissues.update(r['input_audit']['issues'])
  def describe(at):
   if at['lhs'] is not None and at['rhs'] is not None:return f"{at['expression']}：左={at['lhs']:.6g}、右={at['rhs']:.6g}、差={at['numeric_margin_lhs_minus_rhs']:.6g}、结果={at['value']}"
   return at['expression']+'：结果='+str(at['value'])
  atext=f"A的{root}门=0。"+'；'.join(describe(x) for x in a_atoms[:8])+f"。FRESH={a['FRESH']:.3f}（门槛>=70），CONT0={a['CONT0']:.3f}（>=70），RISK0={a['RISK0']:.3f}（最终要求<45），FCON={a['FCON']:.0f}，CCON={a['CCON']:.0f}。完整必要阻断路径见ATOMIC_BLOCKERS.jsonl；各OR支路需结合父树理解。"
  btext=[]
  for rule in r['signal']['b_rules']:
   aa=[x for x in b_atoms if x['root']==rule['source_name'] or rule['rule_id']=='BRICK_FANBAO' and x['root']=='BRICK_FANBAO']
   btext.append(rule['rule_id']+'整体='+rule['status']+'；必要阻断见：'+'；'.join(describe(x) for x in aa[:3]))
  src=priorrows[(r['selection_date'],r['code'])];data.append({**src,'atomic_reason_categories':'|'.join(tags),'a_explanation_zh':atext,'b_explanation_zh':'\n'.join(btext),'input_certification_note_zh':'本地六字段/精确信号bar与封存复现通过；历史资格/名称时点/available_at/跨商单位及原平台引擎一致性CANNOT_CONFIRM。'})
  atomsout.append(dict(selection_date=r['selection_date'],signal_asof=r['signal_asof'],code=r['code'],a_false_gate=root,a_blockers=a_atoms,b_false_routes=b_atoms,note='D-1 technical logical explanations only; distinct-category counts are multilabel and cannot sum to387'))
 with (PUB/'ATOMIC_BLOCKERS.jsonl').open('x') as f:
  for x in atomsout:f.write(json.dumps(x,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
 w.csvwrite(PUB/'USER_EXPLANATIONS_387.csv',data)
 for d in summary['daily_counts']:w.csvwrite(PUB/('USER_EXPLANATIONS_'+d+'.csv'),[x for x in data if x['selection_date']==d])
 perday=[dict(selection_date=d,events=sum(x['selection_date']==d for x in data),primary_reasons=dict(Counter(x['primary_reason'] for x in data if x['selection_date']==d)),atomic_multilabel_event_counts=dict(counts[d])) for d in sorted(summary['daily_counts'])]
 present={'daily':perday,'overall_atomic_multilabel_event_counts':dict(overall),'local_issue_counts':dict(nameissues),'posthoc_D_counts':summary['posthoc_D_counts'],'notes':['Categories count distinct code/date with >=1 saved blocking predicate in category; multilabel totals do not sum to387','Numeric margin=lhs-rhs. Operator and Boolean truth retained; no tolerance-based threshold reinterpretation','No new market inputs or formula numerical replay','385ENTRYPOOL_FALSE is intermediate gate; per-row A/B atom paths and category counts are the next explanatory layer'],**w.FLAGS}
 w.save(PUB/'PRESENTATION_SUMMARY.json',present);w.save(PUB/'SEMANTIC_SCOPE_EVIDENCE.json',proof)
 text='''# 387条共同漏选技术诊断\n\n已逐条解释342只股票、387个股票×日期事件，五日分别92/76/64/65/90条。诊断复算与原封存A255终值、B十路状态、两个candidate及输入SHA全部一致；独立数值解释器差异0。这仅支持冻结离线数值实现的解释，尚待独立Reviewer验收。\n\nA的中间门主因：385条ENTRYPOOL=0；2条进入ENTRYPOOL后未过角色门：2026-10-19正强股份301119.SZ（10/16信号，FRESH=41、CONT0=41、FCON=0）；2026-10-21上海九百600838.SH（10/20信号，FRESH=30、CONT0=40、FCON=0）。两条RISK0均0，不能写成风险过高；FRESH/CONT0门槛均70。入口false行也保留全部角色/风险值，不假设后续门可过。\n\n385入口false继续沿保存的AND/OR依赖树拆到实际比较：ATOMIC_BLOCKERS.jsonl列A必要阻断路径及B十路各自false门的表达式、阈值、左右值、运算符与差值。USER_EXPLANATIONS_387.csv及每日USER_EXPLANATIONS_日期.csv为逐条中文阅读版。PRESENTATION_SUMMARY.json逐日/总体统计J/KDJ/RSI、白黄线、BBI、量额、涨幅突破、砖反包、风险/角色等原子类别。类别按事件去重、允许多标签，合计不能当387的互斥分母。false AND提取失败合取项，false OR展开全部失败分支；不是任意false叶子都解释成最终未选的独立原因。\n\n各类别总体事件计数：\n'''
 for key,v in sorted(overall.items()):text+=f'- {key}：{v}\n'
 text+='\n数据有效性与实现核验分轴：六字段、精确信号bar、RAW/事件前缀、源分支、重复/非有限/零量、历史长度与warmup逐条留证。历史上市日/资格/名称时点、available_at及完整跨商volume/amount单位均CANNOT_CONFIRM；NO/NO不证明没有数据/实现风险。name缺失不进入原公式，不能称造成漏选。SHORT_HISTORY仅是元信息风险，真实未知依赖另列。\n\n数值Reference共享parser AST，不共享原计算helper；另由INDEPENDENT_SOURCE_MAPPING.json的独立字符lexer+shunting-yard验证原文到规范AST结构一致（A255、B50赋值）；通达信/富途原引擎仍未验证。原生客户端全公式一致性CANNOT_CONFIRM。B的NOT/HHVBARS在活动冻结AST不可达；A相应语义按其原实现保留。重建器在dates.index之前对projection/native日期sorted(set)断言，重复键fail closed。未改变原公式、模型、输入或旧封存输出。\n\n同公式上涨当天D的后验触发：A=71、B=256条。D增加当日价格/量/事件信息，不能解释成D-1可预测或模型优化。公告/新闻为catalyst独立证据轴，不能当作公式技术原因。\n\n状态IMPLEMENTED_PENDING_INDEPENDENT_REVIEW；RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。\n'
 (PUB/'TECHNICAL_REPORT.md').write_text(text)
 w.save(PUB/'PRESENTATION_MANIFEST.json',{str(p):w.sha(p) for p in [PUB/'ATOMIC_BLOCKERS.jsonl',PUB/'USER_EXPLANATIONS_387.csv',PUB/'PRESENTATION_SUMMARY.json',PUB/'SEMANTIC_SCOPE_EVIDENCE.json',PUB/'TECHNICAL_REPORT.md',*[PUB/('USER_EXPLANATIONS_'+d+'.csv') for d in summary['daily_counts']]]})
 print(json.dumps({'presentation_rows':len(data),'atomic_multilabel_event_counts':dict(overall),'local_issues':dict(nameissues)},ensure_ascii=False))
if __name__=='__main__':main()
