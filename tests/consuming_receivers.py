#!/usr/bin/env python3
"""Affine && receivers survive PCM import and generic instantiation."""
import pathlib
import subprocess
import sys
import tempfile

clang, plugin, root = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='consuming-receivers-') as directory:
    tmp = pathlib.Path(directory)

    def compile(args, ok=True, needle=''):
        result = subprocess.run(args, text=True, capture_output=True)
        assert (result.returncode == 0) == ok and needle in result.stderr, result.stderr
        assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr

    for optimization in ('-O0', '-O2'):
        flags = ['-std=c++20', optimization, '-fsanitize=address,undefined',
                 '-fno-sanitize-recover=all', '-I'+root+'/include',
                 '-fprebuilt-module-path='+str(tmp)]
        checked = [clang]+flags+['-Xclang', '-load', '-Xclang', plugin,
                    '-Xclang', '-add-plugin', '-Xclang', 'module-safety',
                    '-Xclang', '-plugin-arg-module-safety', '-Xclang', 'safe']
        provider = tmp/'affine.cppm'
        provider.write_text('''module;
#include "module_safety.h"
export module affine;
export struct Value {
  unsigned value=7u;
  unsigned take() && noexcept {return value;}
  unsigned operator()() && noexcept {return value;}
  unsigned fail() && {throw 1u;}
};
export template<class T> unsigned consume(T value){return static_cast<T&&>(value).take();}
export struct View {
  const unsigned& value;
  unsigned take() && noexcept {return value;}
};
export struct Reader {unsigned value=9u;unsigned get() const & {return value;}};
''')
        compile(checked+['--precompile', str(provider), '-o', str(tmp/'affine.pcm')])
        client = tmp/'affine_client.cppm'
        prefix = 'export module affine_client; import affine;\n'
        client.write_text(prefix+'''export struct Pair { Value x; unsigned other=7u; };
export unsigned run(){
  Value value;
  if(static_cast<Value&&>(value).take()!=7u)return 1u;
  value=Value{};
  if(static_cast<Value&&>(value)()!=7u)return 2u;
  if(consume(Value{})!=7u)return 3u;
  unsigned owner=11u;
  { View view{owner}; if(static_cast<View&&>(view).take()!=11u)return 4u; }
  owner=13u;
  if(owner!=13u)return 5u;
  Reader reader;
  if(reader.get()!=9u || reader.get()!=9u)return 6u;
  Pair pair;
  if(static_cast<Value&&>(pair.x).take()!=7u || pair.other!=7u)return 8u;
  Value throwing;
  try{static_cast<Value&&>(throwing).fail();}catch(...){return 0u;}
  return 7u;
}''')
        compile(checked+['--precompile', str(client), '-o', str(tmp/'affine_client.pcm')])
        objects = []
        for name in ('affine', 'affine_client'):
            obj = tmp/(name+'.o')
            compile([clang]+flags+['-c', str(tmp/(name+'.pcm')), '-o', str(obj)])
            objects.append(str(obj))
        main = tmp/'main.cpp'
        main.write_text('import affine_client; int main(){return int(run());}')
        binary = tmp/'run'
        compile([clang]+flags+[str(main)]+objects+['-o', str(binary)])
        subprocess.run([str(binary)], check=True, timeout=30)
        for body, needle in [
            ('unsigned f(){Value x;static_cast<Value&&>(x).take();return x.value;}', 'moved'),
            ('struct Pair{Value x;};unsigned f(){Pair pair;static_cast<Value&&>(pair.x).take();return pair.x.value;}', 'partially relocated'),
            ('unsigned f(Value& x){return static_cast<Value&&>(x).take();}', 'through a borrow'),
            ('unsigned f(){Value x;const Value& r=x;static_cast<Value&&>(x).take();return r.value;}', 'borrow'),
            ('unsigned f(){Value x;try{static_cast<Value&&>(x).fail();}catch(...){return x.value;}return 0u;}', 'moved'),
            ('template<class T>unsigned bad(T x){static_cast<T&&>(x).take();return x.value;}unsigned f(){return bad(Value{});}', 'moved'),
            ('unsigned f(){unsigned owner=1u;View view{owner};static_cast<View&&>(view).take();return view.value;}', 'moved'),
            ('void f(Value& x){Value target(static_cast<Value&&>(x));}', 'ownership through a borrow'),
            ('void f(Value&& x){Value target(static_cast<Value&&>(x));}', 'ownership through a borrow'),
            ('void f(){Value x;Value& r=x;Value target(static_cast<Value&&>(r));}', 'ownership through a borrow'),
            ('void f(Value& x){Value target;target=static_cast<Value&&>(x);}', 'ownership through a borrow'),
            ('void f(){Value x;auto fn=[&](){Value target(static_cast<Value&&>(x));};fn();}', 'ownership through a borrow'),
            ('struct Holder{Value value;__attribute__((annotate("safecpp.borrow.this"))) Value& get(){return value;}};void f(){Holder h;Value target(static_cast<Value&&>(h.get()));}', 'ownership through a borrow'),
            ('void f(Value& x,bool b){Value y;Value target(static_cast<Value&&>(b?x:y));}', 'ownership through a borrow'),
            ('void f(Value& x){Value target(static_cast<Value&&>((0u,x)));}', 'ownership through a borrow'),
            ('void f(Value(&x)[2]){Value target(static_cast<Value&&>(x[0u]));}', 'ownership through a borrow'),
        ]:
            client.write_text(prefix+body)
            compile(checked+['-fsyntax-only', str(client)], False, needle)
print('Cross-PCM consuming receivers, templates, holder ownership and 16 refusals at O0/O2 under ASan/UBSan passed')
