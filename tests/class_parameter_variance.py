#!/usr/bin/env python3
"""Four-point variance composed through T+ fields and higher-ranked callbacks."""
import os
import pathlib
import subprocess
import tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''struct View/(a){const unsigned^/a value;};
struct Pair/(a,b){View/a first;View/b second;};
template<class T+>struct Box{T value;};
template<class T+>struct MutableBox{T unsafe value;};
template<class T+>struct Phantom{};
template<class T+>struct Repeat{T first;T second;};
template<class A+,class B+>struct Duo{A first;B second;};
'''
SHAPES=[
 ('output','Box<const unsigned^/{r} (*)() safe>', 'cov'),
 ('input','Box<void (*)(const unsigned^/{r}) safe>', 'contra'),
 ('both','Box<const unsigned^/{r} (*)(const unsigned^/{r}) safe>', 'inv'),
 ('unused','Phantom<const unsigned^/{r} (*)() safe>', 'biv'),
 ('mutable','MutableBox<const unsigned^/{r} (*)() safe>', 'inv'),
 ('mutable_input','MutableBox<void (*)(const unsigned^/{r}) safe>', 'inv'),
 ('repeated','Repeat<Box<const unsigned^/{r} (*)() safe>>', 'cov'),
 ('opposite','Duo<Box<const unsigned^/{r} (*)() safe>,Box<void (*)(const unsigned^/{r}) safe>>','inv'),
 ('double_negative','Box<void (*)(void (*)(const unsigned^/{r}) safe) safe>', 'cov'),
 ('negative_result','Box<auto (*)() safe -> void (*)(const unsigned^/{r}) safe>', 'contra'),
]
# Distinct record nodes force the fixed point and projections beyond the old
# depth limits; memoization must handle repeated sibling type DAGs as well.
for i in range(48):
 API+=f'template<class T+>struct Deep{i}{{'+('T value;' if i==0 else f'Deep{i-1}<T> left;Deep{i-1}<T> right;')+'};\n'
SHAPES.append(('deep','Deep47<const unsigned^/{r} (*)() safe>','cov'))
checks=[]
for name,shape,variance in SHAPES:
 for r in ('a','b'):
  result='void' if variance=='biv' else 'Pair/a/b'
  bindings=f'/{r}/{r}' if name=='opposite' else f'/{r}'
  API+=f'using {name}_{r}={result} /(a,b,c where a:b)(const unsigned^/a,const unsigned^/b,const {shape.format(r=r)}{bindings}^/c) safe;\n'
 for source,target in (('a','b'),('b','a')):
  answer=variance=='biv' or (variance=='cov' and source=='b') or (variance=='contra' and source=='a')
  checks.append(f'static_assert(__is_convertible({name}_{source}*,{name}_{target}*)=={str(answer).lower()},"{name}:{source}->{target}");\n')
  # An outer function parameter reverses the entire proven class relation.
  API+=f'using Param_{name}_{source}=void({name}_{source}*) safe;\n'
  API+=f'using Return_{name}_{source}={name}_{source}*() safe;\n'
  checks.append(f'static_assert(__is_convertible(Param_{name}_{target}*,Param_{name}_{source}*)=={str(answer).lower()});\n')
  checks.append(f'static_assert(__is_convertible(Return_{name}_{source}*,Return_{name}_{target}*)=={str(answer).lower()});\n')
flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
with tempfile.TemporaryDirectory(prefix='class-variance-') as directory:
 d=pathlib.Path(directory);module=d/'api.cppm';pcm=d/'api.pcm';source=d/'client.cpp'
 module.write_text('export module variance;export {\n'+API+'}\n')
 def compile(args):
  r=subprocess.run([str(CLANG)]+flags+args,capture_output=True,text=True,timeout=120)
  assert r.returncode==0,r.stderr
 compile(['--precompile',str(module),'-o',str(pcm)])
 for imported in (False,True):
  source.write_text(('import variance;\n' if imported else API)+''.join(checks))
  compile((['-fmodule-file=variance='+str(pcm)] if imported else [])+['-fsyntax-only',str(source)])
print(f'Class parameter variance: {len(checks)*2} local/PCM assertions; covariance, contravariance, invariance, bivariance, mutable storage, callback composition and 48-level shared type DAG passed')
