#!/usr/bin/env python3
"""Deep initializer graphs stay bounded without skipping safety checks."""
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = sys.argv[2] if len(sys.argv) > 2 else None
CLANG = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    'MODULE_SAFETY_CLANG', str(ROOT/'llvm-build/bin/clang'))
NATIVE = PLUGIN is None
DEPTH = 40
UNSAFE = 'if ([[clang::annotate("safecpp.unsafe.scope")]] bool scope=true)'
RAW = '[[clang::annotate("safecpp.unsafe")]] unsigned raw(){return 9u;}\n'


def chain(prefix, depth, leaf):
    decl = f'using {prefix}0={leaf};\n'
    for i in range(1, depth+1):
        decl += f'using {prefix}{i}=Wrap<{prefix}{i-1}>;\n'
    return decl


def nested(prefix, depth, value):
    for i in range(1, depth+1):
        value = f'{prefix}{i}{{{value},0u}}'
    return value


def selected(value, depth):
    return value + '.value'*depth


WRAP = 'template<class T'+('+' if NATIVE else '')+'>struct Wrap{T value;unsigned tag;};\n'
API = WRAP + chain('S', DEPTH, 'unsigned') + RAW + '''
struct Good{unsigned operator()()const{return 7u;}};
struct Bad{[[clang::annotate("safecpp.unsafe")]] unsigned operator()()const{return 7u;}};
'''
API += f'template<class T>S{DEPTH} make_template(){{return {nested("S",DEPTH,"T{}()")};}}\n'
API += f'S{DEPTH} make(){{return {nested("S",DEPTH,"7u")};}}\n'
PROGRAM = ('int main(){auto first=make();auto second=make_template<Good>();'
           f'return {selected("first",DEPTH)}==7u && {selected("second",DEPTH)}==7u?0:1;}}\n')


