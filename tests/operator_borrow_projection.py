#!/usr/bin/env python3
"""Circle operator* projects returned borrows; named calls preserve handles."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'llvm-build/bin/clang'
body = '''
template<class T> struct Owner {
 T value;
 Owner(T v) safe : value(rel v) {}
 const T^ operator*(const self^) noexcept safe { return ^const self->value; }
};
struct ArrowNode {unsigned value;};
struct ArrowOwner {
 ArrowNode value;
 const ArrowNode^ operator->(const self^) safe {return ^const self->value;}
};
template<class T> struct ArrowWrapper {
 ArrowOwner owner;
 unsigned read(const self^) safe {return self->owner->value;}
};
unsigned arrow_rebuild() safe {ArrowWrapper<unsigned> w{{{41u}}};return w.read();}
unsigned load(const unsigned^ x) safe { return *x; }
unsigned run() safe {
 if (arrow_rebuild()!=41u) return 0u;
 Owner<unsigned> owner(17u);
 static_assert(__is_same(decltype(*owner),const unsigned&));
 static_assert(__is_same(decltype(owner.operator*()),const unsigned^));
 if (*owner != 17u || load(owner.operator*()) != 17u) return 0u;
 if (*Owner<unsigned>(31u) != 31u) return 0u;
 Owner<Owner<unsigned>> nested(Owner<unsigned>(23u));
 if (**nested != 23u) return 0u;
 unsigned result = **nested;
 return result;
}
'''
with tempfile.TemporaryDirectory(prefix='circle-operator-projection-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'projection':'safe'}}))
    flags = ['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values',
             '-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    def check(args, ok=True, expected=None):
        r = subprocess.run([str(clang)]+args,capture_output=True,text=True)
        assert (r.returncode==0)==ok,r.stderr
        assert 'PLEASE submit' not in r.stderr,r.stderr
        if expected:
            assert expected in r.stderr,r.stderr
        return r
    for opt in ('-O0','-O2'):
        for sanitizer in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
            options=flags+[opt]+sanitizer
            source=tmp/'main.cpp';binary=tmp/'program'
            source.write_text(body+'int main() { return run()==23u ? 0 : 1; }')
            check(options+[str(source),'-o',str(binary)])
            r=subprocess.run([str(binary)],capture_output=True,text=True)
            assert r.returncode==0,r.stderr
            module=tmp/'projection.cppm';pcm=tmp/'projection.pcm';obj=tmp/'projection.o'
            module.write_text('export module projection; export {\n'+body+'\n}')
            check(options+['--precompile',str(module),'-o',str(pcm)])
            check(options+['-c',str(pcm),'-o',str(obj)])
            source.write_text('import projection; int main() { Owner<unsigned> x(7u); return *x==7u && run()==23u ? 0 : 1; }')
            check(options+['-fmodule-file=projection='+str(pcm),str(source),str(obj),'-o',str(binary)])
            r=subprocess.run([str(binary)],capture_output=True,text=True)
            assert r.returncode==0,r.stderr
            for text,expected in (
                ('unsigned bad() safe { Owner<unsigned> x(1u); unsigned y=x.operator*(); return y; }','cannot initialize'),
                ('void bad() safe { Owner<unsigned> x(1u); *x=2u; }','read-only'),
                ('const unsigned^ bad(const unsigned^ input) safe { Owner<unsigned> x(1u); return ^const *x; }','lifetime'),
                ('const unsigned^ bad(const unsigned^ input) safe { return ^const *Owner<unsigned>(1u); }','lifetime provenance'),
                ('unsigned bad() safe { Owner<unsigned> x(1u); auto r=x.operator*(); x.value=2u; return *r; }','mutation conflicts'),
            ):
                source.write_text('import projection;\n'+text)
                check(options+['-fmodule-file=projection='+str(pcm),'-fsyntax-only',str(source)],False,expected)
print('Operator* borrow result projection: nested/template/PCM O0/O2 ASan/UBSan; named handle calls, constness, lifetime and alias refusals preserved')
