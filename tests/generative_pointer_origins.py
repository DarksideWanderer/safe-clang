#!/usr/bin/env python3
"""Raw construction reconnects results to actual caller owners and invalidation."""
import pathlib, subprocess, tempfile, json, os

root=pathlib.Path(__file__).resolve().parents[1];clang=root/'llvm-build/bin/clang'
api='''struct View/(a){const unsigned^/a value;};
const unsigned permanent=17u;
const unsigned^/a raw/(a)(const unsigned* p) unsafe {return ^const *p;}
View/a raw_view/(a)(const unsigned* p) unsafe {return View{^const *p};}
unsigned^/a raw_mut/(a)(unsigned* p) unsafe {return ^*p;}
View/a wrapper/(a)(const unsigned* p) safe {unsafe {return raw_view(p);}}
const unsigned^/a copy/(a)(const unsigned* p) unsafe {auto q=p;return ^const *q;}
const unsigned^/a assigned/(a)(const unsigned* p) unsafe {const unsigned* q=&permanent;q=p;return ^const *q;}
const unsigned^/a selected/(a)(const unsigned* p,bool choose) unsafe {const unsigned* q=&permanent;if(choose)q=p;return ^const *q;}
extern "C" const unsigned^/a legacy_raw/(a)(const unsigned* p) unsafe;
'''
main='''int main() safe {
 unsafe {const unsigned^/static stable=raw(&permanent);unsigned stable_value=*stable;}
 unsigned input=7u;const unsigned* p=&input;auto q=p;
 unsafe {auto first=raw(q);unsigned a=*first;auto fn=&raw;auto second=fn(q);unsigned b=*second;}
 auto third=wrapper(q);unsigned c=*third.value;
 unsafe {auto fourth=copy(q);unsigned d=*fourth;auto fifth=assigned(q);unsigned e=*fifth;
 auto sixth=selected(q,true);unsigned f=*sixth;auto seventh=selected(q,false);unsigned g=*seventh;
 auto eighth=legacy_raw(q);unsigned h=*eighth;}
 {unsafe {auto mutable_value=raw_mut(&input);}*mutable_value=11u;}
 return a==7u && b==7u && c==7u && d==7u && e==7u && f==7u && g==17u && h==7u && stable_value==17u && input==11u?0:1;
}
'''
negative=[
 ('void bad() unsafe {unsigned x=1u;const unsigned^/static value=^const x;}','static borrow variable lifetime contract'),
 ('void bad() safe {unsigned x=1u;const unsigned^/static value=^const x;}','static borrow variable lifetime contract'),
 ('void bad() unsafe {unsigned x=1u;const unsigned^/static value=^const permanent;value=raw(&x);}','static borrow variable lifetime contract'),
 ('const unsigned^/static bad() safe {unsigned x=1u;unsafe {return raw(&x);}}','static return lifetime contract'),
 ('const unsigned^/static bad() unsafe {unsigned x=1u;auto p=&x;auto q=p;return copy(q);}','static return lifetime contract'),
 ('View/static bad() unsafe {unsigned x=1u;return raw_view(&x);}','static return lifetime contract'),
 ('const unsigned^/a bad/(a)() unsafe {unsigned x=1u;return raw(&x);}','generative return lifetime cannot expose'),
 ('const unsigned^/static bad() unsafe {unsigned x=1u;auto fn=&raw;return fn(&x);}','static return lifetime contract'),
 ('void bad() unsafe {unsigned x=1u;const unsigned* p=&permanent;p=&x;const unsigned^/static value=raw(p);}','static borrow variable lifetime contract'),
 ('const unsigned^/static bad(bool choose) unsafe {unsigned x=1u;const unsigned* p=&permanent;if(choose)p=&x;return raw(p);}','static return lifetime contract'),
 ('void bad(bool choose) unsafe {extern const unsigned* unknown;const unsigned* p=&permanent;if(choose)p=unknown;auto value=raw(p);}','generative raw call requires known live pointer provenance'),
 ('unsigned bad() safe {unsigned x=1u;auto value=wrapper(&x);x=2u;return *value.value;}','borrow'),
 ('unsigned bad() safe {unsigned x=1u;unsafe {auto value=raw_mut(&x);}x=2u;return *value;}','borrow'),
 ('void bad() unsafe {unsigned x=1u;auto first=raw_mut(&x);auto second=raw_mut(&x);*first=1u;*second=2u;}','generative raw call conflicts with a live borrow'),
 ('void bad() unsafe {unsigned x=1u;auto first=^x;auto second=raw(&x);*first=2u;unsigned y=*second;}','generative raw call conflicts with a live borrow'),
 ('unsigned bad() safe {const unsigned* p;{unsigned x=1u;p=&x;}unsafe {auto value=raw(p);}return *value;}','generative raw call requires known live pointer provenance'),
 ('const unsigned^/a bad/(a)(const unsigned* p) unsafe {unsigned x=1u;p=&x;return ^const *p;}','generative return lifetime cannot expose'),
 ('const unsigned^/a bad/(a)(const unsigned* p) unsafe {extern void edit(const unsigned**) unsafe;auto alias=p;edit(&p);return ^const *alias;}','generative raw borrow construction provenance is not yet modeled'),
 ('const unsigned^/a bad/(a)(const unsigned* p) unsafe {auto alias=p;delete p;return ^const *alias;}','generative raw borrow construction provenance is not yet modeled'),
 ('const unsigned^/a bad/(a)(const unsigned* p) unsafe {extern void touch(const unsigned*) unsafe;auto alias=p;touch(p);return ^const *alias;}','generative raw borrow construction provenance is not yet modeled'),
 ('void bad() unsafe {extern const unsigned* unknown;auto value=raw(unknown);}','generative raw call requires known live pointer provenance'),
]
with tempfile.TemporaryDirectory(prefix='generative-pointers-') as td:
 d=pathlib.Path(td);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'pointer_api':'safe'}}))
 source=d/'main.cpp';provider=d/'provider.c';obj=d/'provider.o';exe=d/'run'
 provider.write_text('const unsigned* legacy_raw(const unsigned* p){return p;}\n')
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy)]
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=['-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22',opt]+san
   result=subprocess.run([str(clang)]+options+['-c',str(provider),'-o',str(obj)],capture_output=True,text=True)
   assert result.returncode==0,result.stderr
   module=d/'api.cppm';pcm=d/'api.pcm';module_obj=d/'api.o'
   module.write_text('export module pointer_api;\nexport {\n'+api+'\n}\n')
   for args in (['--precompile',str(module),'-o',str(pcm)],['-c',str(pcm),'-o',str(module_obj)]):
    result=subprocess.run([str(clang)]+flags+options+args,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
   for imported in (False,True):
    prefix='import pointer_api;\n' if imported else api
    imports=['-fmodule-file=pointer_api='+str(pcm)] if imported else []
    source.write_text(prefix+main)
    result=subprocess.run([str(clang)]+flags+options+imports+[str(source),str(obj)]+([str(module_obj)] if imported else [])+['-o',str(exe)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    result=subprocess.run([str(exe)],capture_output=True,text=True,env=dict(os.environ,ASAN_OPTIONS='detect_stack_use_after_return=1'))
    assert result.returncode==0,result.stderr
    for body,diag in negative:
     source.write_text(prefix+body)
     result=subprocess.run([str(clang)]+flags+options+imports+['-fsyntax-only',str(source)],capture_output=True,text=True)
     assert result.returncode!=0 and diag in result.stderr and 'PLEASE submit' not in result.stderr,(body,result.stderr)
print('Generative raw pointer owners, copies/assignment/joins, direct/indirect/class results, safe wrappers and legacy C scalar-borrow ABI: local/PCM O0/O2 plain ASan/UBSan, 8 runs and 168 refusals; opaque invalidation remains conservative')