def main():
    base = [CLANG, '--driver-mode=g++', '-std=c++20']
    if NATIVE:
        base += ['-fcircle-safety', '-fcircle-borrow-values',
                 '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    else:
        base += ['-Xclang','-load','-Xclang',PLUGIN,'-Xclang','-add-plugin',
                 '-Xclang','module-safety','-Xclang','-plugin-arg-module-safety',
                 '-Xclang','safe']
    count, runtimes, slowest = 0, 0, 0.0
    with tempfile.TemporaryDirectory(prefix='initializer-traversal-') as directory:
        d = pathlib.Path(directory)
        source, module, pcm, obj, exe = (d/name for name in
            ('client.cppm', 'api.cppm', 'api.pcm', 'api.o', 'run'))

        def compile(options, okay=True, needle=None, pcm_object=False):
            nonlocal count, slowest
            start = time.monotonic()
            command = ([CLANG,'--driver-mode=g++','-std=c++20']
                       if pcm_object and not NATIVE else base)
            r = subprocess.run(command+options,capture_output=True,text=True,timeout=30)
            slowest = max(slowest,time.monotonic()-start)
            assert (r.returncode==0)==okay, r.stderr+'\n'+source.read_text()
            assert 'PLEASE submit' not in r.stderr, r.stderr
            if not okay:
                assert 'module-safety:' in r.stderr, r.stderr
                if needle: assert needle in r.stderr, r.stderr
            count += 1

        module.write_text('export module init_graph;export {\n'+API+'}\n')
        compile(['--precompile',str(module),'-o',str(pcm)])
        imported = ['-fmodule-file=init_graph='+str(pcm)]

        def check(body, okay=True, needle=None):
            for use_pcm in (False,True):
                source.write_text('export module init_client;\n'+
                    ('import init_graph;\n' if use_pcm else API)+body)
                compile((imported if use_pcm else [])+['-fsyntax-only',str(source)],okay,needle)

        check(PROGRAM)
        check(f'void bad(){{auto v=make_template<Bad>();}}',False,'unsafe or unclassified')
        # The template body remains checked when instantiated by an unchecked call.
        check(f'void bad(){{{UNSAFE}{{auto v=make_template<Bad>();}}}}',False,'unsafe or unclassified')
        raw_tree=nested('S',DEPTH,'raw()')
        check(f'void bad(){{auto v={raw_tree};}}',False,'unsafe or unclassified')
        check(f'void audited(){{{UNSAFE}{{auto v={raw_tree};}}}}')
        check(f'void audited(){{{UNSAFE}{{auto v={raw_tree};}}}}\n'
              f'void checked(){{auto v={raw_tree};}}',False,'unsafe or unclassified')
        check(f'void checked(){{auto v={raw_tree};}}\n'
              f'void audited(){{{UNSAFE}{{auto v={raw_tree};}}}}',False,'unsafe or unclassified')
        # Semantic-only fillers and default initializers still execute.
        check('struct X{[[clang::annotate("safecpp.unsafe")]] X(){}};'
              'void bad(){X values[2]{};}',False,'unsafe or unclassified')
        throws='struct Throwing{Throwing(){throw 1u;}};'
        check(throws+'struct Defaults{Throwing values[2]{};};'
              'unsigned bad(){unsigned n;try{Defaults value{};n=1u;}'
              'catch(...){return n;}return n;}',False,'not initialized on every control-flow path')
        defaults=chain('E',25,'Throwing')
        check(throws+defaults+'void consume(E25 value=E25{})noexcept{}'
              'unsigned bad(){unsigned n;try{consume();n=1u;}'
              'catch(...){return n;}return n;}',False,'not initialized on every control-flow path')
        # Readonly sharing stays legal; mutable aliases and sibling effects fail.
        if NATIVE:
            leaf='const unsigned^'
            borrow='^const x'
            read=lambda place:'*'+place
            loans='struct Loans/(a){unsigned^/a first;const unsigned^/a second;};'
            aliases='Loans{^x,^const x}'
            sibling='struct LoanEffect/(a){const unsigned^/a loan;unsigned effect;};'
            change='unsigned change(unsigned^ target){*target=2u;return 0u;}'
            effect='LoanEffect{^const x,change(^x)}'
        else:
            leaf='Borrow'
            borrow='Borrow{x}'
            read=lambda place:place+'.value'
            loans='struct Loans{unsigned& first;const unsigned& second;};'
            aliases='Loans{x,x}'
            sibling='struct LoanEffect{const unsigned& loan;unsigned effect;};'
            change='unsigned change(unsigned& target){target=2u;return 0u;}'
            effect='LoanEffect{x,change(x)}'
        borrow_decl=('' if NATIVE else 'struct Borrow{const unsigned& value;};')
        for depth in (8,25,40):
            decl=borrow_decl+chain('B',depth,leaf)
            tree=nested('B',depth,borrow)
            check(decl+f'unsigned good(){{unsigned x=7u;auto value={tree};'
                  f'return {read(selected("value",depth))};}}')
            check(decl+f'B{depth} bad(){{unsigned x=7u;return {tree};}}',False)
        check(loans+chain('L',25,'Loans')+
              f'void bad(){{unsigned x=1u;auto value={nested("L",25,aliases)};}}',False,'exclusive borrow')
        check(sibling+change+chain('L',25,'LoanEffect')+
              f'void bad(){{unsigned x=1u;auto value={nested("L",25,effect)};}}',False,'argument evaluation invalidates')
        shared=('struct Shared/(a){const unsigned^/a first;const unsigned^/a second;};' if NATIVE else
                'struct Shared{const unsigned& first;const unsigned& second;};')
        init='Shared{^const x,^const x}' if NATIVE else 'Shared{x,x}'
        check(shared+chain('L',25,'Shared')+
              f'void good(){{unsigned x=1u;auto value={nested("L",25,init)};}}')
        runtime_borrows = (borrow_decl+chain('B',40,leaf)+
            f'unsigned read_deep(){{unsigned x=7u;auto value={nested("B",40,borrow)};'
            f'return {read(selected("value",40))};}}\n')
        runtime_program = runtime_borrows+PROGRAM.replace('?0:1;', ' && read_deep()==7u?0:1;')
        for use_pcm in (False,True):
            source.write_text('export module init_client;\n'+
                ('import init_graph;\n' if use_pcm else API)+runtime_program)
            for optimization in ('-O0','-O2'):
                for sanitized in (False,True):
                    flags=[optimization]+(['-fsanitize=address,undefined','-fno-sanitize-recover=all'] if sanitized else [])
                    if use_pcm:
                        compile(flags+['-c',str(pcm),'-o',str(obj)],pcm_object=True)
                    compile(flags+(imported+[str(obj)] if use_pcm else [])+[str(source),'-o',str(exe)])
                    r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
                    assert r.returncode==0,r.stderr
                    runtimes+=1
    print(f'Initializer traversal: {count} native' if NATIVE else f'Initializer traversal: {count} plugin',
          f'local/PCM compilations; 25/40-level values, escaping loans, exclusive aliases, sibling effects,',
          f'implicit fillers, EH and independent unsafe/template contexts; {runtimes} O0/O2 plain ASan/UBSan runs;',
          f'slowest compile {slowest:.2f}s passed')


if __name__ == '__main__':
    main()
