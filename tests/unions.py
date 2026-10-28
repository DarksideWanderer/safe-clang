#!/usr/bin/env python3
"""Union active-member dataflow, aliasing and branch joins at O0/O2."""
import pathlib, subprocess, sys, tempfile
clang,plugin,root=sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safecpp-unions-') as directory:
    tmp=pathlib.Path(directory)
    for optimization in ('-O0','-O2'):
        flags=['-std=c++20',optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all','-fprebuilt-module-path='+str(tmp)]
        checked=[clang]+flags+['-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe']
        source=tmp/'union_checks.cppm'
        prefix='export module union_checks; union U {unsigned a; unsigned b; double c;};\n'
        def compile(args,ok=True,needle=''):
            result=subprocess.run(args,text=True,capture_output=True)
            assert (result.returncode==0)==ok and needle in result.stderr,result.stderr+'\n'+source.read_text()
            assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr,result.stderr
        source.write_text(prefix+'''export unsigned run(){
          U first{.a=1u}; if(first.a!=1u)return 1u;
          first.b=2u;if(first.b!=2u)return 2u;
          U copied=first;if(copied.b!=2u)return 3u;
          U assigned;assigned=copied;if(assigned.b!=2u)return 4u;
          {U&alias=assigned;alias.a=3u;}if(assigned.a!=3u)return 5u;
          unsigned n=0u;while(n<3u){assigned.a=n;++n;}if(assigned.a!=2u)return 6u;
          assigned.c=4.0;if(assigned.c!=4.0)return 7u;
          U zero{};if(zero.a!=0u)return 8u;
          return 0u;
        }
        unsigned branch(bool b){U value{.a=1u};if(b)value.b=2u;else value.b=3u;return value.b;}
        union Default {unsigned a=9u;unsigned b;};unsigned defaulted(){Default value;return value.a;}
        constexpr U global{.b=7u};unsigned static_value(){return global.b;}
        ''')
        compile(checked+['--precompile',str(source),'-o',str(tmp/'union_checks.pcm')])
        compile([clang]+flags+['-c',str(tmp/'union_checks.pcm'),'-o',str(tmp/'union_checks.o')])
        main=tmp/'main.cpp';main.write_text('import union_checks;int main(){return int(run());}')
        binary=tmp/'run';compile([clang]+flags+[str(main),str(tmp/'union_checks.o'),'-o',str(binary)])
        subprocess.run([str(binary)],check=True,timeout=30)
        for body,needle in [
          ('void raw(U*p){unsafe{p->b=2u;}}unsigned f(){U u{.a=1u};raw(&u);return u.a;}', 'not active'),
          ('unsigned f(){U u{.a=1u};return u.b;}', 'not active'),
          ('unsigned f(){U u;return u.a;}', 'not active'),
          ('unsigned f(bool flag){U u{.a=1u};if(flag)u.b=2u;return u.a;}', 'not active'),
          ('unsigned f(){U u{.a=1u};const unsigned&r=u.a;u.b=2u;return r;}', 'borrow'),
          ('unsigned f(){U u{.a=1u};U&r=u;r.b=2u;return u.a;}', 'not active'),
          ('void change(U&u){u.b=2u;}unsigned f(){U u{.a=1u};change(u);return u.a;}', 'not active'),
          ('struct Outer{U inner;};unsigned f(){Outer o{{.a=1u}};return o.inner.a;}', 'directly tracked'),
          ('union Nontrivial{unsigned a;struct Item{~Item(){}}item;};', 'union'),
          ('union Methods{unsigned a=1u;unsigned b;void change(){b=2u;}};unsigned f(){Methods u;u.change();return u.a;}', 'not active'),
          ('union Constructor{unsigned a=1u;unsigned b;Constructor(){b=2u;}};unsigned f(){Constructor u;return u.a;}', 'not active'),
        ]:
            source.write_text(prefix+body)
            compile(checked+['-fsyntax-only',str(source)],False,needle)
print('Scalar union activation/copy/aliases/loop/branch/default/global tests and 22 refusals passed at O0/O2 under ASan/UBSan')
