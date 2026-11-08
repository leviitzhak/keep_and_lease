"""Small causal Transformer with NumPy reverse-mode gradients and Adam.

No framework dependency. All projections, attention, normalization and value
head parameters are trained; finite-difference tests check the backward pass.
"""
import math
import hashlib
import numpy as np

def unbroadcast(g, shape):
    while g.ndim > len(shape): g = g.sum(axis=0)
    for i,s in enumerate(shape):
        if s == 1 and g.shape[i] != 1: g = g.sum(axis=i, keepdims=True)
    return g

class Tensor:
    def __init__(self,data,parents=(),back=None):
        self.data=np.asarray(data);self.parents=parents;self.back=back;self.grad=None
    @staticmethod
    def wrap(x): return x if isinstance(x,Tensor) else Tensor(x)
    def accumulate(self,g):
        self.grad = g if self.grad is None else self.grad+g
    def __add__(self,b):
        b=self.wrap(b)
        return Tensor(self.data+b.data,(self,b),lambda g:(self.accumulate(unbroadcast(g,self.data.shape)),b.accumulate(unbroadcast(g,b.data.shape))))
    __radd__=__add__
    def __neg__(self):return self*-1
    def __sub__(self,b):return self+-self.wrap(b)
    def __mul__(self,b):
        b=self.wrap(b)
        return Tensor(self.data*b.data,(self,b),lambda g:(self.accumulate(unbroadcast(g*b.data,self.data.shape)),b.accumulate(unbroadcast(g*self.data,b.data.shape))))
    __rmul__=__mul__
    def __pow__(self,p):return Tensor(self.data**p,(self,),lambda g:self.accumulate(g*p*self.data**(p-1)))
    def __matmul__(self,b):
        b=self.wrap(b)
        return Tensor(self.data@b.data,(self,b),lambda g:(self.accumulate(unbroadcast(g@np.swapaxes(b.data,-1,-2),self.data.shape)),b.accumulate(unbroadcast(np.swapaxes(self.data,-1,-2)@g,b.data.shape))))
    def sum(self,axis=None,keepdims=False):
        def back(g):
            if axis is not None and not keepdims:g=np.expand_dims(g,axis)
            self.accumulate(np.ones_like(self.data)*g)
        return Tensor(self.data.sum(axis=axis,keepdims=keepdims),(self,),back)
    def mean(self,axis=None,keepdims=False):
        n=self.data.size if axis is None else self.data.shape[axis]
        return self.sum(axis,keepdims)*(1/n)
    def tanh(self):
        y=np.tanh(self.data);return Tensor(y,(self,),lambda g:self.accumulate(g*(1-y*y)))
    def reshape(self,*shape):return Tensor(self.data.reshape(*shape),(self,),lambda g:self.accumulate(g.reshape(self.data.shape)))
    def transpose(self,*axes):return Tensor(self.data.transpose(*axes),(self,),lambda g:self.accumulate(g.transpose(np.argsort(axes))))
    def __getitem__(self,idx):
        def back(g):
            z=np.zeros_like(self.data);z[idx]+=g;self.accumulate(z)
        return Tensor(self.data[idx],(self,),back)
    def softmax(self):
        a=self.data-self.data.max(axis=-1,keepdims=True);y=np.exp(a);y/=y.sum(axis=-1,keepdims=True)
        return Tensor(y,(self,),lambda g:self.accumulate(y*(g-(g*y).sum(axis=-1,keepdims=True))))
    def backward(self):
        seen=set();order=[]
        def visit(x):
            if id(x) in seen:return
            seen.add(id(x))
            for p in x.parents:visit(p)
            order.append(x)
        visit(self);self.grad=np.ones_like(self.data)
        for t in reversed(order):
            if t.back is not None and t.grad is not None:t.back(t.grad)

def gelu(x):
    z=math.sqrt(2/math.pi)*(x+.044715*x*x*x)
    return .5*x*(1+(z.tanh() if isinstance(z,Tensor) else np.tanh(z)))

