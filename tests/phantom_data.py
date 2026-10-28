#!/usr/bin/env python3
"""Non-storage phantom fields: O0 construction, copy, drop and PCM identity."""
import pathlib
import subprocess
import sys
import tempfile
import json

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
body = '''
struct NoObject {
 NoObject() = delete;
 NoObject(const NoObject&) = delete;
 ~NoObject() = delete;
};
struct alignas(64) Aligned { unsigned value; };
unsigned events = 0u;
struct Counted {
 Counted() safe { unsafe { events += 1u; } }
 ~Counted() safe { unsafe { events += 100u; } }
};
template<class T> struct Carrier {
 T __phantom_data;
 unsigned value;
 Carrier(unsigned n) safe : value(n) {}
 Carrier(const Carrier&) safe = default;
 Carrier& operator=(const Carrier&) safe = default;
};
static_assert(sizeof(Carrier<Aligned>) == sizeof(unsigned));
static_assert(alignof(Carrier<Aligned>) == alignof(unsigned));
unsigned run() safe {
 Carrier<unsigned> scalar(17u);
 if (scalar.value != 17u) return 0u;
 Carrier<NoObject> first(17u);
 Carrier<NoObject> second(first);
 second = first;
 {
  Carrier<Counted> tracked(1u);
 }
 try {
  Carrier<Counted> tracked(1u);
  throw 1u;
 } catch (unsigned) {}
 unsafe { if (events != 0u) return 0u; }
 return second.value;
}
'''
with tempfile.TemporaryDirectory(prefix='circle-phantom-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version':1, 'modules':{'phantom':'safe'}}))
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
             '-fcircle-borrow-values', '-fmodule-safety-policy='+str(policy),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22', '-O0']
    def check(args, success=True, diagnostic=None):
        r = subprocess.run([str(clang)]+args, capture_output=True, text=True)
        assert (r.returncode == 0) == success, r.stderr
        assert 'PLEASE submit' not in r.stderr, r.stderr
        if diagnostic:
            assert diagnostic in r.stderr, r.stderr
        return r
    for sanitizer in ([], ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']):
        source = tmp/'local.cpp'
        source.write_text(body+'int main() { return run()==17u ? 0 : 1; }')
        binary = tmp/'local'
        check(flags+sanitizer+[str(source), '-o', str(binary)])
        r = subprocess.run([str(binary)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        module = tmp/'phantom.cppm'
        module.write_text('export module phantom;\nexport {\n'+body+'}\n')
        pcm = tmp/'phantom.pcm'
        check(flags+sanitizer+['--precompile', str(module), '-o', str(pcm)])
        obj = tmp/'phantom.o'
        check(flags+sanitizer+['-c', str(pcm), '-o', str(obj)])
        source.write_text('import phantom;\nstatic_assert(sizeof(Carrier<Aligned>)==sizeof(unsigned));\nint main() { return run()==17u ? 0 : 1; }')
        check(flags+sanitizer+['-fmodule-file=phantom='+str(pcm), str(source), str(obj), '-o', str(binary)])
        r = subprocess.run([str(binary)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    for text, diagnostic in (
        ('struct S { unsigned __phantom_data; S() safe : __phantom_data(1u) {} };', 'cannot be explicitly initialized'),
        ('struct S { unsigned __phantom_data; S() safe {} }; unsigned f(S^ s) safe { return s->__phantom_data; }', 'no accessible storage'),
        ('struct S { unsigned __phantom_data = 1u; };', 'requires an uninitialized'),
        ('union S { unsigned __phantom_data; };', 'requires an uninitialized'),
        ('struct S { unsigned __phantom_data; unsigned value; }; S s{1u};', 'aggregate initialization with phantom data is not yet modeled'),
        ('template<class T> struct P { T __phantom_data; P() safe {} }; unsigned f() safe { P<const unsigned^> unbound; return 0u; }', 'borrow value fields require class lifetime parameters'),
    ):
        source.write_text(text)
        check(flags+['-fsyntax-only', str(source)], False, diagnostic)
    # Source annotations cannot forge compiler-owned storage exclusion.
    source.write_text('struct S { [[clang::annotate("safecpp.native.phantom")]] unsigned value; }; static_assert(sizeof(S)==sizeof(unsigned));')
    check(flags+['-fsyntax-only', str(source)], False,
          'compiler-owned safety metadata cannot be written in source')
    check(['--driver-mode=g++','-std=c++20','-fsyntax-only',str(source)])
    # With the dialect disabled, the reserved spelling is an ordinary field.
    source.write_text('struct alignas(64) Payload { unsigned value; }; struct S { Payload __phantom_data; unsigned value; }; static_assert(sizeof(S)==128); int main() { S s{}; s.__phantom_data.value=7u; return s.__phantom_data.value==7u ? 0 : 1; }')
    check(['--driver-mode=g++','-std=c++20',str(source),'-o',str(binary)])
    assert subprocess.run([str(binary)]).returncode == 0
print('Phantom data O0/PCM/ASan/UBSan: no storage or implicit object construction/drop; access/init rejected; legacy field preserved')
