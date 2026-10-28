#!/usr/bin/env python3
"""Stored class regions are distinct from receiver storage and each other."""
import json, os, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''export module class_regions;
export const unsigned permanent=17u;
export struct Holder/(a) {
 const unsigned^/a value;
 const unsigned^/a get(self) safe {return self.value;}
};
export struct Pair/(a,b) {
 const unsigned^/a first;
 const unsigned^/b second;
 const unsigned^/a get_first(self) safe {return self.first;}
 const unsigned^/b get_second(self) safe {return self.second;}
};
export struct Bound/(a) {
 const unsigned^/a value;
 Bound(const unsigned^/a input) safe :value(input) {}
 const unsigned^/a get(self) safe {return self.value;}
};
export template<class T> struct View/(a) {
 const T^/a value;
 const T^/a get(self) safe {return self.value;}
};
export template<class T> struct GenericBound/(a) {
 const T^/a value;
 GenericBound(const T^/a input) safe :value(input) {}
 const T^/a get(self) safe {return self.value;}
};
export template<class T> struct DeferredBound/(a) {
 const T^/a value;
 DeferredBound(const T^/a input) safe :value(input) {}
};
export template<class Unused> void deferred_safe() safe {
 unsigned long long input=19ull;DeferredBound<unsigned long long> value(^const input);
}
export template<class Unused> void deferred_unsafe() unsafe {
 unsigned short input=23;DeferredBound<unsigned short> value(^const input);
}
export struct Related/(a,b where a:b) {
 const unsigned^/a first;
 const unsigned^/b second;
 const unsigned^/b get(self) safe {return self.first;}
};
static_assert(!__is_same(decltype(&Pair::get_first),decltype(&Pair::get_second)));
export unsigned run() safe {
 unsigned input=7u;const unsigned^ result=^const input;
 {Holder object{^const input}; result=(rel object).get();}
 if(*result!=7u)return 1u;
 unsigned longer=11u;const unsigned^ first=^const longer;
 {unsigned shorter=13u;Pair pair{^const longer,^const shorter};first=(rel pair).get_first();}
 if(*first!=11u)return 2u;
 Related related{^const input,^const longer};if(*(rel related).get()!=7u)return 6u;
 Bound bound(^const input);if(*(rel bound).get()!=7u)return 3u;
 Holder indirect{^const input};auto getter=&Holder::get;
 if(*getter(rel indirect)!=7u)return 4u;
 GenericBound<unsigned> constructed(^const input);if(*(rel constructed).get()!=7u)return 8u;
 View<unsigned> view{^const input};return *(rel view).get();
}
'''
NEG=[
 ('template<class T> struct Bad/(a){const T^/a field;Bad() safe {}};template<class Unused> void deferred() safe {Bad<unsigned long long> value;}', 'class field requires an initialized borrow'),
 ('template<class T> struct Bad/(a){const T^/a field;Bad() safe {}};template<class Unused> void deferred() unsafe {Bad<unsigned long long> value;}', 'class field requires an initialized borrow'),
 ('struct Bad/(a){const unsigned^/a value;[[clang::annotate("safecpp.borrow.static")]] const unsigned^/a get(self) unsafe {return self.value;}};', 'class result lifetime cannot mix declaration borrow attributes'),
 ('struct Bad/(a,b where a:b){const unsigned^/a first;const unsigned^/b second;const unsigned^/a bad(self) safe {return self.second;}};', 'class result lifetime contract'),

 ('struct Bad/(a,b){const unsigned^/a value;Bad(const unsigned^/b input) unsafe :value(input){}};', 'class field lifetime contract'),
 ('struct Bad/(a,b){const unsigned^/a value;Bad(const unsigned^/b input) safe :value(input){}};', 'class field lifetime contract'),
 ('struct Bad/(a,b){const unsigned^/a first;const unsigned^/b second; void bad(self^) unsafe {self->first=self->second;}};', 'class field lifetime contract'),
 ('void bad() unsafe {Holder value;}', 'class field requires an initialized borrow'),
 ('void bad() unsafe {extern void* opaque;auto forged=reinterpret_cast<Holder*>(opaque);}', 'class field representation cast'),
 ('void bad() unsafe {auto forged=reinterpret_cast<decltype(&Pair::get_second)>(&Pair::get_first);}', 'class result lifetime contracts'),
 ('void bad() unsafe {auto erased=reinterpret_cast<void*>(&Holder::get);}', 'class result lifetime contracts'),

 ('struct Bad/(a,b){const unsigned^/a first;const unsigned^/b second; const unsigned^/a bad(self) safe {return self.second;}};', 'class result lifetime contract'),
 ('struct Bad/(a,b){const unsigned^/a first;const unsigned^/b second; const unsigned^/a bad(self) unsafe {return self.second;}};', 'class result lifetime contract'),
 ('struct Bad/(a,b){const unsigned^/a first;const unsigned^/b second; const unsigned^/a bad(self) safe {unsafe {return self.second;}}};', 'class result lifetime contract'),
 ('struct Bad/(a){const unsigned^/a first;unsigned owned; const unsigned^/a bad(self) safe {return ^const self.owned;}};', 'class result lifetime contract'),
 ('const unsigned^ bad() safe {unsigned input=7u;Holder object{^const input};return (rel object).get();}', 'return'),
 ('unsigned bad() safe {const unsigned^ result=^const permanent;{unsigned input=7u;Holder object{^const input};result=(rel object).get();}return *result;}', 'borrow'),
]
with tempfile.TemporaryDirectory(prefix='circle-class-regions-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'class_regions':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def check(args,okay=True,diagnostic=''):
  r=subprocess.run([str(CLANG)]+args,capture_output=True,text=True,timeout=120)
  assert (r.returncode==0)==okay,r.stderr
  assert 'PLEASE submit' not in r.stderr,r.stderr
  if diagnostic:assert diagnostic in r.stderr,r.stderr
 local=API.replace('export module class_regions;','').replace('export ','')
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+san
   m=d/'class_regions.cppm';pcm=d/'class_regions.pcm';obj=d/'class_regions.o';p=d/'client.cpp';exe=d/'run'
   m.write_text(API);check(options+['--precompile',str(m),'-o',str(pcm)]);check(options+['-c',str(pcm),'-o',str(obj)])
   for imported in (False,True):
    prefix='import class_regions;' if imported else local
    imports=['-fmodule-file=class_regions='+str(pcm)] if imported else []
    p.write_text(prefix+'int main() safe {unsigned long input=19ul;View<unsigned long> value{^const input};return run()==7u && *(rel value).get()==19ul?0:1;}');check(options+imports+[str(p)]+([str(obj)] if imported else [])+['-o',str(exe)])
    r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30);assert r.returncode==0,r.stderr+str(r.returncode)
    for source,diag in NEG:
     p.write_text(prefix+source);check(options+imports+['-fsyntax-only',str(p)],False,diag)
print(f'Class region results: local/PCM O0/O2 plain ASan/UBSan, 8 runs and {8*len(NEG)} refusals passed')