class Transformer:
    def __init__(self,seed=17,d=64,heads=4,layers=2,ff=128,dtype=np.float32):
        self.d=d;self.heads=heads;self.layers=layers;self.ff=ff;self.dtype=dtype
        rng=np.random.default_rng(seed);self.p={}
        def w(n,shape,scale=None):self.p[n]=(rng.normal(0,scale or 1/math.sqrt(shape[0]),shape)).astype(dtype)
        def b(n,size,val=0):self.p[n]=np.full(size,val,dtype=dtype)
        w('embed',(60,d));b('embed_b',d)
        for i in range(layers):
            k=f'L{i}.'
            for norm in ['n1','n2']:b(k+norm+'g',d,1);b(k+norm+'b',d)
            for n in ['q','k','v','o']:w(k+n,(d,d));b(k+n+'b',d)
            w(k+'f1',(d,ff));b(k+'f1b',ff);w(k+'f2',(ff,d));b(k+'f2b',d)
        b('final_g',d,1);b('final_b',d)
        w('head',(d,32));w('control',(3,32));b('head_b',32);w('out',(32,1),.01);b('out_b',1)
        self.adam_m={k:np.zeros_like(v) for k,v in self.p.items()};self.adam_v={k:np.zeros_like(v) for k,v in self.p.items()};self.step=0
        self.cache={}
    @property
    def parameter_count(self):return sum(v.size for v in self.p.values())
    def forward(self,x,valid,control,grad=False,encoded_only=False,read_index=-1):
        p={k:Tensor(v) for k,v in self.p.items()} if grad else self.p
        if grad:x=Tensor(x);control=Tensor(control)
        B,L=valid.shape;D=self.d;H=self.heads;dh=D//H
        def norm(z,g,b):
            mu=z.mean(axis=-1,keepdims=True);a=z-mu;var=(a*a).mean(axis=-1,keepdims=True)
            return a*((var+1e-5)**-.5)*p[g]+p[b]
        # Relative receipt-order positions; left padding does not change actual positions.
        pos=np.maximum(valid.cumsum(axis=1)-1,0)[...,None]
        freq=np.exp(np.arange(0,D,2)*(-math.log(10000)/D))
        pe=np.zeros((B,L,D),dtype=self.dtype);pe[:,:,0::2]=np.sin(pos*freq);pe[:,:,1::2]=np.cos(pos*freq)
        z=x@p['embed']+p['embed_b']+pe
        mask=np.where((np.arange(L)[None,:]<=np.arange(L)[:,None])[None,None,:,:] & valid[:,None,None,:],0.,-1e9).astype(self.dtype)
        for i in range(self.layers):
            k=f'L{i}.';a=norm(z,k+'n1g',k+'n1b')
            q=(a@p[k+'q']+p[k+'qb']).reshape(B,L,H,dh).transpose(0,2,1,3)
            kk=(a@p[k+'k']+p[k+'kb']).reshape(B,L,H,dh).transpose(0,2,3,1)
            v=(a@p[k+'v']+p[k+'vb']).reshape(B,L,H,dh).transpose(0,2,1,3)
            logits=(q@kk)*(1/math.sqrt(dh))+mask
            if grad:att=logits.softmax()
            else:
                att=np.exp(logits-logits.max(axis=-1,keepdims=True));att/=att.sum(axis=-1,keepdims=True)
            a=(att@v).transpose(0,2,1,3).reshape(B,L,D)
            z=z+a@p[k+'o']+p[k+'ob']
            a=norm(z,k+'n2g',k+'n2b');z=z+gelu(a@p[k+'f1']+p[k+'f1b'])@p[k+'f2']+p[k+'f2b']
        z=norm(z,'final_g','final_b')[:,read_index,:]
        if encoded_only:return z
        a=z@p['head']+control@p['control']+p['head_b']
        out=(a.tanh() if grad else np.tanh(a))@p['out']+p['out_b']
        return (out.reshape(B),p) if grad else out.reshape(B)
    def update(self,x,mask,c,y,lr=.001):
        self.cache.clear()
        pred,p=self.forward(x,mask,c,True);loss=((pred-y)**2).mean();loss.backward()
        g={k:v.grad for k,v in p.items()};norm=math.sqrt(sum(float((v*v).sum()) for v in g.values()));scale=min(1.,1./(norm+1e-12))
        self.step+=1
        for k in self.p:
            gg=g[k]*scale;self.adam_m[k]=.9*self.adam_m[k]+.1*gg;self.adam_v[k]=.999*self.adam_v[k]+.001*gg*gg
            self.p[k]-=lr*(self.adam_m[k]/(1-.9**self.step))/(np.sqrt(self.adam_v[k]/(1-.999**self.step))+1e-8)
        return float(loss.data)
    def save(self,path):np.savez_compressed(path,**self.p)
    def load(self,path):
        self.cache.clear()
        with np.load(path) as f:
            for k in self.p:self.p[k]=f[k].copy()

def batch(records,dtype=np.float32):
    L=max(len(r['tokens']) for r in records);x=np.zeros((len(records),L,60),dtype=dtype);mask=np.zeros((len(records),L),bool)
    for i,r in enumerate(records):x[i,-len(r['tokens']):]=r['tokens'];mask[i,-len(r['tokens']):]=True
    return x,mask,np.array([r['control'] for r in records],dtype=dtype)

def predict(model,records,chunk=48):
    if model is None:return np.array([r['baseline'] for r in records])
    keys=[hashlib.blake2b(r['tokens'].tobytes(),digest_size=16).digest() for r in records]
    missing={k:r for k,r in zip(keys,records) if k not in model.cache}
    ordered=sorted(missing,key=lambda k:len(missing[k]['tokens']))
    for start in range(0,len(ordered),chunk):
        kk=ordered[start:start+chunk];rr=[missing[k] for k in kk];x,m,c=batch(rr,model.dtype)
        z=model.forward(x,m,c,encoded_only=True)
        for k,v in zip(kk,z):model.cache[k]=v
    z=np.stack([model.cache[k] for k in keys]);c=np.array([r['control'] for r in records],dtype=model.dtype);p=model.p
    y=(np.tanh(z@p['head']+c@p['control']+p['head_b'])@p['out']+p['out_b']).ravel()
    return np.array([r['baseline'] for r in records])+20*y
