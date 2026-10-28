#!/usr/bin/env python3
"""An unsafe caller must honor a checked borrowed-element owner contract."""
import pathlib,subprocess,tempfile,json,os
root=pathlib.Path(__file__).resolve().parents[1];clang=root/'llvm-build/bin/clang'
api='''struct Owner {unsigned value;Owner() safe :value(7u){}};
struct View {const unsigned& value;};
struct Container {
 const Owner& owner;
 unsigned copied=0u;
 [[clang::annotate("safecpp.stores.borrow:input")]] Container(const Owner& input):owner(input){}
 [[clang::annotate("safecpp.unsafe.adopts.borrow:value"),clang::annotate("safecpp.unsafe.mutates.storage")]] void push(const View& value) safe;
};
void Container::push(const View& renamed) safe {copied=renamed.value;}
'''
positive='''unsigned safe_run() safe {Owner owner;Container values(owner);View view{owner.value};values.push(view);return values.copied;}
unsigned unsafe_run() unsafe {Owner owner;Container values(owner);View view{owner.value};values.push(view);return values.copied;}
int main() safe {unsigned first=safe_run();unsafe {unsigned second=unsafe_run();}return first==7u && second==7u?0:1;}
'''
negative=[
 'void bad() safe {Owner owner;unsigned foreign=2u;Container values(owner);View view{foreign};values.push(view);}',
 'void bad() safe {Owner owner;unsigned foreign=2u;Container values(owner);View view{foreign};unsafe {values.push(view);}}',
 'void bad() unsafe {Owner owner;unsigned foreign=2u;Container values(owner);View view{foreign};values.push(view);}',
 'void bad() unsafe {Owner first,second;Container values(first);View view{second.value};values.push(view);}',
 'void bad() unsafe {Owner owner;Container values(owner);{unsigned local=2u;View view{local};values.push(view);}}',
]
unmodeled=['void bad() unsafe {auto method=&Container::push;}', 'void bad() safe {auto method=&Container::push;}']
invalid=['struct Invalid {[[clang::annotate("safecpp.unsafe.adopts.borrow:typo")]] void push(const View& value) unsafe {}};', 'struct Invalid {[[clang::annotate("safecpp.unsafe.adopts.borrow:value")]] static void push(const View& value) {}};', 'struct Invalid {[[clang::annotate("safecpp.unsafe.adopts.borrow:value")]] void push(unsigned value) {}};']
with tempfile.TemporaryDirectory(prefix='adoption-contracts-') as td:
 d=pathlib.Path(td);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{}}));source=d/'main.cpp';exe=d/'run'
 flags=['--driver-mode=g++','-std=c++20','-fmodule-safe','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 for opt in ('-O0','-O2'):
  for sanitized in (False,True):
   options=flags+[opt]+(['-fsanitize=address,undefined','-fno-sanitize-recover=all'] if sanitized else [])
   source.write_text(api+positive);x=subprocess.run([str(clang)]+options+[str(source),'-o',str(exe)],capture_output=True,text=True);assert x.returncode==0,x.stderr
   x=subprocess.run([str(exe)],capture_output=True,text=True,env=dict(os.environ,ASAN_OPTIONS='detect_stack_use_after_return=1'));assert x.returncode==0,x.stderr
   for body in negative:
    source.write_text(api+body);x=subprocess.run([str(clang)]+options+['-fsyntax-only',str(source)],capture_output=True,text=True);assert x.returncode!=0 and 'container element borrows outside the declared owner region' in x.stderr and 'PLEASE submit' not in x.stderr,x.stderr
   for body,diagnostic in [(b,'indirect borrowed-element owner contracts are not yet modeled') for b in unmodeled]+[(b,'invalid borrowed-element owner contract') for b in invalid]:
    source.write_text(api+body);x=subprocess.run([str(clang)]+options+['-fsyntax-only',str(source)],capture_output=True,text=True);assert x.returncode!=0 and diagnostic in x.stderr and 'PLEASE submit' not in x.stderr,x.stderr
print('Borrowed-element owner contracts in safe/explicit unsafe/unsafe functions: O0/O2 plain ASan/UBSan, 4 runs, 20 owner-source refusals, 12 invalid contract refusals and 8 explicitly unmodeled indirect exposures refused')
