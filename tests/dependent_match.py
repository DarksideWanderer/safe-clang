#!/usr/bin/env python3
"""Native template matches survive PCM and check their instantiated operand."""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'llvm-build/bin/clang'
MODULE='''module;
#include <new>
export module templatematch;
unsigned drops=0u;
export unsigned count() safe { unsafe { return drops; } }
export struct Counted {
  unsigned value;
  unsigned* allocation;
  explicit Counted(unsigned v=0u):value(v),allocation(nullptr) {
    unsafe { allocation=new unsigned(v); }
  }
  Counted(const Counted&)=delete;
  Counted(Counted&&)=delete;
  ~Counted(){ unsafe { delete allocation; ++drops; } }
};
export template<class T> choice Maybe { default none, some(T) };
export template<class T> T unwrap(Maybe<T> value) safe {
  return match(rel value) -> T { .some(payload) => rel payload; .none => T{}; };
}
export template<class Choice> unsigned inspect(const Choice^ value) safe {
  return match(*value) -> unsigned { .some(^payload) => *payload; .none => 0u; };
}
export template<class T> constexpr unsigned range(T value) safe {
  return match(value) -> unsigned { 10...20 => 1u; _ => 0u; };
}
export template<class T> constexpr unsigned boolean(T value) safe {
  return match(value) -> unsigned { true => 1u; false => 0u; };
}
export template<class Choice> unsigned incomplete(Choice value) safe {
  return match(rel value) -> unsigned { .some(payload) => 1u; };
}
export template<class Choice> unsigned missing(Choice value) safe {
  return match(rel value) -> unsigned { .other => 1u; _ => 0u; };
}
export template<class Choice> unsigned nested(const Choice^ value) safe {
  return match(*value) -> unsigned {
    .some(.some(^payload)) => *payload;
    .some(.none) => 0u;
    .none => 0u;
  };
}
unsigned throw_value(unsigned) safe { throw 7; }
export template<class Choice> unsigned exceptional(Choice value) safe {
  return match(rel value) -> unsigned {
    .some(payload) => throw_value(payload.value); .none => 0u;
  };
}
'''
CLIENT='''export module matchclient;
import templatematch;
static_assert(range(9u)==0u && range(10u)==1u && range(19u)==1u && range(20u)==0u);
static_assert(boolean(true)==1u && boolean(false)==0u);
export unsigned run() safe {
  Maybe<unsigned> a=.some(7u);
  if(inspect(^const a)!=7u || inspect(^const a)!=7u) return 1u;
  if(unwrap(rel a)!=7u) return 2u;
  Maybe<unsigned> b=.none;
  if(unwrap(rel b)!=0u) return 3u;
  Maybe<unsigned> inner=.some(13u);
  Maybe<Maybe<unsigned>> c=.some(rel inner);
  if(nested(^const c)!=13u) return 4u;
  for(unsigned i=0u; i<32u; ++i)
    if(range(i)!=(i>=10u && i<20u ? 1u : 0u)) return 5u;
  {
    Maybe<Counted> owner=.some(Counted(23u));
    Counted taken=unwrap(rel owner);
    if(taken.value!=23u || count()!=0u) return 6u;
  }
  if(count()!=1u) return 7u;
  {
    Maybe<Counted> untouched=.some(Counted(29u));
  }
  if(count()!=2u) return 8u;
  try {
    Maybe<Counted> throwing=.some(Counted(31u));
    unsigned ignored=exceptional(rel throwing);
    return 9u;
  } catch(int) {
    if(count()!=3u) return 10u;
  }
  return 0u;
}
'''
REFUSALS=[
    ('Maybe<unsigned> v=.some(1u); unsigned n=incomplete(rel v);',
     'match expression does not handle every alternative'),
    ('Maybe<unsigned> v=.some(1u); unsigned n=missing(rel v);',
     'no choice alternative'),
    ('struct Plain { unsigned member; }; unsigned n=range(Plain{1u});',
     'a value or range pattern needs an integer operand'),
    ('struct Dead { ~Dead()=delete; }; Maybe<Dead> v=.none;',
     'choice payload type has a deleted destructor'),
]
DEFINITION_REFUSALS=[
    ('template<class T> void uninitialized(T^ parameter) safe { T^ local; }',
     'module-safety: borrow values require initialization'),
    ('unsigned unsafe_fn(unsigned* p) unsafe { return *p; } '
     'template<class T> unsigned bad_match(T value,unsigned* p) safe {'
     ' return match(value) -> unsigned { .some(x) => unsafe_fn(p); .none => 0u; }; }',
     "module-safety: call to unsafe or unclassified function 'unsafe_fn'"),
]

with tempfile.TemporaryDirectory(prefix='dependent-match-') as directory:
    tmp=pathlib.Path(directory)
    policy=tmp/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'templatematch':'safe','matchclient':'safe'}}))
    base=[str(CLANG),'--driver-mode=g++','-std=c++20',
          '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-fprebuilt-module-path='+str(tmp)]
    checked=['-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy)]
    source=tmp/'templatematch.cppm';source.write_text(MODULE)
    client=tmp/'matchclient.cppm';client.write_text(CLIENT)
    main=tmp/'main.cpp';main.write_text('import matchclient; int main(){return static_cast<int>(run());}\n')
    def compile(args):
        result=subprocess.run(base+args,capture_output=True,text=True,timeout=90)
        if result.returncode:raise AssertionError(result.stderr)
    for optimization in ('-O0','-O2'):
        flags=[optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        compile(flags+checked+['--precompile',str(source),'-o',str(tmp/'templatematch.pcm')])
        compile(flags+['-c',str(tmp/'templatematch.pcm'),'-o',str(tmp/'templatematch.o')])
        compile(flags+checked+['--precompile',str(client),'-o',str(tmp/'matchclient.pcm')])
        compile(flags+['-c',str(tmp/'matchclient.pcm'),'-o',str(tmp/'matchclient.o')])
        compile(flags+[str(main),str(tmp/'templatematch.o'),str(tmp/'matchclient.o'),'-o',str(tmp/'run')])
        subprocess.run([str(tmp/'run')],check=True,timeout=30)
        for body,diagnostic in REFUSALS:
            client.write_text('export module matchclient; import templatematch; void reject() safe {'+body+'}\n')
            result=subprocess.run(base+checked+['-fsyntax-only',str(client)],capture_output=True,text=True)
            if result.returncode==0 or diagnostic not in result.stderr or 'PLEASE submit' in result.stderr:
                raise AssertionError('missing instantiated pattern refusal '+diagnostic+':\n'+result.stderr)
        client.write_text(CLIENT)
    for body,diagnostic in DEFINITION_REFUSALS:
        source.write_text(MODULE+'\n'+body+'\n')
        result=subprocess.run(base+checked+['-fsyntax-only',str(source)],capture_output=True,text=True)
        if result.returncode==0 or diagnostic not in result.stderr or 'PLEASE submit' in result.stderr:
            raise AssertionError('missing template definition safety refusal '+diagnostic+':\n'+result.stderr)
print('Dependent native matches: choice/value/bool/nested borrow patterns, constexpr, PCM, owning payload return/drop/EH, O0/O2 ASan/UBSan and instantiated/definition refusals passed')
