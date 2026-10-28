#!/usr/bin/env python3
"""Relocation transfers storage without copy/move or a source destructor."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='native-relocation-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'relocation': 'safe', 'relocation_client': 'safe'}}))
    base = [str(clang), '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22', '-std=c++20',
            '-I'+str(root/'include'), '-fprebuilt-module-path='+str(tmp)]
    checked = ['-fcircle-safety', '-fmodule-safety-policy='+str(policy)]

    def compile(args, ok=True, needle=''):
        result = subprocess.run(base+args, text=True, capture_output=True)
        if (result.returncode == 0) != ok or needle not in result.stderr:
            sources = ''.join(pathlib.Path(a).read_text() for a in args
                              if isinstance(a, str) and a.endswith('.cppm'))
            raise AssertionError(result.stderr+'\n'+sources)
        assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr

    provider = tmp/'relocation.cppm'
    provider.write_text('''module;
#include <new>
#include "module_safety.h"
export module relocation;
unsigned drops=0u, moves=0u;
export unsigned drop_count(){unsafe{return drops;}}
export unsigned move_count(){unsafe{return moves;}}
export struct Resource {
  unsigned* pointer;
  Resource(unsigned value):pointer(nullptr){unsafe{pointer=new unsigned(value);}}
  Resource(const Resource&)=delete;
  Resource(Resource&&):pointer(nullptr){unsafe{++moves;}throw 1u;}
  ~Resource(){unsafe{delete pointer;++drops;}}
  unsigned get()const{unsafe{return *pointer;}}
};
export Resource make(){Resource source(17u);return rel source;}
export template<class T>T generic(){T source(19u);return rel source;}
export template<class T>struct Slot {T value;Slot(T input):value(^^input){}};
export template<class T>T take_slot(Slot<T> slot){return ^^slot.value;}
export template<class T>T replace_slot(Slot<T> slot,T input){slot.value:=rel input;return ^^slot.value;}
export template<class T>struct PairSlot {T first;T second;PairSlot(T a,T b):first(^^a),second(^^b){}};
export template<class T>T take_first(PairSlot<T> slot){return ^^slot.first;}
export template<class T>T replace_second(PairSlot<T> slot,T input){slot.second:=rel input;return ^^slot.second;}
export template<class T>struct ThrowingSlot {T first;T second;ThrowingSlot(T a,T b):first(^^a),second(^^b){throw 1u;}};
export struct Bomb {
  unsigned* pointer;
  Bomb(unsigned value,bool fail):pointer(nullptr){
    if(fail)throw 1u;
    unsafe{pointer=new unsigned(value);}
  }
  Bomb(const Bomb&)=delete;
  Bomb(Bomb&&):pointer(nullptr){unsafe{++moves;}throw 1u;}
  ~Bomb(){unsafe{delete pointer;++drops;}}
  unsigned get()const{unsafe{return *pointer;}}
};
export struct View {const unsigned& value;~View(){unsafe{++drops;}}};
''')
    client = tmp/'relocation_client.cppm'
    prefix = 'export module relocation_client;import relocation;\n'
    for optimization in ('-O0', '-O2'):
        flags = [optimization, '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        compile(flags+checked+['--precompile', str(provider), '-o', str(tmp/'relocation.pcm')])
        client.write_text(prefix+'''void branch(bool relocate){
  Resource source(11u);
  if(relocate){Resource target=rel source;if(target.get()!=11u)throw 1u;}
}
export unsigned run(){
  {Resource source(7u);Resource target=rel source;if(target.get()!=7u)return 1u;}
  if(drop_count()!=1u || move_count()!=0u)return 2u;
  {Resource source(9u);rel source;}
  if(drop_count()!=2u)return 3u;
  try{Resource source(13u);Resource target=rel source;throw 1u;}catch(...){}
  if(drop_count()!=3u)return 4u;
  branch(false);branch(true);
  if(drop_count()!=5u)return 5u;
  for(unsigned i=0u;i!=3u;++i){Resource source(i);Resource target=rel source;if(target.get()!=i)return 6u;}
  if(drop_count()!=8u)return 7u;
  {Resource target=make();if(target.get()!=17u)return 8u;}
  {Resource target=generic<Resource>();if(target.get()!=19u)return 9u;}
  if(drop_count()!=10u || move_count()!=0u)return 10u;
  {Slot<Resource> slot(21u);Resource target=take_slot(^^slot);if(target.get()!=21u)return 20u;}
  if(drop_count()!=11u || move_count()!=0u)return 21u;
  {Slot<Resource> slot(23u);Resource target=replace_slot(^^slot,Resource(27u));if(target.get()!=27u)return 22u;}
  if(drop_count()!=13u || move_count()!=0u)return 23u;
  {PairSlot<Resource> slot(29u,31u);Resource target=take_first(^^slot);if(target.get()!=29u)return 24u;}
  if(drop_count()!=15u || move_count()!=0u)return 25u;
  {PairSlot<Resource> slot(33u,35u);Resource target=replace_second(^^slot,Resource(37u));if(target.get()!=37u)return 26u;}
  if(drop_count()!=18u || move_count()!=0u)return 27u;
  try{PairSlot<Resource> slot(39u,41u);Resource target=take_first(^^slot);throw 1u;}catch(...){}
  if(drop_count()!=20u)return 28u;
  try{ThrowingSlot<Bomb> slot(Bomb(43u,false),Bomb(47u,false));return 29u;}catch(...){}
  if(drop_count()!=22u || move_count()!=0u)return 30u;
  try{PairSlot<Bomb> slot(Bomb(53u,false),Bomb(59u,false));slot.second:=Bomb(61u,true);return 31u;}catch(...){}
  if(drop_count()!=24u || move_count()!=0u)return 32u;
  {PairSlot<Bomb> slot(Bomb(67u,false),Bomb(71u,false));slot.second:=Bomb(73u,false);if(slot.second.get()!=73u)return 33u;}
  if(drop_count()!=27u || move_count()!=0u)return 34u;
  unsigned owner=23u;
  {View source{owner};View target=rel source;if(target.value!=23u)return 11u;}
  owner=29u;
  if(drop_count()!=28u || owner!=29u)return 12u;
  {struct Pair{Resource left;Resource right;unsigned tag;};Pair pair{31u,37u,1u};
    Resource left=rel pair.left;
    if(left.get()!=31u || pair.right.get()!=37u)return 13u;
    pair.tag=2u;if(pair.tag!=2u)return 14u;
    Resource right=rel pair.right;if(right.get()!=37u)return 15u;
  }
  if(drop_count()!=30u)return 16u;
  try{struct Pair{Resource left;Resource right;};Pair pair{41u,43u};Resource left=rel pair.left;throw 1u;}catch(...){}
  if(drop_count()!=32u)return 17u;
  {struct Pair{Resource left;Resource right;};Pair pair{47u,53u};
    const Resource^ right=^const pair.right;
    Resource left=rel pair.left;
    if(left.get()!=47u || right.get()!=53u)return 18u;
  }
  if(drop_count()!=34u)return 19u;
  return 0u;
}''')
        compile(flags+checked+['--precompile', str(client), '-o', str(tmp/'relocation_client.pcm')])
        objects = []
        for name in ('relocation', 'relocation_client'):
            obj = tmp/(name+'.o')
            compile(flags+['-c', str(tmp/(name+'.pcm')), '-o', str(obj)])
            objects.append(str(obj))
        main = tmp/'main.cpp'
        main.write_text('import relocation_client;int main(){return int(run());}')
        binary = tmp/'run'
        compile(flags+[str(main)]+objects+['-lc++', '-o', str(binary)])
        subprocess.run([str(binary)], check=True, timeout=30)
        for body, needle in [
            ('unsigned f(){Resource x(1u);Resource y=rel x;return x.get();}', 'relocated'),
            ('void f(){Resource x(1u);Resource y=rel x;Resource z=rel x;}', 'relocated'),
            ('void f(){Resource x(1u);Resource& r=x;Resource y=rel r;}', 'local owning'),
            ('unsigned f(){Resource x(1u);const Resource& r=x;Resource y=rel x;return r.get();}', 'borrow'),
            ('unsigned f(bool c){Resource x(1u);if(c){Resource y=rel x;}return x.get();}', 'relocated'),
            ('unsigned f(){Resource x(1u);try{Resource y=rel x;throw 1u;}catch(...){return x.get();}return 0u;}', 'relocated'),
            ('void f(){struct Value{unsigned n=1u;};Value x;Value y=rel x;x=Value{};}', 'relocated'),
            ('void f(){struct Value{unsigned n=1u;};Value x;Value y=rel x;x.n=2u;}', 'relocated'),
            ('void f(const Resource& x){Resource y=rel x;}', 'local owning'),
            ('unsigned f(){struct Pair{Resource a;Resource b;};Pair x{1u,2u};Resource y=rel x.a;return x.a.get();}', 'partially relocated'),
            ('void f(){struct Pair{Resource a;Resource b;};Pair x{1u,2u};Resource y=rel x.a;auto z=rel x;}', 'partially relocated'),
            ('void f(){struct Pair{Resource a;~Pair(){}};Pair x{1u};Resource y=rel x.a;}', 'without custom drop'),
            ('void f(){struct Value{unsigned n=1u;};struct Pair{Value a;Value b;};Pair x;Value y=rel x.a;Value z(x.a);}', 'partially relocated'),
            ('void f(){struct Value{unsigned n=1u;};Value x;Value y=rel x;Value z(x);}', 'relocated'),
            ('unsigned f(){struct Pair{Resource a;Resource b;};Pair x{1u,2u};const Resource^ r=^const x.a;Resource y=rel x.a;return r.get();}', 'borrow'),
            ('unsigned f(){struct Pair{Resource a;Resource b;};Pair x{1u,2u};const auto^ r=^const x;Resource y=rel x.a;return r.b.get();}', 'borrow'),
            ('unsigned f(){Resource source(1u);auto callback=[x=rel source]()mutable{Resource y=rel x;return y.get();};return callback();}', 'local owning'),
            ('unsigned f(){Resource source(1u);auto callback=[&source]()mutable{Resource y=rel source;return y.get();};return callback();}', 'local owning'),
        ]:
            client.write_text(prefix+body)
            compile(flags+checked+['-fsyntax-only', str(client)], False, needle)
print('Native relocation and direct-field partial moves: no move constructor, exact drops, throwing generic field construction/replacement, disjoint field loans, branch/loop/EH/PCM/template/borrow-holder checks and 18 refusals at O0/O2 under ASan/UBSan passed')
