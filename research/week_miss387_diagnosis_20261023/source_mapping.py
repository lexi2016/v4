"""Independent character lexer + shunting-yard parser for source mapping.
Does not import or call original Parser for its parse. Production AST is read
only afterwards as the comparison object. No market data or formula evaluation.
"""
import json,re
from pathlib import Path
from registry_bridge import w
from diagnose import OUT,PRIOR

PRE={'OR':1,'AND':2,'=':3,'<':3,'>':3,'<=':3,'>=':3,'+':4,'-':4,'*':5,'/':5,'u+':6,'u-':6}
def tokens(s):
 out=[];i=0
 while i<len(s):
  c=s[i]
  if c.isspace():i+=1;continue
  if c=="'":
   j=s.index("'",i+1);out.append(('prefix',s[i+1:j]));i=j+1;continue
  if c.isdigit() or c=='.' and i+1<len(s) and s[i+1].isdigit():
   j=i+1
   while j<len(s) and (s[j].isdigit() or s[j]=='.'):j+=1
   out.append(('number',float(s[i:j])));i=j;continue
  if c.isalpha() or c=='_':
   j=i+1
   while j<len(s) and (s[j].isalnum() or s[j]=='_'):j+=1
   t=s[i:j];out.append(('op' if t in ['AND','OR'] else 'name',t));i=j;continue
  if s[i:i+2] in ['<=','>=']:out.append(('op',s[i:i+2]));i+=2;continue
  if c in '+-*/<>=(),':out.append(('punct' if c in '(),' else 'op',c));i+=1;continue
  raise ValueError('UNSUPPORTED_CHARACTER:'+repr(c))
 return out

def parse(s,normalize=None):
 ts=tokens(s);stack=[];vals=[];previous='start';normalize=normalize or {}
 def reduce(op):
  if op in ['u+','u-']:vals.append(('unary',op[1:],(vals.pop(),)));return
  right=vals.pop();left=vals.pop();vals.append(('binary',op,(left,right)))
 for i,(kind,v) in enumerate(ts):
  if kind in ['number','prefix']:vals.append((kind,v,()));previous='value';continue
  if kind=='name':
   if i+1<len(ts) and ts[i+1][1]=='(':stack.append(('func',v));previous='function'
   else:vals.append(('name',normalize.get(v,v),()));previous='value'
   continue
  if v=='(':stack.append(['paren',1 if previous=='function' else None]);previous='open';continue
  if v==',':
   while stack and stack[-1][0]!='paren':reduce(stack.pop())
   assert stack and stack[-1][1] is not None,'COMMA_OUTSIDE_FUNCTION';stack[-1][1]+=1;previous='comma';continue
  if v==')':
   while stack and not isinstance(stack[-1],list):reduce(stack.pop())
   marker=stack.pop();assert marker[0]=='paren'
   if stack and isinstance(stack[-1],tuple) and stack[-1][0]=='func':
    name=stack.pop()[1];n=marker[1];assert n is not None and len(vals)>=n;children=tuple(vals[-n:]);del vals[-n:];vals.append(('call',name,children))
   previous='value';continue
  op='u'+v if v in ['+','-'] and previous in ['start','open','comma','operator'] else v
  while stack and isinstance(stack[-1],str) and (PRE[stack[-1]]>PRE[op] or PRE[stack[-1]]==PRE[op] and not op.startswith('u')):reduce(stack.pop())
  stack.append(op);previous='operator'
 while stack:reduce(stack.pop())
 assert len(vals)==1,'EXPRESSION_STACK';return vals[0]

def source_assignments(path,mode):
 rows=[]
 for statement in Path(path).read_text(encoding='utf-8-sig').split(';'):
  text=statement.strip()
  if not text:continue
  # Locate assignment separator at nesting level0 before any opening parenthesis.
  cut=text.find(':')
  if cut<0 or '(' in text[:cut]:continue
  name=text[:cut].strip()
  if not name or not all(c.isalnum() or c=='_' for c in name):continue
  expr=text[cut+2:] if text[cut:cut+2]==':=' else text[cut+1:]
  depth=0;quote=False;end=len(expr)
  for i,c in enumerate(expr):
   if c=="'":quote=not quote
   if quote:continue
   if c=='(':depth+=1
   elif c==')':depth-=1
   elif c==',' and depth==0:end=i;break
  expr=expr[:end].strip()
  if mode=='B' and 'DRAWNULL' in expr:continue
  rows.append((name,expr))
 return rows

def normal(node,reverse=None):
 reverse=reverse or {};return (node.kind,reverse.get(node.value,node.value) if node.kind=='name' else node.value,tuple(normal(x,reverse) for x in node.children))
def dependencies(node):
 return ({node[1]} if node[0]=='name' else set()).union(*(dependencies(x) for x in node[2]))

def main():
 b=w.load(PRIOR/'EXECUTION_CONTRACT.json')['input_identity'];a=w.module(b['model_a'],'mapped_original');k=w.module(b['model_b'],'mapped_b');ap=a.compile_original(b['formula_a']);bp,_,rev=k.program();allrows=[]
 for mode,path,prod,reverse,normalize in [('A',b['formula_a'],dict(ap),{},{}),('B',k.FORMULA,bp,rev,{'CLOSE':'C','HIGH':'H','LOW':'L'})]:
  independent=source_assignments(path,mode);assert [n for n,_ in independent]==list(prod),'ASSIGNMENT_ORDER:'+mode
  for name,text in independent:
   tree=parse(text,normalize);expected=normal(prod[name],reverse);assert tree==expected,'AST_MISMATCH:'+mode+':'+name
   allrows.append(dict(model=mode,assignment=name,source_expression=text,independent_ast=tree,production_ast_equal=True,dependencies=sorted(dependencies(tree))))
 assert len([x for x in allrows if x['model']=='A'])==255
 w.save(OUT/'INDEPENDENT_SOURCE_MAPPING.json',dict(status='PASS_INDEPENDENT_TEXT_TO_AST_STRUCTURE',strategy='INDEPENDENT_CHARACTER_LEXER_SHUNTING_YARD_VS_ORIGINAL_PRATT',assignments=allrows,source_sha256={str(b['formula_a']):w.sha(b['formula_a']),str(k.FORMULA):w.sha(k.FORMULA)},scope='255 A assignments and all compiled B source assignments, including ten-route buy mappings; numerical reference can be reused because normalized AST is identical',limitations=['No native TDX/Futu runtime parity','Compiler/parser result does not establish historical PIT or raw field units'],**w.FLAGS))
 print(json.dumps({'status':'PASS_INDEPENDENT_TEXT_TO_AST_STRUCTURE','A_assignments':sum(x['model']=='A' for x in allrows),'B_assignments':sum(x['model']=='B' for x in allrows)}))
if __name__=='__main__':main()
