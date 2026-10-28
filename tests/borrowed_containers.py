#!/usr/bin/env python3
"""Heap-stored readonly borrow regions, growth, and alias refusal cases."""
import pathlib
import subprocess
import sys
import tempfile
clang,plugin,root=sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safecpp-borrowed-heap-') as directory:
    tmp=pathlib.Path(directory)
    flags=['-std=c++20','-fsanitize=address,undefined','-fno-sanitize-recover=all','-g','-fprebuilt-module-path='+str(tmp)]
    checked=[clang]+flags+['-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe']
    def compile(command,ok=True):
        r=subprocess.run(command,text=True,capture_output=True)
        if (r.returncode==0)!=ok: raise AssertionError(r.stderr+'\n'+(source.read_text() if 'source' in locals() or 'source' in globals() else str(command)))
        if not ok and ('PLEASE submit' in r.stderr or 'frontend command failed' in r.stderr): raise AssertionError(r.stderr)
    for name,file in [('safety','safety.cppm'),('safety_borrows','borrows.cppm')]:
        compile(checked+['--precompile',root+'/runtime/'+file,'-o',str(tmp/(name+'.pcm'))])
    source=tmp/'checks.cppm'
    prefix='export module checks; import safety; import safety_borrows; struct Owner { unsigned x=1u,y=2u; }; struct View { const unsigned& ref; }; '
    source.write_text(prefix+'''export unsigned run() {
      Owner owner;
      std2::borrowed_vector<View,Owner> values(owner);
      for(unsigned i=0u;i<64u;++i) { View v{owner.x}; values.push_back(v); }
      if(values.size()!=64u) return 1u;
      { auto v=values.get(0u); if(v.ref!=1u) return 2u; }
      View second{owner.y}; values.push_back(second);
      { auto v=values.get(64u); if(v.ref!=2u) return 3u; }
      std2::borrowed_vector<View,Owner> moved(std2::move(values));
      if(moved.size()!=65u) return 4u;
      { auto v=moved.get(64u); if(v.ref!=2u) return 5u; }
      return 0u;
    }''')
    compile(checked+['--precompile',str(source),'-o',str(tmp/'checks.pcm')])
    for name in ('safety','safety_borrows','checks'):
        compile([clang]+flags+['-c',str(tmp/(name+'.pcm')),'-o',str(tmp/(name+'.o'))])
    main=tmp/'main.cpp';main.write_text('import checks; int main() { return run(); }')
    binary=tmp/'borrowed_heap'
    compile([clang]+flags+[str(main)]+[str(tmp/(name+'.o')) for name in ('safety','safety_borrows','checks')]+['-o',str(binary)])
    subprocess.run([str(binary)],check=True)
    for body in [
      'unsigned f() { Owner owner; unsigned foreign=3u; std2::borrowed_vector<View,Owner> v(owner); View value{foreign}; v.push_back(value); return v.size(); }',
      'unsigned f() { Owner owner; std2::borrowed_vector<View,Owner> v(owner); View value{owner.x}; v.push_back(value); owner.x=2u; return v.size(); }',
      'unsigned f() { Owner owner; std2::borrowed_vector<View,Owner> v(owner); View value{owner.x}; v.push_back(value); auto got=v.get(0u); v.reserve(100u); return got.ref; }',
      'unsigned f() { std2::borrowed_vector<View,Owner> v(Owner{}); return v.size(); }',
      'unsigned f() { Owner owner; std2::borrowed_vector<unsigned,Owner> v(owner); return v.size(); }',
      'struct Throwing { const unsigned& ref; ~Throwing() noexcept(false) { throw 1u; } }; unsigned f() { Owner owner; std2::borrowed_vector<Throwing,Owner> v(owner); return v.size(); }',
    ]:
        source.write_text(prefix+body)
        compile(checked+['-fsyntax-only',str(source)],False)
print('Borrowed heap region growth/read/destruction under ASan/UBSan and 6 refusal cases passed')
