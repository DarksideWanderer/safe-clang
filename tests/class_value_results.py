#!/usr/bin/env python3
"""Carried class result regions survive return, calls and function types."""
import pathlib,subprocess,tempfile,json,os
root=pathlib.Path(__file__).resolve().parents[1];clang=root/'llvm-build/bin/clang'
api='''struct View/(a) {const unsigned^/a value;};
const unsigned permanent=19u;
View/a wrap/(a)(const unsigned^/a input) safe {return View{input};}
View/a forward/(a)(View/a input) safe {return rel input;}
View/a fallback/(a)(const unsigned^/a input) safe {return View{^const permanent};}
View/a checked_unsafe/(a)(const unsigned^/a input) unsafe {return View{input};}
using Callback=View/a /(a)(const unsigned^/a) safe;
static_assert(__is_same(decltype(&wrap),Callback*));
template<class T> struct Generic/(a) {const T^/a value;};
template<class T> Generic<T>/a generic/(a)(const T^/a input) safe {return Generic<T>{input};}
struct Mutable/(a) {unsigned^/a value;};
Mutable/a take/(a)(unsigned^/a input) safe {return Mutable{rel input};}
Mutable/a transfer/(a)(Mutable/a input) safe {return rel input;}
'''
main='''int main() safe {
 unsigned unique=3u;{auto value=take(^unique);auto moved=transfer(rel value);*moved.value=11u;}if(unique!=11u)return 1;
 unsigned input=7u;auto value=wrap(^const input);unsigned first=*value.value;
 Callback* callback=&wrap;auto second=callback(^const input);unsigned next=*second.value;
 auto moved=forward(rel value);unsigned third=*moved.value;
 auto fixed=fallback(^const input);unsigned fourth=*fixed.value;
 unsigned long wide=23ul;auto fresh=generic<unsigned long>(^const wide);unsigned long fifth=*fresh.value;
 unsafe {auto other=checked_unsafe(^const input);}unsigned sixth=*other.value;
 return first==7u && next==7u && third==7u && fourth==19u && fifth==23ul && sixth==7u?0:1;
}
'''
negative=[
 ('unsigned bad() safe {unsigned input=1u;auto value=take(^input);auto other=^input;*value.value=2u;*other=3u;return input;}', 'borrow'),
 ('unsigned bad() safe {unsigned input=1u;auto value=take(^input);auto moved=transfer(rel value);return *value.value;}', 'relocated'),
 ('Mutable/a bad/(a)(unsigned^/a input) unsafe {unsigned local=1u;return Mutable{^local};}', 'returned reference does not borrow from the declared lifetime source'),
 ('View/a bad/(a)(const unsigned^/a input) safe {unsigned local=1u;return View{^const local};}', 'returned reference does not borrow from the declared lifetime source'),
 ('View/a bad/(a)(const unsigned^/a input) unsafe {unsigned local=1u;return View{^const local};}', 'returned reference does not borrow from the declared lifetime source'),
 ('View/a bad/(a,b)(const unsigned^/a input,const unsigned^/b other) unsafe {return View{other};}', 'returned reference does not borrow from the declared lifetime source'),
 ('View/a bad/(a,b)(View/a input,View/b other) unsafe {return rel other;}', 'returned reference does not borrow from the declared lifetime source'),
 ('unsigned bad() safe {unsigned input=1u;auto value=wrap(^const input);input=2u;return *value.value;}', 'borrow'),
 ('unsigned bad() safe {unsigned input=1u;Callback* cb=&wrap;auto value=cb(^const input);input=2u;return *value.value;}', 'borrow'),
 ('unsigned bad() safe {unsigned input=1u;auto value=wrap(^const input);auto moved=forward(rel value);input=2u;return *moved.value;}', 'borrow'),
 ('void bad() unsafe {using Loose=View(const unsigned^) safe;auto erased=reinterpret_cast<Loose*>(&wrap);}', 'class-value lifetime contracts'),
 ('void bad() unsafe {using Loose=View(const unsigned^) safe;extern Loose source;auto invented=reinterpret_cast<Callback*>(&source);}', 'class-value lifetime contracts'),
]
with tempfile.TemporaryDirectory(prefix='class-value-results-') as td:
 d=pathlib.Path(td);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{}}));p=d/'main.cpp';exe=d/'run'
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 for opt in ('-O0','-O2'):
  for sanitized in (False,True):
   options=flags+[opt]+(['-fsanitize=address,undefined','-fno-sanitize-recover=all'] if sanitized else [])
   p.write_text(api+main);x=subprocess.run([str(clang)]+options+[str(p),'-o',str(exe)],capture_output=True,text=True);assert x.returncode==0,x.stderr
   x=subprocess.run([str(exe)],capture_output=True,text=True,env=dict(os.environ,ASAN_OPTIONS='detect_stack_use_after_return=1'));assert x.returncode==0,x.stderr
   for body,diag in negative:
    p.write_text(api+body);x=subprocess.run([str(clang)]+options+['-fsyntax-only',str(p)],capture_output=True,text=True);assert x.returncode!=0 and diag in x.stderr and 'PLEASE submit' not in x.stderr,x.stderr
print('Carried scalar class values: direct/indirect/template/forwarded safe and unsafe results, O0/O2 plain ASan/UBSan, 4 runs and 48 refusals passed')
