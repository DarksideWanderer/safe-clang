#!/usr/bin/env python3
"""Lexical captures checked against independently enumerated region sets."""
import functools
import itertools
import os
import pathlib
import subprocess
import tempfile
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))

@dataclass(frozen=True)
class Fn:
    names: tuple
    result: str
    params: tuple
    edges: tuple = ()

    def spelling(self):
        result = 'void' if self.result == '-' else 'const unsigned^/'+self.result
        where = ' where '+','.join(a+':'+b for a,b in self.edges) if self.edges else ''
        binder = '/('+','.join(self.names)+where+')' if self.names else ''
        params = ','.join(p.spelling() if isinstance(p, Fn) else 'const unsigned^/'+p for p in self.params)
        return result+' '+binder+'('+params+') safe'


def lookup(label, env):
    if label == 'static': return 1
    for scope in reversed(env):
        if label in dict(scope): return dict(scope)[label]
    raise AssertionError((label,env))


def outlives(a,b): return a | b == a


def assignments(f, env):
    for values in itertools.product(range(2),repeat=len(f.names)):
        e = env+(tuple(zip(f.names,values)),)
        if all(outlives(lookup(a,e),lookup(b,e)) for a,b in f.edges): yield e


@functools.lru_cache(None)
def relates(f,t,source=(),target=()):
    # Source choices precede all binders introduced by the recursive call.
    # In particular they cannot depend on a later nested universal lifetime.
    if len(f.params) != len(t.params): return False
    for te in assignments(t,target):
        found = False
        for fe in assignments(f,source):
            valid = f.result == t.result == '-'
            if f.result != '-' and t.result != '-':
                valid = outlives(lookup(f.result,fe),lookup(t.result,te))
            for fp,tp in zip(f.params,t.params):
                if isinstance(fp,Fn) and isinstance(tp,Fn):
                    valid &= relates(tp,fp,te,fe)
                elif isinstance(fp,str) and isinstance(tp,str):
                    valid &= outlives(lookup(tp,te),lookup(fp,fe))
                else: valid = False
                if not valid: break
            if valid: found = True;break
        if not found: return False
    return True


def patterns():
    result=[]
    for output in ('a','b','static'):
        for argument in ('a','b'):
            result.append(Fn(('a',),'a',('a',Fn(('b',),output,(argument,)))))
    for edges in ((('a','b'),),(('b','a'),),(('a','b'),('b','a'))):
        result.append(Fn(('a',),'a',('a',Fn(('b',),'b',('b',),edges))))
    for inner in ('a','b','c'):
        result.append(Fn(('a',),'a',('a',Fn(('b',),'b',('b',Fn(('c',),inner,('c',)))))))
    # Same spelling shadows the outer binder instead of capturing it.
    result.append(Fn(('a',),'a',('a',Fn(('a',),'a',('a',)))))
    # Separate callback guards must never become assumptions of a sibling.
    result.append(Fn(('a',),'a',('a',Fn(('b',),'b',('b',),(('a','b'),)),
                                          Fn(('c',),'a',('c',)))))
    result.append(Fn(('a',),'a',('a',Fn(('b',),'b',('b',)),
                                          Fn(('c',),'a',('c',),(('a','c'),)))))
    return result


def main():
    cases=patterns()
    api=''
    for i,f in enumerate(cases):
        api+=f'using F{i}={f.spelling()};\n'
        api+=f'using Argument{i}=void(F{i}*) safe;\n'
        api+=f'using Return{i}=F{i}*() safe;\n'
        api+=f'using Mutable{i}=void(F{i}**) safe;\n'
    checks=[]
    relation={}
    for i,f in enumerate(cases):
        for j,t in enumerate(cases):
            if len(f.params)!=len(t.params): continue
            relation[i,j]=relates(f,t)
    for (i,j),expected in relation.items():
        for prefix,answer in (('F',expected),('Argument',relation[j,i]),('Return',expected)):
            checks.append(f'static_assert(__is_convertible({prefix}{i}*,{prefix}{j}*)=={str(answer).lower()},"{prefix}:{i}->{j}");\n')
        checks.append(f'static_assert(__is_convertible(Mutable{i}*,Mutable{j}*)==__is_same(F{i},F{j}));\n')
    # Binder order and spelling are absent from canonical capture identity.
    api+='''using Alpha=const unsigned^/x /(unused,x)(const unsigned^/x,
 const unsigned^/x /(y)(const unsigned^/y) safe) safe;
static_assert(__is_same(Alpha,F1));
'''
    api+=r"""
template<class... Ts> using Captured=void /(a,b)(const Ts^/a...,const unsigned^/b,void callback(const unsigned^/a,const unsigned^/b) safe) safe;
using Empty=void /(a,b)(const unsigned^/b,void callback(const unsigned^/a,const unsigned^/b) safe) safe;
static_assert(__is_same(Captured<>,Empty));
using Two=void /(a,b)(const unsigned^/a,const unsigned^/a,const unsigned^/b,void callback(const unsigned^/a,const unsigned^/b) safe) safe;
static_assert(__is_same(Captured<unsigned,unsigned>,Two));
"""
    with tempfile.TemporaryDirectory(prefix='outer-captures-') as directory:
        d=pathlib.Path(directory)
        source,module,pcm=(d/name for name in ('client.cpp','api.cppm','api.pcm'))
        def compile(options,okay=True):
            r=subprocess.run([str(CLANG)]+flags+options,capture_output=True,text=True,timeout=120)
            assert (r.returncode==0)==okay,r.stderr
            assert 'PLEASE submit' not in r.stderr,r.stderr
            if not okay: assert 'captured lifetime region' in r.stderr,r.stderr
        for borrow_values in (False, True):
            flags=['--driver-mode=g++','-std=c++20','-fcircle-safety',
                   '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
            if borrow_values: flags.append('-fcircle-borrow-values')
            module.write_text('export module captures;export {\n'+api+'}\n')
            compile(['--precompile',str(module),'-o',str(pcm)])
            for imported in (False,True):
                source.write_text(('import captures;\n' if imported else api)+''.join(checks))
                compile((['-fmodule-file=captures='+str(pcm)] if imported else [])+['-fsyntax-only',str(source)])
    print(f'Outer region captures: {4*len(checks)} local/PCM assertions in reference/value borrow modes against point-membership set semantics; lexical shadowing, alpha identity, nested quantifier order and sibling guards passed')

if __name__=='__main__':main()
