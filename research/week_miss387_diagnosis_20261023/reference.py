"""Independent numerical interpreter for frozen parsed ASTs (not platform parity).
Shares grammar/AST only, no original numerical indicator helpers. Rolling uses
NumPy sliding windows, not production pandas; recurrences are scalar loops.
"""
import numpy as np

class Reference:
 def __init__(self,nodes,raw,mode,code='',reverse=None):
  self.nodes=dict(nodes);self.raw=raw;self.mode=mode;self.code=code;self.reverse=reverse or {};self.n=len(next(iter(raw.values())));self.memo={}
 def arr(self,x):return np.full(self.n,x,dtype=float) if np.isscalar(x) else np.asarray(x,dtype=float)
 def named(self,name):
  name=self.reverse.get(name,name)
  if name in self.raw:return self.raw[name]
  if name=='DRAWNULL':return self.arr(np.nan)
  if name=='CURRBARSCOUNT':return np.arange(self.n,0,-1,dtype=float)
  if name not in self.memo:self.memo[name]=self.expr(self.nodes[name])
  return self.memo[name]
 def truth(self,a):return np.isfinite(a)&(a!=0)
 def expr(self,node):
  if node.kind=='number':return self.arr(node.value)
  if node.kind=='prefix':return node.value
  if node.kind=='name':return self.named(node.value)
  if node.kind=='unary':return self.expr(node.children[0])*(-1 if node.value=='-' else 1)
  if node.kind=='call':return self.call(node.value,[self.expr(c) for c in node.children])
  a,b=[self.expr(c) for c in node.children];op=node.value;valid=np.isfinite(a)&np.isfinite(b)
  if op in ['AND','OR']:
   if self.mode=='A':return (self.truth(a)&self.truth(b) if op=='AND' else self.truth(a)|self.truth(b)).astype(float)
   if op=='AND':return np.where((a==0)|(b==0),0,np.where(valid,1,np.nan))
   return np.where(self.truth(a)|self.truth(b),1,np.where(valid,0,np.nan))
  if op in ['=','<','>','<=','>=']:
   z={'=':np.equal,'<':np.less,'>':np.greater,'<=':np.less_equal,'>=':np.greater_equal}[op](a,b)
   return np.where(valid,z.astype(float),0 if self.mode=='A' else np.nan)
  with np.errstate(all='ignore'):
   if op=='+':z=a+b
   elif op=='-':z=a-b
   elif op=='*':z=a*b
   elif op=='/':z=np.divide(a,b,out=self.arr(np.nan),where=valid&(b!=0))
   else:raise ValueError(op)
  z[~np.isfinite(z)]=np.nan;return z
 def rolling(self,a,p,op):
  # Independent array windows; A accepts partial finite history, B full windows.
  padded=np.pad(a,(p-1,0),constant_values=np.nan);windows=np.lib.stride_tricks.sliding_window_view(padded,p)
  finite=np.isfinite(windows);count=finite.sum(axis=1);out=self.arr(np.nan)
  good=count>0 if self.mode=='A' else count==p
  if op in ['MA','SUM']:s=np.where(finite,windows,0).sum(axis=1);out[good]=s[good]/count[good] if op=='MA' else s[good]
  else:
   z=np.where(finite,windows,-np.inf if op=='HHV' else np.inf);out[good]=(z.max(axis=1) if op=='HHV' else z.min(axis=1))[good]
  return out
 def call(self,name,args):
  if name=='CODELIKE':return self.arr(float(self.code[:6].startswith(args[0])))
  a=args[0]
  if name=='ABS':return np.abs(a)
  if name=='NOT':return (~self.truth(a)).astype(float)
  if name in ['MIN','MAX']:return (np.minimum if name=='MIN' else np.maximum)(a,args[1])
  if name=='IF':return np.where(self.truth(a),args[1],args[2]) if self.mode=='A' else np.where(np.isfinite(a),np.where(a!=0,args[1],args[2]),np.nan)
  if name=='REF':
   offsets=args[1];ix=np.arange(self.n);ok=np.isfinite(offsets)&(offsets>=0)&(offsets==np.floor(offsets))&(offsets<=ix);out=self.arr(np.nan);out[ok]=a[ix[ok]-offsets[ok].astype(int)];return out
  if name=='CROSS':
   out=self.arr(0);v=np.isfinite(a[1:])&np.isfinite(a[:-1])&np.isfinite(args[1][1:])&np.isfinite(args[1][:-1]);z=(a[1:]>args[1][1:])&(a[:-1]<=args[1][:-1]);out[1:]=np.where(v,z.astype(float),0 if self.mode=='A' else np.nan);return out
  if name=='BARSLAST':
   out=self.arr(np.nan);last=None
   for i,x in enumerate(a):
    if self.mode=='B' and not np.isfinite(x):last=None
    elif np.isfinite(x) and x!=0:last=i
    out[i]=i-last if last is not None else i+1 if self.mode=='A' else np.nan
   return out
  if name in ['COUNT','EXIST','EVERY']:
   if self.mode=='A':
    p=int(args[1][0]);s=self.rolling(self.truth(a).astype(float),p,'SUM');return s if name=='COUNT' else (s>0).astype(float) if name=='EXIST' else ((s==p)&(np.arange(self.n)+1>=p)).astype(float)
   out=self.arr(np.nan)
   for i,p in enumerate(args[1]):
    if not np.isfinite(p) or p<0 or p!=int(p):continue
    width=i+1 if p==0 else int(p)
    if width>i+1:continue
    part=a[i-width+1:i+1]
    if np.isfinite(part).all():out[i]=np.count_nonzero(part)
   return out
  p=int(args[1][0])
  if name in ['EMA','SMA']:
   alpha=2/(p+1) if name=='EMA' else args[2][0]/p;out=self.arr(np.nan);prev=None;poison=False
   for i,x in enumerate(a):
    if not np.isfinite(x):
     if self.mode=='B' and (prev is not None or name=='EMA'):poison=True
     continue
    if poison:continue
    prev=x if prev is None else alpha*x+(1-alpha)*prev;out[i]=prev
   return out
  if name=='HHVBARS':
   out=self.arr(np.nan)
   for i in range(self.n):
    z=a[max(0,i-p+1):i+1]
    if np.isfinite(z).any():out[i]=len(z)-1-np.flatnonzero(z==np.nanmax(z))[-1]
   return out
  return self.rolling(a,p,name)

