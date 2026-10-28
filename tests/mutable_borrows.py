#!/usr/bin/env python3
"""Exclusive owner regions with mixed mutable/readonly borrowed elements."""
import pathlib, subprocess, sys, tempfile
clang,plugin,root=sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safecpp-mutable-') as directory:
    tmp=pathlib.Path(directory)
    flags=['-std=c++20','-O2','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fprebuilt-module-path='+str(tmp),'-I'+root+'/include']
    checked=[clang]+flags+['-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe']
    def compile(command,ok=True,needle=''):
        r=subprocess.run(command,text=True,capture_output=True)
        assert (r.returncode==0)==ok and needle in r.stderr,r.stderr
        assert 'PLEASE submit' not in r.stderr,r.stderr
    for name,file in [('safety','safety.cppm'),('safety_mutable_borrows','mutable_borrows.cppm')]:
        compile(checked+['--precompile',root+'/runtime/'+file,'-o',str(tmp/(name+'.pcm'))])
    prefix='''module;
#include "module_safety.h"
export module mutable_checks;
import safety; import safety_mutable_borrows;
struct Owner { unsigned x=1u,y=2u; };
struct View { unsigned& target; const unsigned& source; };
SAFETY_RETURNS_BORROW(owner) View make(Owner& owner){return View{owner.x,owner.y};}
'''
    source=tmp/'checks.cppm'
    source.write_text(prefix+'''export unsigned run(){
      Owner owner;
      {
        std2::mutable_borrowed_vector<View,Owner> values(owner);
        for(unsigned i=0u;i<64u;++i) values.emplace<make>();
        { auto& value=values.get(0u); value.target=value.source; }
        auto moved=std2::move(values);
        { auto& value=moved.get(63u); if(value.target!=2u) return 1u; }
      }
      if(owner.x!=2u) return 2u;
      return 0u;
    }''')
    compile(checked+['--precompile',str(source),'-o',str(tmp/'mutable_checks.pcm')])
    objects=[]
    for name in ['safety','safety_mutable_borrows','mutable_checks']:
        obj=tmp/(name+'.o');objects.append(str(obj))
        compile([clang]+flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)])
    main=tmp/'main.cpp';main.write_text('import mutable_checks; int main(){return int(run());}')
    binary=tmp/'checks';compile([clang]+flags+[str(main)]+objects+['-o',str(binary)])
    r=subprocess.run([str(binary)],capture_output=True,text=True);assert r.returncode==0,(r.returncode,r.stderr)
    bodies=[
      'void f(){Owner o;std2::mutable_borrowed_vector<View,Owner> v(o);v.emplace<make>();auto& x=v.get(0u);v.reserve(100u);x.target=1u;}',
      'void f(){Owner o;std2::mutable_borrowed_vector<View,Owner> v(o);v.emplace<make>();o.x=9u;v.size();}',
      'void f(){Owner o;std2::mutable_borrowed_vector<View,Owner> v(o);v.emplace<make>();auto& a=v.get(0u);auto& b=v.get(0u);a.target=b.source;}',
      'void f(){Owner o;std2::mutable_borrowed_vector<View,Owner> v(o);v.emplace<make>();auto copy=v.get(0u);}',
      'unsafe_fn View raw(Owner&o){return View{o.x,o.y};} void f(){Owner o;std2::mutable_borrowed_vector<View,Owner> v(o);v.emplace<raw>();}',
      'SAFETY_RETURNS_BORROW(owner) View bad(Owner&owner){unsigned local=1u;return View{local,owner.y};} void f(){Owner o;std2::mutable_borrowed_vector<View,Owner> v(o);v.emplace<bad>();}',
      'SAFETY_RETURNS_BORROW(owner) View alias(Owner&owner){return View{owner.x,owner.x};}',
      'struct Aliases { unsigned& a; unsigned& b; }; SAFETY_RETURNS_BORROW(owner) View alias(Aliases&owner){return View{owner.a,owner.b};}',
    ]
    for body in bodies:
        source.write_text(prefix+body)
        compile(checked+['-fsyntax-only',str(source)],False,'module-safety:')
print('Mixed exclusive/readonly heap borrows: factory provenance, growth, handle transfer and 8 refusals passed under ASan/UBSan')
