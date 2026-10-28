#!/usr/bin/env python3
"""Concrete and deduced template native impl calls; full ordering/dyn remain open."""
import json,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
clang=ROOT/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='circle-impl-call-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json'
 policy.write_text(json.dumps({'version':1,'modules':{'impl_calls':'safe'}}))
 base=[str(clang),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-std=c++20','-fmodule-safe','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy)]
 declarations='''interface I {unsigned get(const self^) safe; void set(self^,unsigned x) safe;};
struct V {unsigned value;};
impl V:I {
 unsigned get(const self^) safe override {return self->value;}
 void set(self^,unsigned x) safe override {self->value=x;}
};
template<class T> struct G {unsigned value;};
template<class T> impl G<T>:I {
 unsigned get(const self^) safe override {return self->value;}
 void set(self^,unsigned x) safe override {self->value=x;}
};
interface Iterator {typename item_type; item_type next(self^) safe;};
template<class T> struct It {T value;};
template<class T> impl It<T>:Iterator {
 using item_type=T;
 T next(self^) safe override {return self->value;}
};
'''
 main='int main() {V v{7u}; G<unsigned> g{3u}; G<long> h{4u}; It<unsigned> it{17u}; auto next=mut it.Iterator::next(); mut v.I::set(9u); mut g.I::set(11u); mut h.I::set(13u); return v.I::get()==9u && g.I::get()==11u && h.I::get()==13u && next==17u ? 0 : 1;}'
 def run(args):
  r=subprocess.run(args,capture_output=True,text=True)
  assert r.returncode==0,r.stderr
 for optimization in ('-O0','-O2'):
  for sanitize in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   source=d/'main.cpp';source.write_text(declarations+main);binary=d/'program'
   run(base+[optimization,*sanitize,str(source),'-o',str(binary)])
   run([str(binary)])
   module=d/'impl_calls.cppm';pcm=d/'impl_calls.pcm';obj=d/'impl_calls.o'
   module.write_text('export module impl_calls;\nexport '+declarations.replace('struct V','export struct V').replace('template<class T> struct G', 'export template<class T> struct G').replace('interface Iterator', 'export interface Iterator').replace('template<class T> struct It', 'export template<class T> struct It'))
   run(base+[optimization,*sanitize,'--precompile',str(module),'-o',str(pcm)])
   run(base+[optimization,*sanitize,'-c',str(pcm),'-o',str(obj)])
   source.write_text('import impl_calls;\n'+main)
   run(base+[optimization,*sanitize,'-fprebuilt-module-path='+str(d),str(source),str(obj),'-o',str(binary)])
   run([str(binary)])
   bad_import=d/'bad_import.cpp'
   bad_import.write_text('import impl_calls; void f(const V^ v) safe {mut v.I::set(9u);}')
   r=subprocess.run(base+[optimization,*sanitize,'-fprebuilt-module-path='+str(d),'-fsyntax-only',str(bad_import)],capture_output=True,text=True)
   assert r.returncode and "no viable conversion from 'const V' to 'V ^'" in r.stderr,r.stderr
   assert 'PLEASE submit' not in r.stderr,r.stderr
 for source,expected in [
  ('interface I {unsigned get(const self^) safe;}; struct V {}; unsigned f(const V^ v) safe {return v.I::get();}','requires a modeled concrete impl method'),
  (declarations+'void f(const V^ v) safe {mut v.I::set(9u);}', "no viable conversion from 'const V' to 'V ^'"),
  (declarations+'void f() safe {const V v{1u}; mut v.I::set(9u);}', "no viable conversion from 'const V' to 'V ^'"),
  ('extern \"C\" unsigned external(); interface I {unsigned get(const self^) safe;}; struct V {}; impl V:I {unsigned get(const self^) safe {return external();}};', 'requires an explicit SAFETY_UNSAFE block'),
  ('interface I {unsigned get(const self^) safe;}; template<class T> struct G {T value;}; template<class T> impl G<T>:I {T get(const self^) safe override {return self->value;}}; unsigned f() {G<float> g{1.0f}; return g.I::get();}', 'no method matching the substituted contract'),
  (declarations+'template<class T> impl G<T>:I {unsigned get(const self^) safe override {return self->value;} void set(self^,unsigned x) safe override {self->value=x;}}; unsigned f() {G<unsigned> g{1u}; return g.I::get();}', 'selection is ambiguous'),
  ('extern "C" unsigned external(); interface I {unsigned get(const self^) safe;}; template<class T> struct G {}; template<class T> impl G<T>:I {unsigned get(const self^) safe override {return external();}};', 'requires an explicit SAFETY_UNSAFE block'),
 ]:
  path=d/'bad.cpp';path.write_text(source)
  r=subprocess.run(base+['-fsyntax-only',str(path)],capture_output=True,text=True)
  assert r.returncode and expected in r.stderr,r.stderr
  assert 'PLEASE submit' not in r.stderr,r.stderr
print('Concrete and deduced template native impl shared/mutable calls execute across PCM at O0/O2 with ASan/UBSan; missing impl, const mutation, invalid instantiated contract and ambiguous templates refused; full ordering/dyn remain incomplete')
