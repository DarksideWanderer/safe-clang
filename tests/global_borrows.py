#!/usr/bin/env python3
"""Mutable TLS loans must survive direct, transitive and opaque calls safely."""
import pathlib
import subprocess
import sys
import tempfile

clang, plugin, root = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='global-borrows-') as directory:
    tmp = pathlib.Path(directory)
    def compile(args, ok=True, needle=''):
        result = subprocess.run(args, text=True, capture_output=True)
        if (result.returncode == 0) != ok or needle not in result.stderr:
            source = ''.join(pathlib.Path(a).read_text() for a in args
                             if isinstance(a, str) and a.endswith('.cppm'))
            raise AssertionError(result.stderr+'\n'+source)
        assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr

    for optimization in ('-O0', '-O2'):
        flags = ['-std=c++20', optimization, '-fsanitize=address,undefined',
                 '-fno-sanitize-recover=all', '-fprebuilt-module-path='+str(tmp),
                 '-I'+root+'/include']
        checked = [clang]+flags+['-Xclang', '-load', '-Xclang', plugin,
                    '-Xclang', '-add-plugin', '-Xclang', 'module-safety',
                    '-Xclang', '-plugin-arg-module-safety', '-Xclang', 'safe']
        provider = tmp/'global_owner.cppm'
        provider.write_text('''module;
#include "module_safety.h"
export module global_owner;
export unsigned change();
export struct Handle {
  unsigned* value=nullptr;
  SAFETY_RETURNS_THIS const unsigned& get()const{unsafe{return *value;}for(;;){}}
  void reset(unsigned n){unsafe{delete value;value=new unsigned(n);}}
  void clear(){unsafe{delete value;value=nullptr;}}
  unsigned bad_global()const{const unsigned&r=get();change();return r;}
  unsigned bad_global_mut(){const unsigned&r=get();change();return r;}
};
export inline thread_local Handle owner;
export unsigned change(){owner.reset(17u);return 0u;}
export void nested(){change();}
export unsigned read(){return owner.get();}
export unsigned pure();
export unsigned pure(){unsigned value=3u;++value;return value-1u;}
export unsigned use(const unsigned& x,unsigned){return x;}
export unsigned bad_take(const unsigned& value){change();return value;}
export unsigned bad_nested_take(const unsigned& value){nested();return value;}
export unsigned opaque_take(const unsigned& value);
export struct ReadAfterChange {
  unsigned value;
  explicit ReadAfterChange(const unsigned& r):value(0u){change();value=r;}
};
export struct View {
  const unsigned& value;
  unsigned bad_read()const{change();return value;}
};
export unsigned bad_view(View value){change();return value.value;}
export void opaque();
''')
        compile(checked+['--precompile', str(provider), '-o', str(tmp/'global_owner.pcm')])
        client = tmp/'global_client.cppm'
        prefix = 'export module global_client;import global_owner;\n'
        cases = [
            # Confirmed ASan heap-use-after-free: no VarDecl loan exists at call entry.
            ('unsigned f(){owner.reset(42u);return bad_take(owner.get());}', 'callee may invalidate'),
            ('unsigned f(){owner.reset(42u);return bad_nested_take(owner.get());}', 'callee may invalidate'),
            ('unsigned f(){owner.reset(42u);return opaque_take(owner.get());}', 'callee may invalidate'),
            ('unsigned f(){owner.reset(42u);auto p=&bad_take;return p(owner.get());}', 'error:'),
            ('unsigned f(){owner.reset(42u);ReadAfterChange result(owner.get());return result.value;}', 'callee may invalidate'),
            ('unsigned f(){owner.reset(42u);return bad_view(View{owner.get()});}', 'callee may invalidate'),
            ('unsigned f(){owner.reset(42u);return View{owner.get()}.bad_read();}', 'callee may invalidate'),
            ('unsigned f(){owner.reset(42u);return owner.bad_global();}', 'callee may invalidate'),
            ('unsigned f(){owner.reset(42u);return owner.bad_global_mut();}', 'callee may invalidate'),
            ('unsigned f(){owner.reset(42u);const unsigned& r=owner.get();owner.reset(17u);return r;}', 'borrow'),
            # Confirmed ASan heap-use-after-free before the effect check.
            ('unsigned f(){owner.reset(42u);const unsigned& r=owner.get();change();return r;}', 'call may invalidate'),
            ('unsigned f(){owner.reset(42u);const unsigned& r=owner.get();nested();return r;}', 'call may invalidate'),
            ('unsigned f(){owner.reset(42u);const unsigned& r=owner.get();opaque();return r;}', 'call may invalidate'),
            ('unsigned f(){owner.reset(42u);return use(owner.get(),change());}', 'temporary borrow'),
            ('unsigned f(){owner.reset(42u);return owner.get()+change();}', 'operand evaluation'),
            ('unsigned f(){owner.reset(42u);return change()+owner.get();}', 'operand evaluation'),
            ('struct Change{Change(){change();}};unsigned f(){owner.reset(42u);const unsigned& r=owner.get();Change x;return r;}', 'call may invalidate'),
            ('struct Change{unsigned value;Change():value(change()){}};unsigned f(){owner.reset(42u);const unsigned& r=owner.get();Change x;return r;}', 'call may invalidate'),
            ('unsigned helper(unsigned value=change()){return value;}void hidden(){helper();}unsigned f(){owner.reset(42u);const unsigned& r=owner.get();hidden();return r;}', 'call may invalidate'),
            ('struct Change{~Change(){change();}};unsigned f(){owner.reset(42u);const unsigned& r=owner.get();{Change x;}return r;}', 'call may invalidate'),
            ('struct Change{~Change(){change();}};void hidden(){Change x;}unsigned f(){owner.reset(42u);const unsigned& r=owner.get();hidden();return r;}', 'call may invalidate'),
            ('struct Change{~Change(){change();}};struct Wrapper{Change field;};unsigned f(){owner.reset(42u);const unsigned& r=owner.get();{Wrapper x;}return r;}', 'call may invalidate'),
            ('struct Change{~Change(){change();}};unsigned f(){owner.reset(42u);const unsigned& r=owner.get();try{Change x;throw 1u;}catch(...){return r;}return 0u;}', 'call may invalidate'),
        ]
        for body, needle in cases:
            client.write_text(prefix+body)
            compile(checked+['-fsyntax-only', str(client)], False, needle)
        client.write_text(prefix+'''export unsigned run(){
  owner.reset(42u);
  if(use(owner.get(),pure())!=42u)return 3u;
  unsigned copy;
  {const unsigned& r=owner.get();if(read()!=42u || pure()!=3u || r!=42u)return 1u;copy=r;}
  change();if(copy!=42u || owner.get()!=17u)return 2u;
  owner.clear();return 0u;
}''')
        compile(checked+['--precompile', str(client), '-o', str(tmp/'global_client.pcm')])
        objects = []
        for name in ('global_owner', 'global_client'):
            obj = tmp/(name+'.o')
            compile([clang]+flags+['-c', str(tmp/(name+'.pcm')), '-o', str(obj)])
            objects.append(str(obj))
        main = tmp/'main.cpp'
        main.write_text('import global_client;int main(){return int(run());}')
        binary = tmp/'run'
        compile([clang]+flags+[str(main)]+objects+['-o', str(binary)])
        subprocess.run([str(binary)], check=True, timeout=30)
print('Cross-PCM mutable TLS borrows, read-only/pure calls, normal/EH drops and 23 refusals at O0/O2 under ASan/UBSan passed')
