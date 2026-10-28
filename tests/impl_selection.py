#!/usr/bin/env python3
"""Native impl filtering, defaults, partial ordering and constraint subsumption."""
import json
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = root/'llvm-build/bin/clang'
declarations = '''interface Read {unsigned get(const self^) safe;};
template<class T> struct C {unsigned value;};
template<class T> requires (sizeof(T)==1) impl C<T>:Read {
 unsigned get(const self^) safe override {return 1u;}
};
template<class T> requires (sizeof(T)==4) impl C<T>:Read {
 unsigned get(const self^) safe override {return self->value;}
};
template<class T> struct D {unsigned value;};
template<class T, class U=T> impl D<T>:Read {
 static_assert(__is_same(T,U));
 unsigned get(const self^) safe override {return self->value;}
};
'''
ordering = [
'''template<class T> impl O<T>:Read {
 static_assert(!__is_same(T,unsigned*));
 unsigned get(const self^) safe override {return 1u;}
};
''',
'''namespace specialized {
template<class T> impl O<T*>:Read {
 unsigned get(const self^) safe override {return 2u;}
};
}
''',
'''impl O<unsigned*>:Read {
 unsigned get(const self^) safe override {return 3u;}
};
''',
]
declarations += 'template<class T> struct O {unsigned value;};\n' + ''.join(ordering)
declarations += '''template<class T> concept Word=(sizeof(T)==4);
template<class T> concept Trivial=__is_trivial(T);
template<class T> struct N {unsigned value;};
template<class T> requires Word<T> impl N<T>:Read {
 unsigned get(const self^) safe override {return 4u;}
};
template<class T> requires (Word<T> && Trivial<T>) impl N<T>:Read {
 unsigned get(const self^) safe override {return 5u;}
};
unsigned producer_result() {
 O<char*> partial{0u}; return partial.Read::get();
}
'''
main = '''int main() {
 C<char> small{3u}; C<unsigned> large{7u}; D<unsigned> defaults{11u};
 O<unsigned> general{0u}; O<char*> partial{0u}; O<unsigned*> explicit_impl{0u};
 N<unsigned> constrained{0u};
 return small.Read::get()==1u && large.Read::get()==7u &&
        defaults.Read::get()==11u && general.Read::get()==1u &&
        partial.Read::get()==2u && explicit_impl.Read::get()==3u &&
        constrained.Read::get()==5u && producer_result()==2u ? 0 : 1;
}
'''
with tempfile.TemporaryDirectory(prefix='circle-impl-selection-') as name:
    d=pathlib.Path(name)
    policy=d/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'impl_selection':'safe'}}))
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
            source.write_text(declarations.replace(''.join(ordering),
                              ''.join(reversed(ordering)))+main)
            run(flags+[str(source),'-o',str(binary)])
            run([str(binary)])
            module=d/'impl_selection.cppm';pcm=d/'impl_selection.pcm';obj=d/'impl_selection.o'
            module.write_text('export module impl_selection;\nexport '+
                              declarations.replace('template<class T> struct ',
                                                   'export template<class T> struct ').replace(
                                                   'unsigned producer_result()', 'export unsigned producer_result()'))
            run(flags+['--precompile',str(module),'-o',str(pcm)])
            run(flags+['-c',str(pcm),'-o',str(obj)])
            source.write_text('import impl_selection;\n'+main)
            run(flags+['-fprebuilt-module-path='+str(d),str(source),str(obj),'-o',str(binary)])
            run([str(binary)])
    source.write_text(declarations+
        'unsigned rejected() {C<unsigned __int128> value{1u}; return value.Read::get();}')
    result=subprocess.run(base+['-fsyntax-only',str(source)],capture_output=True,text=True)
    assert result.returncode and 'requires a modeled concrete impl method' in result.stderr,result.stderr
    assert 'PLEASE submit' not in result.stderr,result.stderr
    # These matches are incomparable: each fixes a different pointer position.
    source.write_text('''interface Read {unsigned get(const self^) safe;};
template<class A,class B> struct Pair {unsigned value;};
template<class A,class B> impl Pair<A,B*>:Read {
 unsigned get(const self^) safe override {return 1u;}
};
template<class A,class B> impl Pair<A*,B>:Read {
 unsigned get(const self^) safe override {return 2u;}
};
unsigned rejected() {Pair<unsigned*,char*> p{0u}; return p.Read::get();}
''')
    result=subprocess.run(base+['-fsyntax-only',str(source)],capture_output=True,text=True)
    assert result.returncode and 'selection is ambiguous' in result.stderr,result.stderr
    assert 'PLEASE submit' not in result.stderr,result.stderr
print('Native impl constraints/defaults, explicit-over-partial-over-generic ordering across namespaces and declaration permutations, constraint subsumption and losing-body non-instantiation pass in same TU/PCM O0/O2 with ASan/UBSan; no eligible impl rejected; full coherence remains open')
