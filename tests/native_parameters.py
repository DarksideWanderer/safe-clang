#!/usr/bin/env python3
"""Owning record parameters transfer cleanup responsibility across native PCM."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='native-parameters-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'parameter_owner':'safe','parameter_client':'safe'}}))
    base = [str(clang),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-std=c++20',
            '-I'+str(root/'include'),'-fprebuilt-module-path='+str(tmp)]
    checked = ['-fmodule-safe','-fmodule-safety-policy='+str(policy)]
    (tmp/'legacy.hpp').write_text('struct Legacy {unsigned value=1u;~Legacy(){}};')
    def compile(args, ok=True, needle=''):
        r = subprocess.run(base+args,text=True,capture_output=True)
        if (r.returncode==0)!=ok or needle not in r.stderr:
            source=''.join(pathlib.Path(a).read_text() for a in args if isinstance(a,str) and a.endswith('.cppm'))
            raise AssertionError(r.stderr+'\n'+source)
        assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr
    provider = tmp/'parameter_owner.cppm'
    provider.write_text('''module;
#include <new>
#include "legacy.hpp"
export module parameter_owner;
unsigned drops=0u;
export unsigned count(){unsafe{return drops;}}
export struct Resource {
  unsigned* pointer;
  Resource(unsigned n):pointer(nullptr){if(n==0u)throw 1u;unsafe{pointer=new unsigned(n);}}
  Resource(const Resource&)=delete;Resource(Resource&&)=delete;
  ~Resource(){unsafe{delete pointer;++drops;}}
  unsigned get()const{unsafe{return *pointer;}for(;;){}}
};
export struct Pair {Resource left;Resource right;};
export Resource identity(Resource value){return ^^value;}
export template<class T>T relay(T value){return ^^value;}
export void consume(Resource value){}
export void retire(Resource value){value:=void();}
export unsigned replace(Resource value){value:=Resource(11u);return value.get();}
export void fail(Resource value){throw 1u;}
export void two(Resource first,Resource second){}
export Resource first(Pair value){return ^^value.left;}
export void replace_field(Pair value){value.left:=Resource(13u);}
export struct Box {Resource value;Box(Resource input):value(^^input){}};
export struct Delegated {
  Pair pair;
  Delegated(unsigned,Pair input):pair(^^input){}
  Delegated(Pair input):Delegated(0u,^^input){}
};
export struct Base {virtual void accept(Resource value){}};
export struct Derived:Base {void accept(Resource value)override{Resource local=^^value;}};
''')
    provider_text=provider.read_text()
    client=tmp/'parameter_client.cppm';prefix='export module parameter_client;import parameter_owner;\n'
    for optimization in ('-O0','-O2'):
        flags=[optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        compile(flags+checked+['--precompile',str(provider),'-o',str(tmp/'parameter_owner.pcm')])
        client.write_text(prefix+'''export unsigned run(){
  {Resource source(1u);Resource value=identity(^^source);if(value.get()!=1u)return 1u;}
  if(count()!=1u)return 2u;
  consume(Resource(2u));retire(Resource(3u));if(count()!=3u)return 3u;
  if(replace(Resource(5u))!=11u || count()!=5u)return 4u;
  try{fail(Resource(7u));}catch(...){}
  if(count()!=6u)return 5u;
  {Resource value=relay(Resource(17u));if(value.get()!=17u)return 6u;}
  if(count()!=7u)return 7u;
  {Resource value=first(Pair{19u,23u});if(value.get()!=19u || count()!=8u)return 8u;}
  if(count()!=9u)return 9u;
  replace_field(Pair{29u,31u});if(count()!=12u)return 10u;
  {Box box(Resource(37u));if(box.value.get()!=37u)return 11u;}
  if(count()!=13u)return 12u;
  {Delegated value(Pair{41u,43u});if(value.pair.left.get()!=41u)return 13u;}
  if(count()!=15u)return 14u;
  {Derived object;Base& base=object;base.accept(Resource(47u));}
  if(count()!=16u)return 15u;
  {auto callback=&consume;callback(Resource(53u));}
  if(count()!=17u)return 16u;
  try{two(Resource(59u),Resource(0u));}catch(...){}
  // Argument order is unspecified: the first argument is either never
  // constructed or is cleaned up when the second construction throws.
  if(count()<17u || count()>18u)return 17u;
  return 0u;
}''')
        compile(flags+checked+['--precompile',str(client),'-o',str(tmp/'parameter_client.pcm')])
        objects=[]
        for name in ('parameter_owner','parameter_client'):
            obj=tmp/(name+'.o');compile(flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)]);objects.append(str(obj))
        main=tmp/'main.cpp';main.write_text('import parameter_client;int main(){return int(run());}')
        binary=tmp/'run';compile(flags+[str(main)]+objects+['-lc++','-o',str(binary)])
        subprocess.run([str(binary)],check=True,timeout=30)
        for body,needle in [
            ('unsigned bad(Resource value){Resource out=^^value;return value.get();}','relocated'),
            ('unsigned bad(Resource value){value:=void();return value.get();}','relocated'),
            ('unsigned bad(Resource value){const Resource^ r=^const value;Resource out=^^value;return r.get();}','borrow'),
            ('unsigned bad(Pair value){Resource out=^^value.left;return value.left.get();}','partially relocated'),
            ('Resource bad(Resource& value){return ^^value;}','local owning'),
        ]:
            client.write_text(prefix+body);compile(flags+checked+['-fsyntax-only',str(client)],False,needle)
        provider.write_text('module;\n#include "legacy.hpp"\nexport module parameter_owner;unsafe_fn Legacy bad(Legacy value){return ^^value;}')
        compile(flags+checked+['-fsyntax-only',str(provider)],False,'local owning')
        # Restore the provider for the next optimization level.
        provider.write_text(provider_text)
print('Native owning parameters: whole/field relocation, replacement/drop, exceptions, delegation, virtual/indirect calls and 6 refusals at O0/O2 under ASan/UBSan passed')
