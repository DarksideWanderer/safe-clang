#!/usr/bin/env python3
"""Native replacement preserves old values on construction failure and drops once."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='native-replacement-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'replace_owner':'safe','replace_client':'safe'}}))
    base = [str(clang),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-std=c++20',
            '-I'+str(root/'include'),'-fprebuilt-module-path='+str(tmp)]
    checked = ['-fmodule-safe','-fmodule-safety-policy='+str(policy)]
    def compile(args, ok=True, needle=''):
        r = subprocess.run(base+args,text=True,capture_output=True)
        if (r.returncode==0)!=ok or needle not in r.stderr:
            source=''.join(pathlib.Path(a).read_text() for a in args if isinstance(a,str) and a.endswith('.cppm'))
            raise AssertionError(r.stderr+'\n'+source)
        assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr
    provider = tmp/'replace_owner.cppm'
    provider.write_text('''module;
#include <new>
export module replace_owner;
unsigned drops=0u, moves=0u;
export unsigned count(){unsafe{return drops;}}
export unsigned moved(){unsafe{return moves;}}
export struct Resource {
  unsigned* pointer;
  Resource(unsigned n):pointer(nullptr){if(n==0u)throw 1u;unsafe{pointer=new unsigned(n);}}
  Resource(const Resource&)=delete;
  Resource(Resource&&):pointer(nullptr){unsafe{++moves;}throw 1u;}
  ~Resource(){unsafe{delete pointer;++drops;}}
  unsigned get()const{unsafe{return *pointer;}for(;;){}}
};
export struct ThrowDrop {
  unsigned* pointer;bool fail;
  ThrowDrop(unsigned n,bool f):pointer(nullptr),fail(f){unsafe{pointer=new unsigned(n);}}
  ThrowDrop(const ThrowDrop&)=delete;ThrowDrop(ThrowDrop&&)=delete;
  ~ThrowDrop()noexcept(false){unsafe{delete pointer;++drops;}if(fail)throw 1u;}
  unsigned get()const{unsafe{return *pointer;}for(;;){}}
};
export struct __attribute__((annotate("safecpp.pinned"))) Pinned {
  Resource value;
  Pinned(unsigned n):value(n){}
  Pinned(const Pinned&)=delete;Pinned(Pinned&&)=delete;
};
''')
    client=tmp/'replace_client.cppm';prefix='export module replace_client;import replace_owner;\n'
    for optimization in ('-O0','-O2'):
        flags=[optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        compile(flags+checked+['--precompile',str(provider),'-o',str(tmp/'replace_owner.pcm')])
        client.write_text(prefix+'''template<class T>void replace(T& value,unsigned n){
  T local(n);local:=T(n+1u);
}
template<class T>void retire(unsigned n){T local(n);local:=void();}
template<class T>void deferred(unsigned n){T local:=void();local:=T(n);}
unsigned scalar_parameter(unsigned source){unsigned target=^^source;source:=3u;return target+source;}
export unsigned run(){
  {Resource value(7u);value:=Resource(11u);if(value.get()!=11u || count()!=1u)return 1u;
   try{value:=Resource(0u);}catch(...){if(value.get()!=11u)return 2u;}
   if(count()!=1u)return 3u;
   Resource source(13u);value:=^^source;if(value.get()!=13u || count()!=2u)return 4u;
  }
  if(count()!=3u || moved()!=0u)return 5u;
  {Resource source(17u);Resource target=^^source;source:=Resource(19u);
   if(source.get()!=19u || target.get()!=17u)return 6u;
  }
  if(count()!=5u)return 7u;
  {struct Pair{Resource left;Resource right;};Pair pair{23u,29u};Resource left=^^pair.left;
   pair:=Pair{31u,37u};if(pair.left.get()!=31u || pair.right.get()!=37u || count()!=6u)return 8u;
  }
  if(count()!=9u)return 9u;
  try{ThrowDrop old(41u,true);old:=ThrowDrop(43u,false);}catch(...){}
  if(count()!=11u)return 10u;
  {Resource value(47u);for(unsigned i=0u;i<3u;++i){value:=Resource(i+1u);}
   if(value.get()!=3u)return 11u;
  }
  if(count()!=15u)return 12u;
  {Resource value(53u);replace(value,59u);}
  if(count()!=18u)return 13u;
  {Resource value(61u);value:=void();value:=void();value:=Resource(67u);}
  if(count()!=20u)return 14u;
  {const Resource value(71u);value:=void();}
  if(count()!=21u)return 15u;
  {Pinned value(73u);value:=void();}
  if(count()!=22u)return 16u;
  {struct Pair{Resource left;Resource right;};Pair pair{79u,83u};Resource left=^^pair.left;
   pair:=void();}
  if(count()!=24u)return 17u;
  retire<Resource>(89u);if(count()!=25u)return 18u;
  try{ThrowDrop value(97u,true);value:=void();}catch(...){}
  if(count()!=26u)return 19u;
  {unsigned value=101u;struct View{const unsigned& value;};View view{value};
   view:=void();value=103u;if(value!=103u)return 20u;}
  {struct Pair{Resource left;Resource right;};Pair pair{107u,109u};
   const Resource^ right=^const pair.right;
   pair.left:=Resource(113u);if(right.get()!=109u || pair.left.get()!=113u)return 21u;
   pair.left:=void();pair.left:=Resource(127u);
   if(pair.left.get()!=127u || pair.right.get()!=109u)return 22u;
  }
  if(count()!=30u)return 23u;
  {struct Pair{Resource left;Resource right;};Pair pair{131u,137u};Resource left=^^pair.left;
   pair.left:=Resource(139u);if(pair.left.get()!=139u || left.get()!=131u)return 24u;
  }
  if(count()!=33u)return 25u;
  {struct Pair{ThrowDrop left;Resource right;};Pair pair{ThrowDrop(149u,true),Resource(151u)};
   try{pair.left:=ThrowDrop(157u,false);}catch(...){if(pair.right.get()!=151u)return 26u;}
   pair.left:=ThrowDrop(163u,false);
  }
  if(count()!=37u)return 27u;
  {Resource value:=void();value:=void();value:=Resource(167u);if(value.get()!=167u)return 28u;}
  if(count()!=38u)return 29u;
  {Resource never:=void();}
  deferred<Resource>(173u);if(count()!=39u)return 30u;
  try{Resource value:=void();value:=Resource(0u);}catch(...){}
  if(count()!=39u)return 31u;
  {Resource value:=Resource(179u);if(value.get()!=179u)return 32u;}
  if(count()!=40u)return 33u;
  {unsigned value:=void();value:=181u;unsigned target=^^value;value:=191u;
   if(target!=181u || value!=191u || scalar_parameter(193u)!=196u)return 34u;}
  {double value:=void();value:=1.5;double target=^^value;value:=2.5;
   if(target!=1.5 || value!=2.5)return 35u;}
  {struct Pair{unsigned left;Resource right;};Pair pair{197u,199u};unsigned left=^^pair.left;
   pair.left:=211u;if(left!=197u || pair.left!=211u)return 36u;}
  if(count()!=41u)return 37u;
  {unsigned first=223u,second=227u;struct View{const unsigned& value;};View view:=void();
   view:=View{first};if(view.value!=223u)return 38u;
   view:=View{second};first=229u;if(view.value!=227u || first!=229u)return 39u;
   view:=void();second=233u;if(second!=233u)return 40u;
  }
  return 0u;
}''')
        compile(flags+checked+['--precompile',str(client),'-o',str(tmp/'replace_client.pcm')])
        objects=[]
        for name in ('replace_owner','replace_client'):
            obj=tmp/(name+'.o');compile(flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)]);objects.append(str(obj))
        main=tmp/'main.cpp';main.write_text('import replace_client;int main(){return int(run());}')
        binary=tmp/'run';compile(flags+[str(main)]+objects+['-lc++','-o',str(binary)])
        subprocess.run([str(binary)],check=True,timeout=30)
        for body,needle in [
            ('unsigned f(){Resource x(1u);const Resource^ r=^const x;x:=Resource(2u);return r.get();}','live storage borrow'),
            ('void f(Resource& x){x:=Resource(2u);}','local owning'),
            ('void f(){Resource x(1u);Resource y(2u);x:=y;}','fresh value'),
            ('void f(){const Resource x(1u);x:=Resource(2u);}','local owning'),
            ('void f(){Resource x(1u);auto fn=[&](){x:=Resource(2u);};fn();}','local owning'),
            ('void f(){Resource x(1u);auto fn=[x=^^x]()mutable{x:=Resource(2u);};fn();}','local owning'),
            ('unsigned f(){ThrowDrop x(1u,true);try{x:=ThrowDrop(2u,false);}catch(...){return x.get();}return 0u;}','relocated'),
            ('unsigned f(){Resource x(1u);x:=void();return x.get();}','relocated'),
            ('unsigned f(){Resource x(1u);const Resource^ r=^const x;x:=void();return r.get();}','live storage borrow'),
            ('void f(){Pinned x(1u);x:=Pinned(2u);}','pinned'),
            ('unsigned f(){struct Pair{Resource left;Resource right;};Pair x{1u,2u};const Resource^ r=^const x.left;x.left:=Resource(3u);return r.get();}','live storage borrow'),
            ('unsigned f(){struct Pair{Resource left;Resource right;};Pair x{1u,2u};x.left:=void();return x.left.get();}','relocated'),
            ('void f(){struct Pair{Resource left;Resource right;};Pair x{1u,2u};Pair y=^^x;x.left:=Resource(3u);}','live owning parent'),
            ('void f(){struct Pair{Resource left;~Pair(){}};Pair x{1u};x.left:=Resource(3u);}','custom parent drop'),
            ('unsigned f(){Resource x:=void();return x.get();}','relocated'),
            ('unsigned f(bool b){Resource x:=void();if(b)x:=Resource(1u);return x.get();}','relocated'),
            ('void f(){Resource& x:=void();}','deferred initialization'),
            ('unsigned f(){unsigned x:=void();return x;}','relocated'),
            ('unsigned f(){unsigned x=1u;unsigned y=^^x;return x;}','relocated'),
            ('unsigned f(){unsigned x=1u;const unsigned^ r=^const x;x:=2u;return r;}','live storage borrow'),
            ('unsigned f(unsigned& x){return ^^x;}','local owning'),
            ('void f(){Resource x(1u);Resource^ r=^x;Resource y(static_cast<Resource&&>(r));}','borrow'),
            ('unsigned f(){unsigned a=1u,b=2u;struct View{const unsigned& value;};View v{a};v:=View{b};b=3u;return v.value;}','borrow'),
            ('Resource x:=void();','deferred initialization'),
        ]:
            client.write_text(prefix+body);compile(flags+checked+['-fsyntax-only',str(client)],False,needle)
print('Native replacement: records/scalars/fields, deferred initialization, explicit drop, construction rollback, exact drops and throwing cleanup; 24 refusals at O0/O2 under ASan/UBSan passed')