def render(node,reverse=None):
 reverse=reverse or {}
 if node.kind=='number':return format(node.value,'.12g')
 if node.kind=='prefix':return repr(node.value)
 if node.kind=='name':return reverse.get(node.value,node.value)
 if node.kind=='unary':return node.value+render(node.children[0],reverse)
 if node.kind=='call':return node.value+'('+','.join(render(x,reverse) for x in node.children)+')'
 return '('+render(node.children[0],reverse)+' '+node.value+' '+render(node.children[1],reverse)+')'

def scalar(a):
 x=float(a[-1]);return x if np.isfinite(x) else None

def atoms(node,reference,path='',seen=None):
 """All logical leaves, retaining AND/OR trees elsewhere. No causal claim for
 an individual false leaf under a satisfied OR. Values sampled at exact cutoff.
 """
 out=[]
 if node.kind=='binary' and node.value in ['=','<','>','<=','>=']:
  out.append(dict(path=path,expression=render(node,reference.reverse),operator=node.value,lhs=scalar(reference.expr(node.children[0])),rhs=scalar(reference.expr(node.children[1])),value=scalar(reference.expr(node))))
 elif node.kind=='call' and node.value in ['CROSS','NOT','EXIST','EVERY']:
  out.append(dict(path=path,expression=render(node,reference.reverse),operator=node.value,lhs=None,rhs=None,value=scalar(reference.expr(node))))
 for i,c in enumerate(node.children):out.extend(atoms(c,reference,path+'/'+str(i)))
 return out
