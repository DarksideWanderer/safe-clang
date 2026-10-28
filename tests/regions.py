#!/usr/bin/env python3
"""Lifetime-indexed associated families, variance and exclusive transfer."""
import pathlib,subprocess,sys,tempfile
clang,plugin,root=sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safecpp-regions-')as directory:
 tmp=pathlib.Path(directory)
 flags=['-std=c++20','-O2','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fprebuilt-module-path='+str(tmp),'-I'+root+'/include']
 checked=[clang]+flags+['-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe']
 source=tmp/'region_checks.cppm'
 def compile(args,ok=True,needle=''):
  r=subprocess.run(args,text=True,capture_output=True)
  assert (r.returncode==0)==ok and needle in r.stderr,r.stderr+'\n'+(source.read_text()if source.exists()else str(args))
  assert 'PLEASE submit'not in r.stderr and 'frontend command failed'not in r.stderr,r.stderr
 for name,file in [('safety','safety.cppm'),('safety_regions','regions.cppm')]:
  compile(checked+['--precompile',root+'/runtime/'+file,'-o',str(tmp/(name+'.pcm'))])
 prefix='''module;
#include "module_safety.h"
export module region_checks;import safety;import safety_regions;
struct Long{};struct Short:Long{};struct Unrelated{};
struct Base{unsigned value=7u;};struct Derived:Base{};
template<class Provider,class Region> SAFETY_RETURNS_BORROW(owner)
std2::lifetime_item<Provider,Region> lend(const unsigned&owner){return Provider::template borrow<Region>(owner);}
'''
 source.write_text(prefix+'''export unsigned run(){
   unsigned x=42u;
   {
     std2::shared_ref<unsigned,Long> long_ref(x);
     std2::shared_ref<unsigned,Short> short_ref(long_ref);
     if(short_ref.get()!=42u)return 1u;
     auto associated=lend<std2::borrow_family<unsigned>,Short>(x);
     if(associated.get()!=42u)return 2u;
   }
   {
     std2::exclusive_ref<unsigned,Long> long_ref(x);
     std2::exclusive_ref<unsigned,Short> short_ref(std2::move(long_ref));
     short_ref.get_mut()=17u;
   }
   if(x!=17u)return 3u;
   Derived derived;
   std2::shared_ref<Derived,Long> source(derived);
   std2::shared_ref<Base,Short> base(source);
   if(base.get().value!=7u)return 4u;
   return 0u;
 }''')
 compile(checked+['--precompile',str(source),'-o',str(tmp/'region_checks.pcm')])
 objects=[]
 for name in ['safety','safety_regions','region_checks']:
  obj=tmp/(name+'.o');objects.append(str(obj));compile([clang]+flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)])
 main=tmp/'main.cpp';main.write_text('import region_checks;int main(){return int(run());}')
 binary=tmp/'run';compile([clang]+flags+[str(main)]+objects+['-o',str(binary)]);subprocess.run([str(binary)],check=True,timeout=30)
 for body,needle in [
   ('void f(){unsigned x=1u;std2::shared_ref<unsigned,Short>s(x);std2::shared_ref<unsigned,Long>l(s);}','error:'),
   ('void f(){Derived x;std2::exclusive_ref<Derived,Long>d(x);std2::exclusive_ref<Base,Short>b(std2::move(d));}','error:'),
   ('void f(){unsigned x=1u;std2::exclusive_ref<unsigned,Long>a(x);std2::exclusive_ref<unsigned,Short>b(std2::move(a));a.get_mut()=2u;}','moved'),
   ('unsigned f(){unsigned x=1u;auto item=lend<std2::borrow_family<unsigned>,Long>(x);x=2u;return item.get();}','borrow'),
   ('SAFETY_RETURNS_BORROW(outer) std2::shared_ref<unsigned,Long> bad(const unsigned&outer){unsigned local=1u;return std2::shared_ref<unsigned,Long>(local);}','lifetime'),
   ('void f(){unsigned x=1u;std2::exclusive_ref<unsigned,Long>a(x);auto b=a;}','error:'),
 ]:
  source.write_text(prefix+body);compile(checked+['-fsyntax-only',str(source)],False,needle)
print('Lifetime associated families, shared covariance, mutable invariance/transfer and 6 refusals passed under ASan/UBSan')
