#!/usr/bin/env python3
"""Native impl overload resolution uses validated contracts and borrow receivers."""
import json
import pathlib
import subprocess
import tempfile

root=pathlib.Path(__file__).resolve().parent.parent
clang=root/'llvm-build/bin/clang'
declarations='''interface Ops {
 unsigned pick(const self^,unsigned x) safe;
 unsigned pick(const self^,bool x) safe;
 unsigned access(const self^) safe;
 unsigned access(self^) safe;
};
template<class T> struct G {unsigned value;};
template<class T> impl G<T>:Ops {
 unsigned pick(const self^,unsigned x) safe override {return self->value+x;}
 unsigned pick(const self^,bool x) safe override {return self->value+(x?11u:13u);}
 unsigned access(const self^) safe override {return self->value;}
 unsigned access(self^) safe override {self->value+=1u;return self->value;}
};
'''
main='''int main() {
 G<unsigned> value{7u}; const G<unsigned> constant{23u};
 auto a=value.Ops::pick(2u); auto b=value.Ops::pick(true);
 const G<unsigned>^ loan=^const value;
 auto shared=loan.Ops::access();
 auto changed=mut value.Ops::access();
 auto readonly=constant.Ops::access();
 return a==9u && b==18u && shared==7u && changed==8u && readonly==23u ? 0:1;
}
'''
with tempfile.TemporaryDirectory(prefix='circle-impl-overload-') as name:
    d=pathlib.Path(name);policy=d/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'impl_overloads':'safe'}}))
    base=[str(clang),'--driver-mode=g++','-std=c++20','-fmodule-safe',
          '-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),
          '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    def run(command):
        result=subprocess.run(command,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr
        return result
    for opt in ('-O0','-O2'):
        for sanitizer in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
            flags=base+[opt,*sanitizer]
            source=d/'main.cpp';binary=d/'run'
            source.write_text(declarations+main)
            run(flags+[str(source),'-o',str(binary)])
            run([str(binary)])
            module=d/'impl_overloads.cppm';pcm=d/'impl_overloads.pcm';obj=d/'impl_overloads.o'
            module.write_text('export module impl_overloads;\nexport '+declarations.replace(
                              'template<class T> struct G','export template<class T> struct G'))
            run(flags+['--precompile',str(module),'-o',str(pcm)])
            run(flags+['-c',str(pcm),'-o',str(obj)])
            source.write_text('import impl_overloads;\n'+main)
            run(flags+['-fprebuilt-module-path='+str(d),str(source),str(obj),'-o',str(binary)])
            run([str(binary)])
    for body,diagnostic in [
        ('unsigned f(unsigned char x) {G<unsigned> v{1u}; return v.Ops::pick(x);}', 'ambiguous'),
        ('unsigned f() {G<unsigned> v{1u}; return v.Ops::pick();}', 'no matching member function'),
        ('unsigned f() {G<unsigned> v{1u}; const G<unsigned>^ loan=^const v; auto n=mut v.Ops::access(); return n+loan->value;}', 'mutation conflicts with a live borrow'),
    ]:
        source.write_text(declarations+body)
        result=subprocess.run(base+['-fsyntax-only',str(source)],capture_output=True,text=True)
        assert result.returncode and diagnostic in result.stderr,result.stderr
        assert 'PLEASE submit' not in result.stderr,result.stderr
print('Native impl argument and shared/mutable receiver overloads execute in same TU/PCM at O0/O2 with ASan/UBSan; ambiguous arguments, missing arguments and live shared-loan mutation refused; method templates remain open')
