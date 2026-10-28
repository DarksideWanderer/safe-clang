#!/usr/bin/env python3
"""Static class result contracts retain carried regions across values and PCM."""
import json,os,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''export module static_class_values;
export const unsigned permanent=17u;
export struct View/(a) {const unsigned^/a value;};
export View/static get() safe {return View{^const permanent};}
export template<class T> struct Generic/(a) {const T^/a value;};
export const unsigned long wide=23ul;
export Generic<unsigned long>/static generic() safe {return Generic<unsigned long>{^const wide};}
export template<class T> Generic<T>/static from_static(const T^/static input) safe {return Generic<T>{input};}
export using StaticView=View/static;
export StaticView alias() safe {return View{^const permanent};}
export View/static forward(View/static input) safe {return rel input;}
export View/static with_binder/(a)(const unsigned^/a unused) safe {return View{^const permanent};}
export void accepts(View/static input) safe {unsigned value=*input.value;}
export using Callback=View/static () safe;
static_assert(__is_same(decltype(&get),Callback*));
export unsigned run() safe {unsigned scalar=1u, replacement=5u;unsafe {__builtin_memcpy(&scalar,&replacement,sizeof(scalar));}if(scalar!=5u)return 0u;auto value=get();unsigned first=*value.value;Callback* cb=&get;auto other=cb();return first+*other.value;}
'''
NEG=[
 ('void bad() unsafe {View values[1]={{^const permanent}};void* erased=values;}', 'native borrow storage representation cannot be erased'),
 ('void bad() unsafe {View value{^const permanent};auto erased=reinterpret_cast<unsigned long>(&value);}', 'native borrow storage representation cannot be erased'),
 ('View/static bad() safe {View value{^const permanent};unsafe {unsigned local=23u;const unsigned* pointer=&local;__builtin_memcpy(&value,&pointer,sizeof(pointer));}return rel value;}', 'native borrow storage representation cannot be erased'),
 ('void bad() unsafe {View value{^const permanent};void* erased=&value;}', 'native borrow storage representation cannot be erased'),
 ('void bad() unsafe {View value{^const permanent};__builtin_memset(&value,0,sizeof(value));}', 'native borrow storage representation cannot be erased'),
 ('void bad() unsafe {const unsigned^ loan=^const permanent;void* erased=&loan;}', 'native borrow storage representation cannot be erased'),
 ('void bad() unsafe {unsigned local=1u;from_static<unsigned>(^const local);}', 'static lifetime contract'),
 ('View/static bad/(a)(const unsigned^/a unused) safe {unsigned local=1u;return View{^const local};}', 'static return lifetime contract'),
 ('View/static bad/(a)(const unsigned^/a unused) unsafe {unsigned local=1u;return View{^const local};}', 'static return lifetime contract'),
 ('void bad() unsafe {using Loose=void(View) safe;auto erased=reinterpret_cast<Loose*>(&accepts);}', 'static lifetime contracts'),
 ('void bad() unsafe {unsigned local=1u;using Bad=View/static;Bad value{^const local};}', 'static field lifetime contract'),
 ('void bad() unsafe {unsigned local=1u;View/static value{^const local};}', 'static field lifetime contract'),
 ('void bad() safe {unsigned local=1u;View value{^const local};unsafe {forward(rel value);}}', 'static lifetime contract'),
 ('void bad() unsafe {unsigned local=1u;View value{^const local};View/static target{^const permanent};target=rel value;}', 'static field lifetime contract'),
 ('View/static bad() safe {unsigned local=1u;return View{^const local};}', 'static return lifetime contract'),
 ('View/static bad() unsafe {unsigned local=1u;return View{^const local};}', 'static return lifetime contract'),
 ('View/static bad() safe {unsafe {unsigned local=1u;return View{^const local};}}', 'static return lifetime contract'),
 ('View/static bad() unsafe {thread_local const unsigned local=1u;return View{^const local};}', 'static return lifetime contract'),
 ('View/static bad(View input) unsafe {return rel input;}', 'static return lifetime contract'),
 ('void bad() unsafe {using Loose=View() safe;auto erased=reinterpret_cast<Loose*>(&get);}', 'static lifetime contracts'),
 ('void bad() unsafe {using Loose=View() safe;extern Loose source;auto invented=reinterpret_cast<Callback*>(&source);}', 'static lifetime contracts'),
]
with tempfile.TemporaryDirectory(prefix='circle-static-class-values-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'static_class_values':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def check(args,okay=True,diagnostic=''):
  x=subprocess.run([str(CLANG)]+args,capture_output=True,text=True,timeout=120)
  assert (x.returncode==0)==okay,x.stderr
  assert 'PLEASE submit' not in x.stderr,x.stderr
  if diagnostic:assert diagnostic in x.stderr,x.stderr
 local=API.replace('export module static_class_values;','').replace('export ','')
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+san;m=d/'api.cppm';pcm=d/'api.pcm';obj=d/'api.o';p=d/'client.cpp';exe=d/'run'
   m.write_text(API);check(options+['--precompile',str(m),'-o',str(pcm)]);check(options+['-c',str(pcm),'-o',str(obj)])
   for imported in (False,True):
    prefix='import static_class_values;' if imported else local
    imports=['-fmodule-file=static_class_values='+str(pcm)] if imported else []
    p.write_text(prefix+'const unsigned long long big=29ull;int main() safe {auto fresh=from_static<unsigned long long>(^const big);unsigned long long k=*fresh.value;unsigned local=1u;auto bound=with_binder(^const local);unsigned first=*bound.value;unsigned result=run();auto value=generic();unsigned long n=*value.value;auto other=forward(alias());return k==29ull && first==17u && result==34u && n==23ul && *other.value==17u?0:1;}')
    check(options+imports+[str(p)]+([str(obj)] if imported else [])+['-o',str(exe)])
    x=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30);assert x.returncode==0,x.stderr+str(x.returncode)
    for source,diag in NEG:
     p.write_text(prefix+source);check(options+imports+['-fsyntax-only',str(p)],False,diag)
print(f'Static class results, direct/indirect and template values: local/PCM O0/O2 plain ASan/UBSan, 8 runs and {8*len(NEG)} refusals passed')
