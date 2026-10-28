#!/usr/bin/env python3
"""Finite region-set semantics independently checks callable composition."""
import itertools
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
# A region is a set of live points. Outlives is superset, and 7 is static.
# The common invocation point can be added to every set without changing this
# order. Three other points provide a chain and incomparable lifetimes.
STATIC = 'static'
PATTERNS = [
    ('first', 'a', ('a','b'), ()),
    ('second', 'b', ('a','b'), ()),
    ('tied', 'a', ('a','a'), ()),
    ('short', 'b', ('a','b'), (('a','b'),)),
    ('long', 'a', ('a','b'), (('a','b'),)),
    ('reverse_short', 'a', ('a','b'), (('b','a'),)),
    ('reverse_long', 'b', ('a','b'), (('b','a'),)),
    ('equal', 'a', ('a','b'), (('a','b'),('b','a'))),
    ('permanent_result', STATIC, ('a','b'), ()),
    ('permanent_first', 'a', ('a',STATIC), ()),
    ('permanent_second', 'a', (STATIC,'a'), ()),
    ('permanent_all', STATIC, (STATIC,STATIC), ()),
    ('static_kind_first', 'a', ('a','b'), (('a',STATIC),)),
    ('static_kind_second', 'b', ('a','b'), (('b',STATIC),)),
    ('static_kind_edge', 'a', ('a','b'), (('a',STATIC),('b','a'))),
    ('static_kind_both', STATIC, ('a','b'), (('a',STATIC),('b',STATIC))),
]


def outlives(a,b):
    return a | b == a


def interpretations(pattern):
    _, result, inputs, edges = pattern
    names = sorted(({result,*inputs} | {x for edge in edges for x in edge})-{STATIC})
    values = []
    for masks in itertools.product(range(8), repeat=len(names)):
        environment = dict(zip(names,masks),static=7)
        if all(outlives(environment[a],environment[b]) for a,b in edges):
            values.append((tuple(environment[a] for a in inputs),environment[result]))
    return values


def substitutable(source,target):
    # For every legal target call, the source may instantiate its own binders.
    # Source inputs accept the target values, and its result lasts long enough.
    return all(any(all(outlives(a,b) for a,b in zip(target_args,source_args))
                   and outlives(source_result,target_result)
                   for source_args,source_result in source)
               for target_args,target_result in target)


def main():
    api = 'struct Owner{};\n'
    for i,(_,result,inputs,edges) in enumerate(PATTERNS):
        names=sorted(({result,*inputs} | {x for edge in edges for x in edge})-{STATIC})
        where=(' where '+','.join(a+':'+b for a,b in edges)) if edges else ''
        binders='/('+','.join(names)+where+')' if names else ''
        api += (f'using F{i}=const unsigned^/{result} {binders}'
                '('+','.join('const unsigned^/'+a for a in inputs)+') safe;\n')
        for name,spelling in (
                ('argument',f'void(F{i}*) safe'),
                ('result',f'F{i}* () safe'),
                ('twice',f'void(argument{i}*) safe'),
                ('result_argument',f'argument{i}* () safe'),
                ('readonly_slot',f'void(F{i}*const*) safe'),
                ('readonly_borrow',f'void(F{i}*const^) safe'),
                ('readonly_array',f'void(F{i}*const(*)[2]) safe'),
                ('member_code',f'void(F{i} Owner::*) safe'),
                ('borrow_code',f'void(F{i}^) safe'),
                ('mutable_slot',f'void(F{i}**) safe')):
            api += f'using {name}{i}={spelling};\n'
    n=len(PATTERNS)
    for i in range(n):
        api += f'using siblings{i}=void(F{i}*,F{(i+n//2)%n}*) safe;\n'
    interpretations_all = list(map(interpretations,PATTERNS))
    relation = [[substitutable(a,b) for b in interpretations_all] for a in interpretations_all]
    checks=[]
    for i in range(n):
        for j in range(n):
            for name,expected in (
                    ('F',relation[i][j]),
                    ('argument',relation[j][i]),
                    ('result',relation[i][j]),
                    ('twice',relation[i][j]),
                    ('result_argument',relation[j][i]),
                    ('readonly_slot',relation[j][i]),
                    ('readonly_borrow',relation[j][i]),
                    ('readonly_array',relation[j][i]),
                    ('member_code',relation[j][i]),
                    ('borrow_code',relation[j][i]),
                    ('siblings',relation[j][i] and relation[(j+n//2)%n][(i+n//2)%n])):
                checks.append(f'static_assert(__is_convertible({name}{i}*,{name}{j}*)=={str(expected).lower()},"{name}:{i}->{j}");\n')
            checks.append(f'static_assert(__is_convertible(mutable_slot{i}*,mutable_slot{j}*)==__is_same(F{i},F{j}),"mutable:{i}->{j}");\n')
    flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values',
           '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    with tempfile.TemporaryDirectory(prefix='higher-algebra-') as directory:
        d=pathlib.Path(directory)
        module,pcm,source=(d/name for name in ('api.cppm','api.pcm','client.cpp'))
        module.write_text('export module algebra;export {\n'+api+'}\n')
        def compile(options):
            r=subprocess.run([str(CLANG)]+flags+options,capture_output=True,text=True,timeout=120)
            assert r.returncode==0,r.stderr
        compile(['--precompile',str(module),'-o',str(pcm)])
        for use_pcm in (False,True):
            source.write_text(('import algebra;\n' if use_pcm else api)+''.join(checks))
            compile((['-fmodule-file=algebra='+str(pcm)] if use_pcm else [])+['-fsyntax-only',str(source)])
    print(f'Higher-ranked relation algebra: {len(checks)*2} local/PCM assertions against finite region-set semantics; independent binders, substitution, covariance, invariance, sibling scopes and nested contravariance passed')


if __name__=='__main__':
    main()
