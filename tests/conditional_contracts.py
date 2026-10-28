#!/usr/bin/env python3
"""A thread contract written in the template's terms is read per instantiation."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'

DECLARATIONS = '''export module contracts;

struct Raw { unsigned* p; };
struct Plain { unsigned v; };

template <class T+>
struct [[unsafe::send(T~is_send), unsafe::sync(T~is_sync)]] Holder { T* p_; };

template <class T>
unsigned transfer(__attribute__((annotate("safecpp.send.static"))) T value) {
  return 0u;
}
'''

with tempfile.TemporaryDirectory(prefix='conditional-contracts-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'contracts': 'safe'}}))
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
             '-fcircle-borrow-values', '-fmodule-safety-policy='+str(policy)]
    source = tmp/'contracts.cppm'

    def compiles(body, ok):
        source.write_text(DECLARATIONS+body)
        result = subprocess.run([str(clang)]+flags+['-fsyntax-only', str(source)],
                                text=True, capture_output=True)
        if (result.returncode == 0) != ok:
            raise AssertionError(f'{body}\n{result.stderr}')
        if 'PLEASE submit' in result.stderr:
            raise AssertionError(result.stderr)

    # The property the contract names holds for this instantiation, so the
    # representation the contract chose is trusted.
    compiles('export unsigned ok(Holder<unsigned> v) { return transfer(v); }\n'
             'export unsigned also(Holder<Plain> v) { return transfer(v); }\n', True)
    # It does not hold: the class is not Send for this instantiation, whatever
    # the contract says about its storage.
    compiles('export unsigned bad(Holder<Raw> v) { return transfer(v); }\n', False)

    # The trait reads the same contracts.
    trait = tmp/'trait.cpp'
    trait.write_text('''#include <cstdio>
struct Raw { unsigned* p; };
struct Plain { unsigned v; };
template <class T+>
struct [[unsafe::send(T~is_send), unsafe::sync(T~is_sync)]] Holder { T* p_; };
using U = unsigned;
using HU = Holder<unsigned>;
using HP = Holder<Plain>;
using HR = Holder<Raw>;
int main() {
  // The traits remain checked; only the legacy output call crosses FFI.
  bool u = U~is_send, hu = HU~is_send, hp = HP~is_send, hr = HR~is_send;
  unsafe { std::printf("%d %d %d %d\\n", u, hu, hp, hr); }
  return 0;
}
''')
    binary = tmp/'trait'
    for optimization in ('-O0', '-O2'):
        build = subprocess.run([str(clang)]+flags+[optimization, str(trait), '-o', str(binary)],
                               text=True, capture_output=True)
        if build.returncode:
            raise AssertionError('trait program did not build:\n'+build.stderr)
        run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
        if run.returncode or run.stdout.splitlines() != ['1 1 1 0']:
            raise AssertionError(f'trait program produced {run.stdout.splitlines()}\n'
                                 f'{run.stderr}')

print('thread contracts: a claim written `[[unsafe::send(T~is_send)]]` is '
      'evaluated for each instantiation, and the trait reads it')
