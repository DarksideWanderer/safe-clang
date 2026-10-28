#!/usr/bin/env python3
"""Native `^payload` bindings keep borrow identity, constness and drop duty."""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'llvm-build/bin/clang'
MODULE = '''module;
#include <new>
export module borrowpattern;
export choice Scalar { default none, some(unsigned) };
export unsigned read(const Scalar^ value) safe {
  return match(*value) -> unsigned { .some(^payload) => *payload; .none => 0u; };
}
export unsigned modify(Scalar^ value) safe {
  return match(*value) -> unsigned { .some(^payload) => ++*payload; .none => 0u; };
}
unsigned drops=0u;
export unsigned count() safe { unsafe { return drops; } }
export struct Counted {
  unsigned value;
  unsigned* allocation;
  explicit Counted(unsigned v):value(v),allocation(nullptr) {
    unsafe { allocation=new unsigned(v); }
  }
  Counted(const Counted&)=delete;
  Counted(Counted&&)=delete;
  ~Counted(){ unsafe { delete allocation; ++drops; } }
};
export choice Owned { default absent, held(Counted) };
export unsigned watch(const Owned^ value) safe {
  return match(*value) -> unsigned { .held(^payload) => payload->value; .absent => 0u; };
}
export unsigned edit(Owned^ value) safe {
  return match(*value) -> unsigned { .held(^payload) => ++payload->value; .absent => 0u; };
}
export unsigned run() safe {
  Scalar s=.some(7u);
  if(read(^const s)!=7u || modify(^s)!=8u || read(^const s)!=8u) return 1u;
  Scalar blank=.none;
  if(read(^const blank)!=0u || modify(^blank)!=0u) return 2u;
  {
    Owned value=.held(Counted(31u));
    if(watch(^const value)!=31u || watch(^const value)!=31u || count()!=0u) return 3u;
    if(edit(^value)!=32u || watch(^const value)!=32u || count()!=0u) return 4u;
  }
  return count()==1u ? 0u : 5u;
}
'''
CLIENT = '''export module borrowclient;
import borrowpattern;
export unsigned client() safe {
  Scalar value=.some(41u);
  if(read(^const value)!=41u || modify(^value)!=42u || read(^const value)!=42u) return 6u;
  return run();
}
'''
REFUSALS = [
    ('unsigned bad(const Scalar^ value) safe { return match(*value) -> unsigned {'
     ' .some(^payload) => ++*payload; .none => 0u; }; }', 'error: read-only variable is not assignable'),
    ('choice Only { only(unsigned) }; unsigned^/a escape/(a)(unsigned^/a anchor, Only value) safe {'
     ' return match(value) -> unsigned^/a { .only(^payload) => rel payload; }; }',
     'module-safety: returned reference does not borrow from the declared lifetime source'),
    ('unsigned conflict(Scalar^ value) safe { return match(*value) -> unsigned {'
     ' .some(^payload) => (modify(^*value), *payload); .none => 0u; }; }',
     'module-safety: access conflicts with a live exclusive borrow'),
]

with tempfile.TemporaryDirectory(prefix='choice-borrow-pattern-') as directory:
    tmp=pathlib.Path(directory)
    policy=tmp/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'borrowpattern':'safe','borrowclient':'safe'}}))
    base=[str(CLANG),'--driver-mode=g++','-std=c++20',
          '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-fprebuilt-module-path='+str(tmp)]
    checked=['-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy)]
    source=tmp/'borrowpattern.cppm';source.write_text(MODULE)
    client=tmp/'borrowclient.cppm';client.write_text(CLIENT)
    main=tmp/'main.cpp';main.write_text('import borrowclient; int main(){return static_cast<int>(client());}\n')
    def compile(args):
        result=subprocess.run(base+args,capture_output=True,text=True,timeout=90)
        if result.returncode:raise AssertionError(result.stderr)
    for optimization in ('-O0','-O2'):
        flags=[optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        compile(flags+checked+['--precompile',str(source),'-o',str(tmp/'borrowpattern.pcm')])
        compile(flags+['-c',str(tmp/'borrowpattern.pcm'),'-o',str(tmp/'borrowpattern.o')])
        compile(flags+checked+['--precompile',str(client),'-o',str(tmp/'borrowclient.pcm')])
        compile(flags+['-c',str(tmp/'borrowclient.pcm'),'-o',str(tmp/'borrowclient.o')])
        compile(flags+[str(main),str(tmp/'borrowpattern.o'),str(tmp/'borrowclient.o'),'-o',str(tmp/'run')])
        subprocess.run([str(tmp/'run')],check=True,timeout=30)
    for body,diagnostic in REFUSALS:
        source.write_text(MODULE+'\n'+body+'\n')
        result=subprocess.run(base+checked+['-fsyntax-only',str(source)],capture_output=True,text=True)
        if result.returncode==0 or diagnostic not in result.stderr or 'PLEASE submit' in result.stderr:
            raise AssertionError('missing expected safety refusal '+diagnostic+':\n'+result.stderr)
print('Choice borrow patterns: shared/mutable native bindings, preserved ownership, PCM and O0/O2 ASan/UBSan with const/dangling/alias refusals passed')
