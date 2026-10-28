#!/usr/bin/env python3
"""Checked exceptional destruction and cleanup across PCM, at O0 and O2."""
import pathlib
import subprocess
import sys
import tempfile

clang, plugin, root = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safety-exception-cleanup-') as directory:
    tmp = pathlib.Path(directory)
    for optimization in ('-O0', '-O2'):
        flags = ['-std=c++20', optimization, '-fsanitize=address,undefined',
                 '-fno-sanitize-recover=all', '-fprebuilt-module-path='+str(tmp),
                 '-I'+root+'/include']
        checked = [clang]+flags+['-Xclang', '-load', '-Xclang', plugin,
                                '-Xclang', '-add-plugin', '-Xclang', 'module-safety',
                                '-Xclang', '-plugin-arg-module-safety', '-Xclang', 'safe']

        def compile(arguments, ok=True, needle=''):
            result = subprocess.run(arguments, text=True, capture_output=True, timeout=60)
            assert (result.returncode == 0) == ok, result.stderr
            assert needle in result.stderr, result.stderr
            assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr

        api = tmp/'drops.cppm'
        api.write_text('''module;
#include "module_safety.h"
#include <typeinfo>
export module drops;
export struct Drop {
  unsigned& count;
  SAFETY_STORES_BORROW(c) explicit Drop(unsigned& c) noexcept :count(c){}
  ~Drop() noexcept(false){++count;throw 7u;}
};
export struct Member {
  Drop value;
  SAFETY_STORES_BORROW(c) explicit Member(unsigned& c) noexcept :value(c){}
  ~Member() noexcept(false) try {} catch(...){throw;}
};
export struct Base:Drop {
  SAFETY_STORES_BORROW(c) explicit Base(unsigned& c) noexcept :Drop(c){}
  ~Base() noexcept(false) try {} catch(...){throw;}
};
export void ordinary_throw(){throw 7u;}
export struct QuietDrop {
  unsigned& count;
  SAFETY_STORES_BORROW(c) explicit QuietDrop(unsigned& c) noexcept :count(c){}
  ~QuietDrop() noexcept{++count;}
};
export struct DefaultFailure {DefaultFailure(){throw 9u;}};
export struct DefaultArray {DefaultFailure fields[2]{};};
export void consume_default(DefaultFailure value=DefaultFailure{}) noexcept {}
export struct Poly {virtual ~Poly(){}};
export struct Child:Poly {unsigned value=4u;};
export unsigned dynamic_probe(const Poly& source){
  try{const auto& child=dynamic_cast<const Child&>(source);return child.value;}
  catch(...){return 3u;}
}
export unsigned typeid_probe(Poly* source){
  try{unsafe{typeid(*source);}return 1u;}
  catch(...){return 2u;}
}
''')
        compile(checked+['--precompile', str(api), '-o', str(tmp/'drops.pcm')])
        source = tmp/'exception_checks.cppm'
        prefix = 'export module exception_checks; import drops;\n'
        source.write_text(prefix+'''
unsigned return_cleanup(unsigned& count){
  try{Drop drop(count);return 42u;}catch(unsigned n){return n;}
}
export unsigned run(){
  unsigned count=0u;
  try{Drop drop(count);}catch(unsigned n){if(n!=7u)return 1u;}
  if(count!=1u)return 2u;
  try{Drop{count};}catch(unsigned n){if(n!=7u)return 3u;}
  if(count!=2u)return 4u;
  if(return_cleanup(count)!=7u)return 5u;
  if(count!=3u)return 6u;
  try{Member member(count);}catch(unsigned n){if(n!=7u)return 7u;}
  if(count!=4u)return 8u;
  try{Base base(count);}catch(unsigned n){if(n!=7u)return 9u;}
  if(count!=5u)return 10u;
  try{
    try{Drop drop(count);}catch(unsigned n){if(n!=7u)return 11u;throw;}
  }catch(unsigned n){if(n!=7u)return 12u;}
  if(count!=6u)return 13u;
  unsigned ready=1u;
  try{Drop drop(count);ready=2u;}catch(...){if(ready!=2u)return 14u;}
  if(count!=7u)return 15u;
  try{QuietDrop drop(count);ordinary_throw();}catch(unsigned n){if(n!=7u)return 16u;}
  if(count!=8u)return 17u;
  try{DefaultArray array{};return 18u;}catch(unsigned n){if(n!=9u)return 19u;}
  try{consume_default();return 20u;}catch(unsigned n){if(n!=9u)return 21u;}
  ++count;
  if(count!=9u)return 22u;
  Poly base;Child child;
  if(dynamic_probe(base)!=3u || dynamic_probe(child)!=4u)return 23u;
  if(typeid_probe(nullptr)!=2u)return 24u;
  return 0u;
}
''')
        compile(checked+['--precompile', str(source), '-o', str(tmp/'exception_checks.pcm')])
        objects = []
        for name in ('drops', 'exception_checks'):
            obj = tmp/(name+'.o')
            compile([clang]+flags+['-c', str(tmp/(name+'.pcm')), '-o', str(obj)])
            objects.append(str(obj))
        main = tmp/'main.cpp'
        main.write_text('import exception_checks;int main(){return int(run());}')
        binary = tmp/'run'
        compile([clang]+flags+[str(main)]+objects+['-o', str(binary)])
        subprocess.run([str(binary)], check=True, timeout=30)

        for name, body in [
            ('drop_skips_assignment', 'unsigned f(unsigned& c){unsigned n;try{{Drop d(c);}n=1u;}catch(...){return n;}return n;}'),
            ('temporary_drop_skips_assignment', 'unsigned f(unsigned& c){unsigned n;try{Drop{c};n=1u;}catch(...){return n;}return n;}'),
            ('member_drop_skips_assignment', 'unsigned f(unsigned& c){unsigned n;try{{Member d(c);}n=1u;}catch(...){return n;}return n;}'),
            ('base_drop_skips_assignment', 'unsigned f(unsigned& c){unsigned n;try{{Base d(c);}n=1u;}catch(...){return n;}return n;}'),
            ('default_array_skips_assignment', 'unsigned f(){unsigned n;try{DefaultArray array{};n=1u;}catch(...){return n;}return n;}'),
            ('default_argument_skips_assignment', 'unsigned f(){unsigned n;try{consume_default();n=1u;}catch(...){return n;}return n;}'),
        ]:
            source.write_text(prefix+body)
            compile(checked+['-fsyntax-only', str(source)], False,
                    'not initialized on every control-flow path')

print('Exceptional automatic/temporary/return/member/base destruction, default initialization and nested cleanup; 12 refusals at O0/O2 under ASan/UBSan passed')
