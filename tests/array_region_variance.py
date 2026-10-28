#!/usr/bin/env python3
"""Array-element variance and bounded queries over repeated record type DAGs."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values', '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
API = '''
struct View/(a) {const unsigned^/a value;};
struct Slots/(a) {const unsigned^/a values[2];};
struct Writable/(a,b) {View/a^/b values[2];};
struct Readonly/(a,b) {const View/a^/b values[2];};
struct Pair/(a,b) {View/b second;View/a first;};
struct MixedRegions/(a,b) {const unsigned^/a shared[2];View/b* writer;};
struct ArrayCell/(a) {
 using Row=View/a[2];View/a value;Row* get(const self^) safe;
};
struct ReadArrayCell/(a) {
 using Row=View/a[2];View/a value;const Row* get(const self^) safe;
};
template<class T+> struct Grid {T values[2][2];};
template<class T+> struct AuditedGrid {T unsafe values[2];};
template<class From,class To> To* adapt(From* f) safe {return f;}
unsigned sum/(a,c)(const Slots/a^/c slots,const unsigned^/a unused) safe {
 return *slots->values[0]+*slots->values[1];
}
'''

# Each pair separates the carrier's data region from its storage duration.
# Only the region being tested changes its relationship to the last argument.
SHAPES = [
    ('Slots', 'Slots/a', 'Slots/b', True),
    ('ScalarGrid', 'Grid<const unsigned^>/a', 'Grid<const unsigned^>/b', True),
    ('RecordGrid', 'Grid<View>/a', 'Grid<View>/b', True),
    ('AuditedGrid', 'AuditedGrid<View>/a', 'AuditedGrid<View>/b', False),
    ('Writable', 'Writable/a/s', 'Writable/b/s', False),
    ('Readonly', 'Readonly/a/s', 'Readonly/b/s', True),
    ('MappedGrid', 'Grid<Pair>/s/a', 'Grid<Pair>/s/b', True),
    ('ArrayCell', 'ArrayCell/a', 'ArrayCell/b', False),
    ('ReadArrayCell', 'ReadArrayCell/a', 'ReadArrayCell/b', True),
    ('NestedArrayCell', 'Grid<ArrayCell>/a', 'Grid<ArrayCell>/b', False),
    ('MixedShared', 'MixedRegions/a/s', 'MixedRegions/b/s', True),
    ('MixedWritable', 'MixedRegions/s/a', 'MixedRegions/s/b', False),
]
for name, tied, free, _ in SHAPES:
    API += f'using {name}Tied=void /(a,s,c)(const {tied}^/c,const unsigned^/a) safe;\n'
    API += f'using {name}Free=void /(a,b,s,c)(const {free}^/c,const unsigned^/a) safe;\n'
API += '''
using SumFree=unsigned /(a,b,c)(const Slots/b^/c,const unsigned^/a) safe;
using MutableCarrier=void /(a,b,c)(Slots/b^/c,const unsigned^/a) safe;
using MutableCarrierTied=void /(a,c)(Slots/a^/c,const unsigned^/a) safe;
'''
PROGRAM = '''
int main() safe {
 unsigned x=3u,y=5u,independent=7u;
 Slots slots{{^const x,^const y}};
 SumFree* f=&sum;
 if(f(^const slots,^const independent)!=8u)return 1;
 auto generic=adapt<decltype(sum),SumFree>(&sum);
 return generic(^const slots,^const independent)==8u ? 0 : 2;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='array-region-variance-') as directory:
        d = pathlib.Path(directory)
        source, module, pcm, obj, binary = (d/n for n in
                                           ('client.cpp', 'api.cppm', 'api.pcm', 'api.o', 'run'))
        module.write_text('export module array_variance;export {\n'+API+'}\n')

        def compile(options, okay=True, timeout=120):
            r = subprocess.run([str(CLANG)]+FLAGS+options, capture_output=True,
                               text=True, timeout=timeout)
            context = source.read_text() if source.exists() else ''
            assert (r.returncode == 0) == okay, r.stderr+'\n'+context
            assert r.returncode >= 0 and 'PLEASE submit' not in r.stderr, r.stderr
            if not okay:
                assert 'error:' in r.stderr, r.stderr
            return r

        compile(['--precompile', str(module), '-o', str(pcm)])
        imports = ['-fmodule-file=array_variance='+str(pcm)]
        count = 0
        pairs = []
        for name, _, _, covariant in SHAPES:
            pairs += [(name+'Tied', name+'Free', covariant),
                      (name+'Free', name+'Tied', True)]
        pairs += [('MutableCarrierTied', 'MutableCarrier', False)]
        for src, dst, okay in pairs:
            for body in (f'void check({src}* f) unsafe {{{dst}* g=f;}}',
                         f'void check({src}* f) unsafe {{auto g=reinterpret_cast<{dst}*>(f);}}',
                         f'void check({src}* f) unsafe {{auto g=adapt<{src},{dst}>(f);}}'):
                for imported in (False, True):
                    source.write_text(('import array_variance;\n' if imported else API)+body)
                    compile((imports if imported else [])+['-fsyntax-only', str(source)], okay)
                    count += 1

        # Subtyping values cannot grant write access to their pointer slots.
        for imported in (False, True):
            prefix = 'import array_variance;\n' if imported else API
            for body in (
                    'void bad(SlotsTied** f) unsafe {auto g=reinterpret_cast<SlotsFree**>(f);}',
                    'unsigned bad() safe {unsigned x=1u,y=2u;const unsigned^ saved;'
                    '{unsigned local=3u;Slots slots{{^const x,^const local}};'
                    'saved=slots.values[1];}return *saved;}'):
                source.write_text(prefix+body)
                compile((imports if imported else [])+['-fsyntax-only', str(source)], False)

        for optimization in ('-O0', '-O2'):
            for sanitize in ([], ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']):
                options = [optimization]+sanitize
                compile(options+['--precompile', str(module), '-o', str(pcm)])
                compile(options+['-c', str(pcm), '-o', str(obj)])
                for imported in (False, True):
                    source.write_text(('import array_variance;\n' if imported else API)+PROGRAM)
                    compile(options+(imports if imported else [])+[str(source)]+
                            ([str(obj)] if imported else [])+['-o', str(binary)])
                    r = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                    assert r.returncode == 0, r.stderr

        # A record type DAG has two fields per level, but only 25 definitions.
        # Revisiting every path previously expanded this into 2**24 queries.
        dag = 'struct L0/(a){const unsigned^/a value;};\n'
        for level in range(1, 25):
            dag += f'struct L{level}/(a){{L{level-1}/a left;L{level-1}/a right;}};\n'
        dag += ('using Tied=void /(a,c)(const L24/a^/c,const unsigned^/a) safe;\n'
                'using Free=void /(a,b,c)(const L24/b^/c,const unsigned^/a) safe;\n')
        module.write_text('export module array_variance;export {\n'+dag+'}\n')
        compile(['--precompile', str(module), '-o', str(pcm)], timeout=30)
        for imported in (False, True):
            source.write_text(('import array_variance;\n' if imported else dag)+
                              'void check(Tied* f) unsafe {Free* g=f;}\n')
            compile((imports if imported else [])+['-fsyntax-only', str(source)], timeout=30)
    print(f'Array region variance: {count} local/PCM implicit/cast/template checks; '
          'mutable storage and escaping-borrow refusals; 8 O0/O2 plain ASan/UBSan '
          'runs; bounded 24-level repeated record DAG passed')


if __name__ == '__main__':
    main()
