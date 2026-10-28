#!/usr/bin/env python3
"""Result-only lifetime identities, body contracts, and indirect calls."""
import json, os, pathlib, subprocess, tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = root/'llvm-build/bin/clang'
api = '''const unsigned global=7u;
struct View/(a) {const unsigned^/a value;};
const unsigned^/a make/(a)() safe {return ^const global;}
View/a make_view/(a)() safe {return View{^const global};}
View/a unsafe_view/(a)() unsafe {return View{^const global};}
using Primitive=const unsigned^/a /(a)() safe;
using Renamed=const unsigned^/b /(b)() safe;
using Static=const unsigned^/static () safe;
using Class=View/a /(a)() safe;
using ClassRenamed=View/b /(b)() safe;
using ClassStatic=View/static () safe;
using BoundClass=View/a /(where a:static)() safe;
static_assert(__is_same(ClassStatic,BoundClass));
static_assert(__is_same(Primitive,Renamed));
static_assert(!__is_same(Primitive,Static));
static_assert(__is_same(Class,ClassRenamed));
static_assert(!__is_same(Class,ClassStatic));
static_assert(__is_same(decltype(&make),Primitive*));
static_assert(__is_same(decltype(&make_view),Class*));
template<class T> struct Generic/(a) {const T^/a value;};
template<class T> Generic<T>/a fresh/(a)() safe {
 static const T value=13u;return Generic<T>{^const value};
}
const [char;dyn]^/a raw_slice/(a)(const char* p,unsigned long n) safe {
 return ^*__slice_pointer(p,n);
}
const unsigned^/a raw/(a)(void* p) unsafe {return ^const *static_cast<const unsigned*>(p);}
View/a offset_element/(a)(const unsigned* p) unsafe {return View{^const *(p+1u)};}
View/a runtime_offset/(a)(const unsigned* p,unsigned k) unsafe {return View{^const *(p+k)};}
View/a backwards_offset/(a)(const unsigned* p) unsafe {return View{^const *(p-1u)};}
'''
main = '''int main() safe {
 Primitive* p=&make;Class* q=&make_view;
 unsigned first=*make();unsigned second=*p();
 auto third_view=make_view();unsigned third=*third_view.value;
 auto fourth_view=q();unsigned fourth=*fourth_view.value;
 auto fifth_view=fresh<unsigned>();unsigned fifth=*fifth_view.value;
 unsafe {auto sixth_view=unsafe_view();unsigned sixth=*sixth_view.value;}
 unsigned seventh=0u;
 {char letters[3]={'a','b','c'};auto bytes=raw_slice(letters,3u);
  seventh=static_cast<unsigned>(bytes~length)+static_cast<unsigned>(bytes[2u]);}
 unsigned eighth=0u;
 unsafe {unsigned word=9u;auto through_void=raw(&word);eighth=*through_void;}
 unsigned ninth=0u;
 unsafe {unsigned words[2]={11u,22u};auto ninth_view=offset_element(&words[0]);ninth=*ninth_view.value;}
 unsigned tenth=0u,eleventh=0u;
 unsafe {unsigned more_words[2]={33u,44u};auto tenth_view=runtime_offset(&more_words[0],1u);tenth=*tenth_view.value;
  auto eleventh_view=backwards_offset(&more_words[1]);eleventh=*eleventh_view.value;}
 return first==7u && second==7u && third==7u &&
        fourth==7u && fifth==13u && sixth==7u && seventh==3u+static_cast<unsigned>('c')
        && eighth==9u && ninth==22u && tenth==44u && eleventh==33u?0:1;
}
'''
negative = [
 ('const unsigned^/a bad/(a)() safe {unsigned local=1u;return ^const local;}', 'generative return lifetime cannot expose'),
 ('const unsigned^/a bad/(a)() unsafe {unsigned local=1u;return ^const local;}', 'generative return lifetime cannot expose'),
 ('View/a bad/(a)() safe {unsigned local=1u;return View{^const local};}', 'generative return lifetime cannot expose'),
 ('View/a bad/(a)() unsafe {unsigned local=1u;return View{^const local};}', 'generative return lifetime cannot expose'),
 ('const unsigned^/a bad/(a,b)(const unsigned^/b input) unsafe {return input;}', 'generative return lifetime cannot expose'),
 ('View/a bad/(a,b)(View/b input) unsafe {return rel input;}', 'generative return lifetime cannot expose'),
 ('View/a bad/(a)(unsigned k) unsafe {unsigned words[2]={1u,2u};const unsigned* p=words;return View{^const *(p+k)};}', 'generative raw borrow construction provenance is not yet modeled'),
 ('void bad() unsafe {auto p=reinterpret_cast<Static*>(&make);}', 'generative lifetime contracts'),
 ('void bad() unsafe {using Loose=const unsigned^ () safe;auto p=reinterpret_cast<Loose*>(&make);}', 'generative lifetime contracts'),
 ('void bad() unsafe {extern Static permanent;auto p=reinterpret_cast<Primitive*>(&permanent);}', 'generative lifetime contracts'),
 ('void bad() unsafe {auto p=reinterpret_cast<ClassStatic*>(&make_view);}', 'class-value lifetime contracts'),
 ('void bad() safe {unsafe {auto p=[]() {unsafe_view();};}}', 'call to unsafe'),
]
# An offset from an opaque pointer to a single element is a claim the
# unchecked body may make, and it keeps the origin that pointer already
# names. The same holds for a runtime-computed or backwards offset; only an
# offset from a known local owner needs a placement proof.
# A slice result built from raw parts hands its extent to the call, which has
# to place it: the length of one slice, or a counted suffix of a known array.
extents = [
 (' unsigned bad(const char* p,unsigned long n) safe {auto s=raw_slice(p,n);'
  'return static_cast<unsigned>((*s)~length);}',
  'slice extent must be the length of a slice or a counted suffix of a known array'),
 (' unsigned bad() safe {char local[4]={};auto s=raw_slice(local,9ul);'
  'return static_cast<unsigned>((*s)~length);}',
  'slice extent must be the length of a slice or a counted suffix of a known array'),
 (' unsigned bad() safe {char local[4]={};auto fn=&raw_slice;auto s=fn(local,3ul);'
  'return static_cast<unsigned>((*s)~length);}',
  'slice extent of an indirect call must be placed at the call site'),
]
with tempfile.TemporaryDirectory(prefix='generative-lifetimes-') as td:
 d=pathlib.Path(td);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'generative_api':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 source=d/'main.cpp';exe=d/'run'
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+san
   module=d/'api.cppm';pcm=d/'api.pcm';obj=d/'api.o'
   module.write_text('export module generative_api;\nexport {\n'+api+'\n}\n')
   for args in (['--precompile',str(module),'-o',str(pcm)],['-c',str(pcm),'-o',str(obj)]):
    result=subprocess.run([str(clang)]+options+args,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
   for imported in (False,True):
    prefix='import generative_api;\n' if imported else api
    imports=['-fmodule-file=generative_api='+str(pcm)] if imported else []
    source.write_text(prefix+main)
    result=subprocess.run([str(clang)]+options+imports+[str(source)]+([str(obj)] if imported else [])+['-o',str(exe)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    result=subprocess.run([str(exe)],capture_output=True,text=True,env=dict(os.environ,ASAN_OPTIONS='detect_stack_use_after_return=1'))
    assert result.returncode==0,result.stderr
    for body,diag in negative+extents:
     source.write_text(prefix+body)
     result=subprocess.run([str(clang)]+options+imports+['-fsyntax-only',str(source)],capture_output=True,text=True)
     assert result.returncode!=0 and diag in result.stderr and 'PLEASE submit' not in result.stderr,result.stderr
print('Result-only lifetime identities, scalar class results and a raw-parts slice whose extent the '
      'call places, including runtime and backwards offsets from opaque pointers: local/PCM O0/O2 '
      'plain ASan/UBSan, 8 runs and {} contract refusals'.format(8*len(negative)))
