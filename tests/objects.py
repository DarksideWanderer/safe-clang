#!/usr/bin/env python3
"""Object borrowing contracts across interface, implementation, and client PCM."""
import pathlib
import subprocess
import sys
import tempfile
clang, plugin, root = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safecpp-object-modules-') as directory:
    tmp=pathlib.Path(directory)
    flags=['-std=c++20','-fsanitize=address,undefined','-fno-sanitize-recover=all','-g','-fprebuilt-module-path='+str(tmp)]
    checked=[clang]+flags+['-I'+root+'/include','-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe']
    def compile(command, ok=True):
        result=subprocess.run(command,text=True,capture_output=True)
        if (result.returncode==0)!=ok: raise AssertionError(result.stderr)
        if not ok and ('PLEASE submit' in result.stderr or 'frontend command failed' in result.stderr): raise AssertionError(result.stderr)
    interface=tmp/'objects.cppm'
    interface.write_text('''module;
#include "module_safety.h"
export module objects;
export struct View {
  const unsigned& ref;
  SAFETY_STORES_BORROW(x) View(const unsigned& x);
};
export template<class T> struct GenericView { const T& ref; };
export template<class T> SAFETY_RETURNS_BORROW(x) GenericView<T> generic(const T& x) { return {x}; }
export SAFETY_RETURNS_BORROW(x) auto closure(const unsigned& x) { return [&x] { return x; }; }
''')
    compile(checked+['--precompile',str(interface),'-o',str(tmp/'objects.pcm')])
    implementation=tmp/'objects_impl.cpp'
    implementation.write_text('module objects; View::View(const unsigned& renamed):ref(renamed) {}')
    compile(checked+['-c',str(implementation),'-o',str(tmp/'implementation.o')])
    implementation.write_text('module objects; unsafe_fn View::View(const unsigned& renamed):ref(renamed) {}')
    compile(checked+['-fsyntax-only',str(implementation)],False)
    client=tmp/'client.cppm'
    client.write_text('''export module client; import objects;
export unsigned run() {
  unsigned x=42u;
  View v(x); auto g=generic(x); auto callback=closure(x);
  if(v.ref!=42u || g.ref!=42u || callback()!=42u) return 1u;
  return 0u;
}''')
    compile(checked+['--precompile',str(client),'-o',str(tmp/'client.pcm')])
    for name in ('objects','client'):
        compile([clang]+flags+['-c',str(tmp/(name+'.pcm')),'-o',str(tmp/(name+'.o'))])
    main=tmp/'main.cpp';main.write_text('import client; int main() { return run(); }')
    binary=tmp/'objects_test'
    compile([clang]+flags+[str(main),str(tmp/'objects.o'),str(tmp/'client.o'),str(tmp/'implementation.o'),'-o',str(binary)])
    subprocess.run([str(binary)],check=True)
    for body in (
        'unsigned f() { unsigned x=1u; View v(x); x=2u; return v.ref; }',
        'unsigned f() { unsigned x=1u; auto v=generic(x); x=2u; return v.ref; }',
        'unsigned f() { unsigned x=1u; auto callback=closure(x); x=2u; return callback(); }',
        'unsigned f() { View v(1u); return v.ref; }',
    ):
        client.write_text('export module client; import objects; '+body)
        compile(checked+['-fsyntax-only',str(client)],False)
print('Cross-module constructor, generic object and closure borrowing under ASan/UBSan; 4 refusal cases passed')
