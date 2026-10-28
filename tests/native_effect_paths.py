#!/usr/bin/env python3
"""Native raw pointer values and normal versus exceptional noreturn exits."""
import json,os,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''module;
extern "C" void may_throw();
extern "C" [[noreturn]] void stop();
export module effect_paths;
export const unsigned* raw(const unsigned* value) safe {return value;}
export [[noreturn]] void wrapper() safe {unsafe {may_throw();stop();}}
export unsigned drops=0u;
export unsigned drop_count() safe {unsafe {return drops;}}
export struct Guard {unsigned value;Guard(unsigned input) safe :value(input) {} ~Guard() safe {unsafe {++drops;}}};
export template<class T> struct Template {
 static unsigned scope() safe {
  unsafe {drops=0u;}
  {unsafe {Guard first(9u);} if(drop_count()!=0u || first.value!=9u)return 1u;
   {unsafe {Guard nested(11u);} if(drop_count()!=0u || nested.value!=11u)return 2u;}
   if(drop_count()!=1u)return 3u;}
  if(drop_count()!=2u)return 4u;
  if(true)unsafe {Guard branch(13u);}
  if(drop_count()!=3u)return 5u;
  try {unsafe {Guard value(17u);} if(drop_count()!=3u || value.value!=17u)return 6u;throw 7;}
  catch(int value) {if(value!=7 || drop_count()!=4u)return 7u;}
  return 0u;
 }
 static unsigned value() safe {unsafe {unsigned result=5u;}return result;}
 [[noreturn]] static void wrapper() safe {unsafe {may_throw();stop();}}
};
export unsigned run() safe {unsigned value=3u;const unsigned* p;unsafe {p=&value;} auto q=raw(p);unsafe {return *q;}}
'''
NEGATIVES=(
 ('template<class T> [[noreturn]] void bad(bool value) safe {unsafe {if(value)stop();}} void instantiate() safe {bad<int>(false);}', 'noreturn function can complete normally'),
 ('template<class T> void bad() safe {unsafe {auto callback=[] {may_throw();};callback();}} void instantiate() safe {bad<int>();}', 'unsafe or unclassified'),
 ('template<class T> void bad() safe {unsafe {struct Nested {static void invoke() safe {may_throw();}};Nested::invoke();}} void instantiate() safe {bad<int>();}', 'unsafe or unclassified'),
 ('unsigned bad(const unsigned* p) safe {return *raw(p);}', 'raw pointer dereference'),
 ('[[noreturn]] void bad() safe {}', 'noreturn function can complete normally'),
 ('[[noreturn]] void bad() safe {return;}', 'noreturn function can complete normally'),
 ('[[noreturn]] void bad(bool value) safe {if(value) throw 1;}', 'noreturn function can complete normally'),
 ('[[noreturn]] void bad() safe {try {throw 1;}catch(int) {}}', 'noreturn function can complete normally'),
)
with tempfile.TemporaryDirectory(prefix='circle-effect-paths-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'effect_paths':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def check(args,okay=True,diagnostic=''):
  r=subprocess.run([str(CLANG)]+args,capture_output=True,text=True,timeout=120)
  assert (r.returncode==0)==okay,r.stderr
  assert 'PLEASE submit' not in r.stderr,r.stderr
  if diagnostic:assert diagnostic in r.stderr,r.stderr
 local=API.replace('module;','').replace('export module effect_paths;','').replace('export ','')
 main='int main() safe {if(run()!=3u || Template<int>::value()!=5u || Template<int>::scope()!=0u)return 1;unsigned caught=0u;try {wrapper();}catch(int value) {if(value!=7)return 2;++caught;}try {Template<int>::wrapper();}catch(int value) {if(value!=7)return 3;++caught;}return caught==2u?0:4;}'
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+san
   provider=d/'provider.cpp';provider.write_text('extern "C" void may_throw(){throw 7;}extern "C" [[noreturn]] void stop(){__builtin_trap();}')
   provider_obj=d/'provider.o';check(['--driver-mode=g++','-std=c++20',opt]+san+['-c',str(provider),'-o',str(provider_obj)])
   m=d/'effect_paths.cppm';pcm=d/'effect_paths.pcm';obj=d/'effect_paths.o';p=d/'client.cpp';exe=d/'run'
   m.write_text(API);check(options+['--precompile',str(m),'-o',str(pcm)]);check(options+['-c',str(pcm),'-o',str(obj)])
   for imported in (False,True):
    prefix='import effect_paths;' if imported else local
    imports=['-fmodule-file=effect_paths='+str(pcm)] if imported else []
    p.write_text(prefix+main);check(options+imports+[str(p),str(provider_obj)]+([str(obj)] if imported else [])+['-o',str(exe)])
    r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30);assert r.returncode==0,r.stderr+str(r.returncode)
    for source,diag in NEGATIVES:
     p.write_text(prefix+'extern "C" void may_throw();extern "C" [[noreturn]] void stop();'+source);check(options+imports+['-fsyntax-only',str(p)],False,diag)
print('Native raw pointer value returns retain unsafe dereference; noreturn normal/EH exits, transparent unsafe scope and exact normal/EH/branch destruction, throwing linked legacy provider: local/PCM O0/O2 plain ASan/UBSan, 8 runs and 64 refusals including template fallthrough and independent lambda/nested method safety passed')
