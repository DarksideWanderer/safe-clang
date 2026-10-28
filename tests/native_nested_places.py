#!/usr/bin/env python3
"""Nested owned paths have independent loans and conditional cleanup."""
import json
import pathlib
import subprocess
import sys
import tempfile

root=pathlib.Path(__file__).resolve().parent.parent
clang=pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='native-nested-') as directory:
    tmp=pathlib.Path(directory)
    policy=tmp/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'nested_owner':'safe','nested_client':'safe'}}))
    base=[str(clang),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-std=c++20','-I'+str(root/'include'),'-fprebuilt-module-path='+str(tmp)]
    checked=['-fmodule-safe','-fmodule-safety-policy='+str(policy)]
    def compile(args,ok=True,needle=''):
        r=subprocess.run(base+args,text=True,capture_output=True)
        if (r.returncode==0)!=ok or needle not in r.stderr:
            source=''.join(pathlib.Path(a).read_text() for a in args if isinstance(a,str) and a.endswith('.cppm'))
            raise AssertionError(r.stderr+'\n'+source)
        assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr
    provider=tmp/'nested_owner.cppm'
    provider.write_text('''module;
#include <new>
export module nested_owner;
unsigned drops=0u;
export unsigned count(){unsafe{return drops;}}
export struct Resource {
  unsigned* value;
  Resource(unsigned n):value(nullptr){unsafe{value=new unsigned(n);}}
  Resource(const Resource&)=delete;Resource(Resource&&)=delete;
  ~Resource(){unsafe{delete value;++drops;}}
  unsigned get()const{unsafe{return *value;}for(;;){}}
};
export struct Branch{Resource left;Resource right;};
export struct Tree{Branch first;Branch second;};
export struct Root{Tree tree;Resource tail;};
export template<class T>Resource leaf(T value){return ^^value.first.left;}
export struct Box{Tree tree;Box(Tree value):tree(^^value){}};
struct UnsafeDrop {unsigned value=1u;unsafe_fn ~UnsafeDrop(){}};
export struct DelayedUnsafe{UnsafeDrop value;};
export struct ThrowDrop {
  unsigned* value;bool fail;
  ThrowDrop(unsigned n,bool f):value(nullptr),fail(f){unsafe{value=new unsigned(n);}}
  ThrowDrop(const ThrowDrop&)=delete;ThrowDrop(ThrowDrop&&)=delete;
  ~ThrowDrop()noexcept(false){unsafe{delete value;++drops;}if(fail)throw 1u;}
};
''')
    client=tmp/'nested_client.cppm';prefix='export module nested_client;import nested_owner;\n'
    for optimization in ('-O0','-O2'):
        flags=[optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        compile(flags+checked+['--precompile',str(provider),'-o',str(tmp/'nested_owner.pcm')])
        client.write_text(prefix+'''export unsigned run(){
  {Tree tree{{1u,2u},{3u,5u}};Resource saved=^^tree.first.left;
   const Resource^ right=^const tree.first.right;
   if(right.get()!=2u || tree.second.left.get()!=3u)return 1u;
   tree.first.left:=Resource(7u);Branch taken=^^tree.second;
   tree.second:=Branch{11u,13u};
   if(saved.get()!=1u || taken.left.get()!=3u || tree.second.right.get()!=13u)return 2u;
  }
  if(count()!=7u)return 3u;
  {Root root{Tree{{17u,19u},{23u,29u}},Resource(31u)};Resource saved=^^root.tree.first.left;
   root.tree.first.right:=Resource(37u);
   root.tree:=void();root.tree:=Tree{{41u,43u},{47u,53u}};
   if(saved.get()!=17u || root.tree.second.left.get()!=47u || root.tail.get()!=31u)return 4u;
  }
  if(count()!=17u)return 5u;
  {Resource value=leaf(Tree{{59u,61u},{67u,71u}});if(value.get()!=59u || count()!=20u)return 6u;}
  if(count()!=21u)return 7u;
  {Box value(Tree{{73u,79u},{83u,89u}});if(value.tree.first.left.get()!=73u)return 8u;}
  if(count()!=25u)return 9u;
  {struct Inner{ThrowDrop left;Resource right;};struct Outer{Inner inner;Resource tail;};
   Outer value{{ThrowDrop(97u,true),Resource(101u)},Resource(103u)};
   try{value.inner.left:=ThrowDrop(107u,false);}catch(...){if(value.inner.right.get()!=101u || value.tail.get()!=103u)return 10u;}
   value.inner.left:=ThrowDrop(109u,false);
  }
  if(count()!=30u)return 11u;
  return 0u;
}''')
        compile(flags+checked+['--precompile',str(client),'-o',str(tmp/'nested_client.pcm')])
        objects=[]
        for name in ('nested_owner','nested_client'):
            obj=tmp/(name+'.o');compile(flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)]);objects.append(str(obj))
        main=tmp/'main.cpp';main.write_text('import nested_client;int main(){return int(run());}')
        binary=tmp/'run';compile(flags+[str(main)]+objects+['-lc++','-o',str(binary)])
        subprocess.run([str(binary)],check=True,timeout=30)
        cases=[
            ('unsigned f(){Tree t{{1u,2u},{3u,4u}};Resource x=^^t.first.left;return t.first.left.get();}','partially relocated'),
            ('void f(){Tree t{{1u,2u},{3u,4u}};Resource x=^^t.first.left;Branch y=^^t.first;}','partially relocated'),
            ('void f(){Tree t{{1u,2u},{3u,4u}};Branch x=^^t.first;t.first.left:=Resource(5u);}','live owning parent'),
            ('unsigned f(){Tree t{{1u,2u},{3u,4u}};const Branch^ r=^const t.first;Resource x=^^t.first.left;return r.right.get();}','borrow'),
            ('unsigned f(){Tree t{{1u,2u},{3u,4u}};const Resource^ r=^const t.first.left;t.first.left:=Resource(5u);return r.get();}','borrow'),
            ('void f(){struct Inner{Resource value;~Inner(){}};struct Outer{Inner inner;};Outer x{{1u}};Resource y=^^x.inner.value;}','without custom drop'),
            ('void f(Tree& t){Resource value=^^t.first.left;}','local owning'),
            ('unsigned f(){struct Value{unsigned data[2];};Value x{{1u,2u}};Value y=^^x;return x.data[0u];}','relocated'),
            ('unsigned f(){struct Value{unsigned data:2;};Value x{1u};return ^^x.data;}','without custom drop'),
            ('void f(){DelayedUnsafe value;}','unsafe or unclassified'),
        ]
        for body,needle in cases:
            client.write_text(prefix+body);compile(flags+checked+['-fsyntax-only',str(client)],False,needle)
print('Nested owned paths: repeated field declarations, disjoint loans, subtree transfer/drop/restore, parameter/delegation/EH cleanup and 10 refusals at O0/O2 under ASan/UBSan passed')
