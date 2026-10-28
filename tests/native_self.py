#!/usr/bin/env python3
"""Symbolic explicit self parameters own and explicitly consume their receiver
values.  Circle's current relocated-parameter ABI does not automatically
destroy an explicit `self` parameter, so library-style code writes drp/rel
explicitly; automatic callee-side destruction remains a compatibility gap."""
import json
import pathlib
import subprocess
import sys
import tempfile

root=pathlib.Path(__file__).resolve().parent.parent
clang=pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='native-self-') as directory:
    tmp=pathlib.Path(directory)
    policy=tmp/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'self_owner':'safe','self_client':'safe'}}))
    base=[str(clang),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-std=c++20','-I'+str(root/'include'),'-fprebuilt-module-path='+str(tmp)]
    checked=['-fcircle-safety','-fmodule-safety-policy='+str(policy)]
    def compile(args,ok=True,needle=''):
        r=subprocess.run(base+args,text=True,capture_output=True)
        if (r.returncode==0)!=ok or needle not in r.stderr:
            source=''.join(pathlib.Path(a).read_text() for a in args if isinstance(a,str) and a.endswith('.cppm'))
            raise AssertionError(r.stderr+'\n'+source)
        assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr
    provider=tmp/'self_owner.cppm'
    provider.write_text('''module;
#include <new>
export module self_owner;
unsigned drops=0u;
export unsigned count(){unsafe{return drops;}}
export struct Resource {
  unsigned* value;
  Resource(unsigned n):value(nullptr){unsafe{value=new unsigned(n);}}
  Resource(const Resource&)=delete;Resource(Resource&&)=delete;
  ~Resource(){unsafe{delete value;++drops;}}
  unsigned get()const{unsafe{return *value;}for(;;){}}
  Resource into(self) safe{return ^^self;}
  unsigned read(self) safe{auto v=self.get();drp self;return v;}
  void fail(self) safe{drp self;throw 1u;}
  template<class Self>Resource generic(^^ Self self){return ^^self;}
  unsigned operator()(self,unsigned delta) safe{auto v=self.get()+delta;drp self;return v;}
};
export template<class T>struct GenericCell {
  T value;
  T read(const self^) safe {return self->value;}
  const T^ view(const self^) safe {return ^const self->value;}
  void write(self^,T next) safe {self->value=next;}
};
export template<class T>struct BorrowBox {
  T value;
  T^ operator->(self^) safe {return ^self->value;}
  const T^ operator->(const self^) safe {return ^const self->value;}
  const T^ operator*(const self^) safe {return ^const self->value;}
};
export struct Cell {
  unsigned value;
  unsigned read(const self^) safe {return self->value;}
  void write(self^,unsigned next) safe {self->value=next;}
};
export struct Pair {
  Resource first;Resource second;
  Resource take_first(self) safe{Resource result=^^self.first;drp self;return rel result;}
};
''')
    client=tmp/'self_client.cppm';prefix='export module self_client;import self_owner;\n'
    for optimization in ('-O0','-O2'):
        flags=[optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        compile(flags+checked+['--precompile',str(provider),'-o',str(tmp/'self_owner.pcm')])
        client.write_text(prefix+'''export unsigned run(){
  {BorrowBox<Cell> box{{5u}};box->write(6u);const Cell^ loan=box.operator->();if(loan->value!=6u || (*box).value!=6u)return 96u;}
  {GenericCell<unsigned> cell{3u};const unsigned^ value=cell.view();if(*value+cell.read()!=6u)return 97u;}
  {Cell cell{1u};cell.write(2u);if(cell.read()!=2u)return 99u;const Cell^ view=^const cell;if((*view).value!=2u)return 98u;}
  {Resource owner(1u);Resource result=(^^owner).into();if(result.get()!=1u)return 1u;}
  if(count()!=1u)return 2u;
  if(Resource(2u).read()!=2u || count()!=2u)return 3u;
  try{Resource(3u).fail();}catch(...){}
  if(count()!=3u)return 4u;
  {Resource result=Resource(5u).generic();if(result.get()!=5u)return 5u;}
  if(count()!=4u)return 6u;
  {Pair owner{7u,11u};Resource result=(^^owner).take_first();
   if(result.get()!=7u || count()!=5u)return 7u;
  }
  if(count()!=6u)return 8u;
  {auto callback=&Resource::into;Resource result=callback(Resource(13u));if(result.get()!=13u)return 9u;}
  if(count()!=7u)return 10u;
  if(Resource(17u)(2u)!=19u || count()!=8u)return 11u;
  return 0u;
}''')
        compile(flags+checked+['--precompile',str(client),'-o',str(tmp/'self_client.pcm')])
        objects=[]
        for name in ('self_owner','self_client'):
            obj=tmp/(name+'.o');compile(flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)]);objects.append(str(obj))
        main=tmp/'main.cpp';main.write_text('import self_client;int main(){return int(run());}')
        binary=tmp/'run';compile(flags+[str(main)]+objects+['-lc++','-o',str(binary)])
        subprocess.run([str(binary)],check=True,timeout=30)
        for body,needle in [
            ('unsigned f(){BorrowBox<Cell> box{{1u}};const Cell^ loan=box.operator->();box->write(2u);return loan->value;}','borrow'),
            ('unsigned f(){GenericCell<unsigned> value{1u};const unsigned^ loan=value.view();value.write(2u);return *loan;}','borrow'),
            ('unsigned f(){unsigned value=1u;unsigned^ parent=^value;const unsigned^ child=^const parent;*parent=2u;return *child;}','borrow'),
            ('unsigned f(){Cell value{1u};Cell^ parent=^value;const Cell^ child=^const parent;(*parent).value=2u;return child->value;}','borrow'),
            ('void f(){Cell value{1u};const Cell^ loan=^const value;loan->value=2u;}','error:'),
            ('unsigned f(){Cell value{1u};const Cell^ loan=^const value;value.write(2u);return loan->value;}','borrow'),
            ('unsigned f(){Resource x(1u);Resource out=(^^x).into();return x.get();}','relocated'),
            ('unsigned f(){Resource x(1u);const Resource^ r=^const x;Resource out=(^^x).into();return r.get();}','borrow'),
            ('struct Bad{void call(^^ Bad& self){}};','by-value record'),
            ('struct Bad{void call(^^ unsigned self){}};','by-value record'),
            ('struct Bad{unsigned value=1u;unsigned call(^^ Bad self){return this->value;}};','explicit object'),
            ('unsigned f(){Resource x(1u);return x.read();}','owned self requires'),
        ]:
            client.write_text(prefix+body);compile(flags+checked+['-fsyntax-only',str(client)],False,needle)
print('Circle owned/borrowed self with explicit consumption, native borrow dereference/member access, value ABI, PCM/templates/field moves/indirect calls/EH and 12 refusals at O0/O2 under ASan/UBSan passed')
