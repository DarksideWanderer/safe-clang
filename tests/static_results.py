#!/usr/bin/env python3
"""Built-in static result contracts survive direct/indirect calls and PCM."""
import json,os,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''export module static_results;
export const unsigned permanent=7u;
export const unsigned^/static get() safe {return ^const permanent;}
export const unsigned^/L bound/(where L:static)() safe {return ^const permanent;}
static_assert(__is_same(decltype(&get),decltype(&bound)));
export const unsigned^/a arbitrary/(a)() safe {return ^const permanent;}
static_assert(!__is_same(decltype(&get),decltype(&arbitrary)));
export const unsigned^/a longer/(a)(const unsigned^/a input) safe {return ^const permanent;}
export const unsigned^/static forward/(where L:static)(const unsigned^/L value) safe {return value;}
export using Callback=const unsigned^/static () safe;
static_assert(__is_same(decltype(&get),Callback*));
export unsigned inspect_handle(const unsigned^/static input) safe {
 auto handle=^const input;auto comma=^const (0u,input);
 auto branch=^const (*input==7u?input:input);
 return **handle==**comma && **comma==**branch?**handle:0u;
}
export unsigned run() safe {if(inspect_handle(get())!=7u)return 0u;Callback* cb=&get;unsigned local=1u;return *cb()+*forward(get())+*longer(^const local);}
'''
NEGATIVES=(
 ('using Loan=const unsigned^/static;const Loan^/static bad(const unsigned^/static input) safe {return ^const (0u,input);}', 'static return lifetime contract'),
 ('using Loan=const unsigned^/static;const Loan^/static bad(bool flag,const unsigned^/static input) safe {return ^const (flag?input:input);}', 'static return lifetime contract'),
 ('using Loan=const unsigned^/static;const Loan^/static bad(bool flag,const unsigned^/static input) unsafe {return ^const (flag?input:(0u,input));}', 'static return lifetime contract'),
 ('using Loan=const unsigned^/static;const Loan^/static bad(const unsigned^/static input) safe {return ^const input;}', 'static return lifetime contract'),
 ('using Loan=const unsigned^/static;const Loan^/static bad(const unsigned^/static input) unsafe {return ^const input;}', 'static return lifetime contract'),
 ('using Loan=const unsigned^/static;const Loan^/static bad/(where L:static)(const unsigned^/L input) safe {return ^const input;}', 'static return lifetime contract'),
 ('extern const unsigned* pointer;const unsigned^/static bad() unsafe {return ^const *pointer;}', 'static return lifetime contract'),
 ('unsigned state=1u;const unsigned^/static getter() safe {unsafe {return ^const state;}} void writer() safe {unsafe {++state;}} unsigned bad() safe {auto loan=getter();writer();return *loan;}', 'mutable global storage'),
 ('const unsigned^/static bad() safe {unsigned local=1u;return ^const local;}', 'static return lifetime contract'),
 ('const unsigned^/static bad() safe {unsigned local=1u;unsafe {return ^const local;}}', 'static return lifetime contract'),
 ('const unsigned^/static bad() unsafe {unsigned local=1u;return ^const local;}', 'static return lifetime contract'),
 ('const unsigned^/L bad/(where L:static)() unsafe {unsigned local=1u;return ^const local;}', 'static return lifetime contract'),
 ('const unsigned^/static bad() safe {thread_local const unsigned local=1u;return ^const local;}', 'static return lifetime contract'),
 ('const unsigned^/static bad() unsafe {thread_local const unsigned local=1u;return ^const local;}', 'static return lifetime contract'),
 ('const unsigned^/static bad(const unsigned^ value) safe {return value;}', 'static return lifetime contract'),
 ('const unsigned^/static bad(const unsigned^ value) unsafe {return value;}', 'static return lifetime contract'),
 ('const unsigned^/static bad() unsafe {extern const unsigned^ unknown;return unknown;}', 'static return lifetime contract'),
 ('const unsigned^/static bad() unsafe {const unsigned^ local=^const permanent;return ^const local;}', 'error:'),
 ('void bad() unsafe {using Loose=const unsigned^() safe;auto f=reinterpret_cast<Loose*>(&get);}', 'error:'),
 ('void bad() unsafe {using Loose=const unsigned^() unsafe;extern Loose source;auto f=reinterpret_cast<Callback*>(&source);}', 'static lifetime contracts'),
 ('void bad() unsafe {extern void* unknown;auto f=reinterpret_cast<Callback*>(unknown);}', 'static lifetime contracts'),
)
with tempfile.TemporaryDirectory(prefix='circle-static-results-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json'
 policy.write_text(json.dumps({'version':1,'modules':{'static_results':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def check(args,okay=True,diagnostic=''):
  r=subprocess.run([str(CLANG)]+args,capture_output=True,text=True,timeout=120)
  assert (r.returncode==0)==okay,r.stderr+'\n'+str(args)+'\n'+(d/'client.cpp').read_text() if (d/'client.cpp').exists() else r.stderr
  assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr,r.stderr
  if diagnostic:assert diagnostic in r.stderr,r.stderr
  return r
 for opt in ('-O0','-O2'):
  for sanitizer in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+sanitizer
   m=d/'static_results.cppm';pcm=d/'static_results.pcm';obj=d/'static_results.o';p=d/'client.cpp';binary=d/'run'
   m.write_text(API)
   check(options+['--precompile',str(m),'-o',str(pcm)])
   check(options+['-c',str(pcm),'-o',str(obj)])
   p.write_text('import static_results;int main() safe {return run()==21u?0:1;}')
   check(options+['-fmodule-file=static_results='+str(pcm),str(p),str(obj),'-o',str(binary)])
   x=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
   assert x.returncode==0,x.stderr+str(x.returncode)
   p.write_text(API.replace('export module static_results;','').replace('export ', '')+'int main() safe {return run()==21u?0:1;}')
   check(options+[str(p),'-o',str(binary)])
   x=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
   assert x.returncode==0,x.stderr+str(x.returncode)
   for text,diag in NEGATIVES:
    for imported in (False,True):
     p.write_text(('import static_results;' if imported else API.replace('export module static_results;','').replace('export ',''))+text)
     check(options+(['-fmodule-file=static_results='+str(pcm)] if imported else [])+['-fsyntax-only',str(p)],False,diag)
print(f'Static results: explicit /static and result-only binder type identity, direct/indirect/forwarding, local/PCM O0/O2 plain ASan/UBSan; {len(NEGATIVES)*8} refusals including parameter-handle storage, unsafe return bodies, TLS/unknown origins and invented/erased contracts passed')
