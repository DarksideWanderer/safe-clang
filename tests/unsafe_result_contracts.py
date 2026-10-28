#!/usr/bin/env python3
"""Explicit unsafe bodies must preserve declared return lifetime sources."""
import json,os,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''export module unsafe_result_contracts;
export const unsigned permanent=17u;
export const unsigned^/a checked/(a)(const unsigned^/a input) unsafe {return input;}
export const unsigned^/a permanent_result/(a)(const unsigned^/a input) unsafe {return ^const permanent;}
export const unsigned^/a wrapped/(a)(const unsigned^/a input) safe {unsafe {return checked(input);}}
export struct View/(a) {const unsigned^/a value;};
export unsigned run() safe {
 unsigned input=7u;
 unsafe {auto loan=checked(^const input);auto other=permanent_result(^const input);}
 if(*loan!=7u || *other!=17u)return 1u;
 unsafe {auto cb=&checked;auto indirect=cb(^const input);}
 if(*indirect!=7u)return 2u;
 return *wrapped(^const input);
}
'''
NEG=[
 ('View/a dangling/(a)() unsafe {unsigned local=17u;return View{^const local};}', 'generative return lifetime cannot expose a local or input-bound owner'),
 ('const unsigned^/a bad/(a)(const unsigned^/a input) unsafe {unsigned local=17u;return ^const local;}', 'returned reference does not borrow from the declared lifetime source'),
 ('const unsigned^/a bad/(a,b)(const unsigned^/a input,const unsigned^/b other) unsafe {return other;}', 'returned reference does not borrow from the declared lifetime source'),
 ('const unsigned^/a bad/(a)(const unsigned^/a input) safe {unsafe {unsigned local=17u;return ^const local;}}', 'returned reference does not borrow from the declared lifetime source'),
 ('[[clang::annotate("safecpp.borrow.from:input")]] View bad(View input) unsafe {unsigned local=17u;return View{^const local};}', 'returned reference does not borrow from the declared lifetime source'),
 ('const unsigned^/a bad/(a)(const unsigned^/a input) unsafe {unsigned other=1u;unsafe {return checked(^const other);}}', 'returned reference does not borrow from the declared lifetime source'),
 ('void bad() safe {unsigned input=7u;checked(^const input);}', 'call to unsafe or unclassified function'),
 ('void bad() safe {unsafe {auto fn=[](const unsigned^ input) {checked(input);};}}', 'call to unsafe or unclassified function'),
]
UNMODELED=[
 ('View unknown() unsafe {unsigned local=17u;return View{^const local};}', 'native borrow result requires a checked lifetime contract'),
 ('const unsigned^ unknown() unsafe {unsigned local=17u;return ^const local;}', 'native borrow result requires a checked lifetime contract'),
]
with tempfile.TemporaryDirectory(prefix='circle-unsafe-results-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'unsafe_result_contracts':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def check(args,okay=True,diagnostic=''):
  x=subprocess.run([str(CLANG)]+args,capture_output=True,text=True,timeout=120)
  assert (x.returncode==0)==okay,x.stderr
  assert 'PLEASE submit' not in x.stderr,x.stderr
  if diagnostic:assert diagnostic in x.stderr,x.stderr
 local=API.replace('export module unsafe_result_contracts;','').replace('export ','')
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+san;m=d/'api.cppm';pcm=d/'api.pcm';obj=d/'api.o';p=d/'client.cpp';exe=d/'run'
   m.write_text(API);check(options+['--precompile',str(m),'-o',str(pcm)]);check(options+['-c',str(pcm),'-o',str(obj)])
   for imported in (False,True):
    prefix='import unsafe_result_contracts;' if imported else local
    imports=['-fmodule-file=unsafe_result_contracts='+str(pcm)] if imported else []
    p.write_text(prefix+'int main() safe {return run()==7u?0:1;}')
    check(options+imports+[str(p)]+([str(obj)] if imported else [])+['-o',str(exe)])
    x=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30,env=dict(os.environ,ASAN_OPTIONS='detect_stack_use_after_return=1'));assert x.returncode==0,x.stderr+str(x.returncode)
    for source,diag in NEG+UNMODELED:
     p.write_text(prefix+source);check(options+imports+['-fsyntax-only',str(p)],False,diag)
print(f'Unsafe checked return sources, indirect calls and safe wrappers: local/PCM O0/O2 plain ASan/UBSan, 8 runs, {8*len(NEG)} contract/permission refusals and {8*len(UNMODELED)} explicitly unmodeled signatures refused')
