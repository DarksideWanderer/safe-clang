#!/usr/bin/env python3
"""Array and array-borrow conversions preserve slice address, extent and loans."""
import os
import pathlib
import subprocess
import tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
FLAGS=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values',
       '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
API=r'''
using MutableBorrow=unsigned^;
using SharedSlot=const MutableBorrow^;
using InlineSharedSlot=unsigned^const^;
using VolatileSlot=volatile MutableBorrow^;
using InlineVolatileSlot=unsigned^volatile^;
static_assert(__is_same(SharedSlot,InlineSharedSlot));
static_assert(__is_same(VolatileSlot,InlineVolatileSlot));
struct Consumer {
 unsigned observed;
 Consumer(unsigned n):observed(n){}
 Consumer(const [unsigned;dyn]^ input) safe
  :observed(static_cast<unsigned>((*input)~length)+input[0u]) {}
 void operator=(Consumer rhs) safe {observed=rhs.observed;}
};
void set([unsigned;dyn]^ s) safe {s[0u]=19u;}
unsigned inspect(Consumer c) safe {return c.observed;}
unsigned run() safe {
 unsigned data[3]={7u,11u,13u};const unsigned readonly[2]={23u,29u};
 Consumer target(0u);target=data;
 if(target.observed!=10u || inspect(data)!=10u || inspect(readonly)!=25u)return 1u;
 mut set(data);
 return data[0u]==19u?0u:2u;
}
const [unsigned;dyn]^/a view/(a)(const [unsigned;3]^/a input) safe {return input;}
template<typename T>const [T;dyn]^/a generic_view/(a)(const [T;3]^/a input) safe {return input;}
const [unsigned;3]^/a once/(a,b)(const [unsigned;3]^/a input,unsigned^/b count) safe {
 *count+=1u;return input;
}
unsigned run_borrowed() safe {
 unsigned data[3]={7u,11u,13u};const unsigned readonly[2]={23u,29u};
 {
  [unsigned;dyn]^ edit=^data;
  if((*edit)~length!=3ul)return 3u;
  edit[1u]=31u;
 }
 auto shared=^const data;auto read=view(shared);auto generic=generic_view<unsigned>(shared);auto count=0u;
 const [unsigned;dyn]^ single=once(^const data,^count);
 if(count!=1u || (*single)~length!=3ul || single[1u]!=31u || read[2u]!=13u || generic[1u]!=31u)return 4u;
 Consumer target(0u);target=^const data;
 auto indirect=&inspect;
 if(target.observed!=10u || indirect(^const readonly)!=25u || inspect(^data)!=10u)return 5u;
 {
  auto loan=^data;[unsigned;dyn]^ edit=^*loan;edit[2u]=37u;
  auto indirect_set=&set;indirect_set(loan);set(loan);
 }
 return data[0u]==19u && data[2u]==37u?0u:6u;
}
template<typename T>T element(const [T;dyn]^ s,unsigned i) safe {return s[i];}
template<typename Unused>unsigned fixed_element(const [unsigned;dyn]^ s,unsigned i) safe {return s[i];}
unsigned run_indexed() safe {
 unsigned data[3]={7u,11u,13u},evaluations=0u,index=2u;
 auto last=view(once(^const data,^evaluations))[index++];
 if(last!=13u || evaluations!=1u || index!=3u)return 7u;
 {
  [unsigned;dyn]^ edit=^data;index=0u;edit[index++]=17u;
  if(index!=1u)return 8u;
 }
 return element<unsigned>(^const data,0u)==17u && fixed_element<int>(^const data,2u)==13u?0u:9u;
}
unsigned read_shared_slot(const [unsigned^^;dyn]^ s) safe {
 unsigned^const^ shared=s[0u];return **shared;
}
unsigned run_slots() safe {
 unsigned y=2u;unsigned^ r=^y;auto const holder=^r;
 unsigned^const^ shared=holder;
 return **shared==2u?0u:11u;
}
unsigned read_bound(long long index) safe {
 unsigned data[3]={1u,2u,3u};const [unsigned;dyn]^ s=^const data;return s[index];
}
unsigned read_wide() safe {
 unsigned data[3]={1u,2u,3u};const [unsigned;dyn]^ s=^const data;
 unsigned __int128 index=static_cast<unsigned __int128>(1u)<<64;return s[index];
}
'''
NEGATIVES=[
 ('void bad() safe {unsigned x=1u,y=2u;unsigned^const fixed=^x;fixed=^y;}', 'const-qualified'),
 ('void bad() safe {unsigned x=1u,y=2u;unsigned^ p=^x;unsigned^const^ q=^const p;*q=^y;}', 'read-only variable'),
 ('void bad() safe {unsigned x=1u;unsigned^volatile p=^x;unsigned value=*p;}', 'volatile load'),
 ('void bad() safe {unsigned x=1u;unsigned^ p=^x;auto const holder=^p;unsigned^^ q=holder;**q=2u;}', 'cannot initialize'),
 ('void bad(const [unsigned^^;dyn]^ s) safe {unsigned^^ q=s[0u];**q=2u;}', 'cannot initialize'),
 ('void bad() safe {unsigned x=1u;unsigned^ p=^x;auto const holder=^p;unsigned^const^ q=holder;unsigned read=**q+*p;}', 'module-safety:'),
 ('const unsigned^/a bad/(a)(const [unsigned;dyn]^/a input) safe {unsigned local[3]={};const [unsigned;dyn]^ s=^const local;return ^const s[(s=input,0u)];}', 'captured slice loan'),
 ('void bad() safe {unsigned data[3]={};const [unsigned;dyn]^ s=^const data;unsigned x=s[1.5];}', 'not an integer'),
 ('void bad() safe {unsigned data[3]={};auto loan=^data;[unsigned;dyn]^ s=^*loan;(*loan)[0u]=1u;unsigned read=s[0u];}', 'module-safety:'),
 ('void bad() safe {unsigned data[3]={};auto loan=^data;[unsigned;dyn]^ s=^*loan;data[0u]=1u;unsigned read=s[0u];}', 'module-safety:'),
 ('void bad() safe {const unsigned data[2]={};[unsigned;dyn]^ s=^const data;}', 'cannot discard qualifiers'),
 ('void bad() safe {unsigned data[2]={};auto p=^data;[unsigned;dyn]^ s=p;}', 'cannot initialize'),
 ('const [unsigned;dyn]^ bad() safe {unsigned data[2]={};return ^const data;}', 'module-safety:'),
 ('void bad() safe {unsigned data[2]={};auto s=view(^const data);}', 'no matching function'),
 ('void bad() safe {unsigned data[3]={};const [unsigned;dyn]^ s=^const data;data[0u]=1u;unsigned read=s[0u];}', 'module-safety:'),
 ('void bad() safe {unsigned data[3]={};[unsigned;dyn]^ a=^data;[unsigned;dyn]^ b=^data;a[0u]=b[0u];}', 'module-safety:'),
 ('void bad() safe {unsigned data[3]={};const [unsigned;dyn]^ s=^const data;s[0u]=1u;}', 'read-only variable'),
 ('void bad(unsigned n) safe {unsigned data[n];const [unsigned;dyn]^ s=^const data;}', 'fixed array extent'),
 ('void bad() safe {const unsigned data[2]={1u,2u};mut set(data);}', 'cannot discard qualifiers'),
 ('void bad() safe {unsigned data[2]={1u,2u};set(data);}', 'unaudited mutable borrow'),
 ('const [unsigned;dyn]^ bad() safe {unsigned data[2]={1u,2u};return data;}', 'module-safety:'),
 ('unsigned bad(unsigned n) safe {unsigned data[n];return inspect(data);}', 'fixed array extent'),
 ('struct Invalid {Invalid()=delete;Invalid(const [unsigned;dyn]^ s) safe {}};void bad() safe {Invalid v;unsigned data[2]={};v=data;}', 'deleted constructor'),
]
with tempfile.TemporaryDirectory(prefix='array-slice-conversions-') as directory:
 d=pathlib.Path(directory);source=d/'main.cpp';module=d/'api.cppm';pcm=d/'api.pcm';obj=d/'api.o';exe=d/'run'
 def compile(args,okay=True,diagnostic='',checked=True):
  flags=FLAGS if checked else [arg for arg in FLAGS if arg not in ('-fcircle-safety','-fcircle-borrow-values')]
  r=subprocess.run([str(CLANG)]+flags+args,capture_output=True,text=True,timeout=120)
  assert (r.returncode==0)==okay,r.stderr
  assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr,r.stderr
  assert diagnostic in r.stderr,r.stderr
 module.write_text('export module array_slice;export {\n'+API+'}\n')
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=[opt]+san
   compile(options+['--precompile',str(module),'-o',str(pcm)])
   compile(options+['-c',str(pcm),'-o',str(obj)])
   for imported in (False,True):
    source.write_text(('import array_slice;\n' if imported else API)+'int main() safe {auto a=run();auto b=run_borrowed();auto c=run_indexed();return static_cast<int>(a?a:b?b:c?c:run_slots());}')
    compile(options+(['-fmodule-file=array_slice='+str(pcm)] if imported else [])+[str(source)]+([str(obj)] if imported else [])+['-o',str(exe)])
    r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    source.write_text('#include <cstdlib>\n#include <csignal>\n'+('import array_slice;\n' if imported else API)+
     'void panic(int) safe {unsafe {std::_Exit(77);}}int main(int argc,char** argv) safe {unsafe {std::signal(SIGABRT,panic);'
     'switch(std::atoi(argv[1])){case 1:return static_cast<int>(read_bound(-1));'
     'case 2:return static_cast<int>(read_bound(3));case 3:return static_cast<int>(read_wide());}return 0;}}')
    compile(options+(['-fmodule-file=array_slice='+str(pcm)] if imported else [])+[str(source)]+
     ([str(obj)] if imported else [])+['-o',str(exe)])
    for case in ('1','2','3'):
     r=subprocess.run([str(exe),case],capture_output=True,text=True,timeout=30)
     assert r.returncode==77,(opt,san,imported,case,r.returncode,r.stderr)
     assert 'runtime error:' not in r.stderr and 'ERROR: AddressSanitizer' not in r.stderr,r.stderr
 for imported in (False,True):
  for body,diagnostic in NEGATIVES:
   source.write_text(('import array_slice;\n' if imported else API)+body)
   compile((['-fmodule-file=array_slice='+str(pcm)] if imported else [])+['-fsyntax-only',str(source)],False,diagnostic)
 official=ROOT/'downloads/safe-cpp-reference/libsafecxx/test/compile-fail/string_view1.cxx'
 compile(['-I'+str(ROOT/'downloads/safe-cpp-reference/libsafecxx/single-header'),'-fsyntax-only',str(official)],False,'deleted constructor')
 panic=ROOT/'downloads/safe-cpp-reference/libsafecxx/test/compile-fail/panic/subscript_slice.cxx'
 support=ROOT/'downloads/safe-cpp-reference/libsafecxx/test/compile-fail/abort_handler.cxx'
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   helper=d/'abort_handler.o'
   compile([opt]+san+['-c',str(support),'-o',str(helper)],checked=False)
   compile([opt]+san+[str(panic),str(helper),'-o',str(exe)])
   r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
   assert r.returncode==1,(opt,r.returncode,r.stderr)
   assert 'runtime error:' not in r.stderr and 'ERROR: AddressSanitizer' not in r.stderr,r.stderr
print(f'Array/array-borrow to slice: exact address+extent, single evaluation, calls/returns/conversions, qualifier and loan preservation; 8 local/PCM O0/O2 plain ASan/UBSan runs, 24 signed/wide bounds panics, {2*len(NEGATIVES)} refusals, 4 untouched upstream panic executions O0/O2 plain ASan/UBSan and deleted-constructor recovery passed')
