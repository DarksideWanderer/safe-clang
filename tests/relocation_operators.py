#!/usr/bin/env python3
"""A type that relocates itself through the operator its definition declares."""
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
policy = root/'build/circle-compatibility.policy.json'
driver = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
          '-fcircle-borrow-values', '-fmodule-safety-policy='+str(policy)]

PROGRAM = '''#include <cstdio>
#feature on safety

// A relocation that is not a copy of the representation: the destination holds
// a value the source's own bytes do not.
struct Tagged {
  int value;
  int derived;
  operator rel(Tagged) {
    return Tagged{value, value * 2};
  }
};

choice Box { default empty, full(Tagged) };

unsigned relocations = 0u;

struct Counted {
  int value;
  operator rel(Counted) {
    unsafe { ++relocations; }
    return Counted{value + 1};
  }
};

choice Slot { default blank, taken(Counted) };

int main() {
  Tagged source{21, 0};
  Tagged moved = rel source;
  unsafe { std::printf("%d %d\\n", moved.value, moved.derived); }

  // A match binding relocates its payload through the same operator.
  Box box = .full(Tagged{5, 0});
  int box_read = match(box) -> int { .full(t) => (rel t).derived; .empty => -1; };
  unsafe { std::printf("%d\\n", box_read); }

  // The native relocation read calls it too.
  Slot slot = .taken(Counted{7});
  int read = match(slot) -> int { .taken(c) => (rel c).value; .blank => -1; };
  unsafe { std::printf("%d %u\\n", read, relocations); }
  return 0;
}
'''

EXPECTED = ['21 42', '10', '8 1']

with tempfile.TemporaryDirectory(prefix='relocation-operators-') as directory:
    tmp = pathlib.Path(directory)
    source = tmp/'relocation.cpp'
    source.write_text(PROGRAM)
    binary = tmp/'relocation'
    for optimization in ('-O0', '-O2'):
        for sanitizer in ([], ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']):
            build = subprocess.run([str(clang)]+driver+[optimization, '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22', *sanitizer, str(source), '-o', str(binary)],
                                   text=True, capture_output=True)
            if build.returncode:
                raise AssertionError('relocation operator program did not build:\n'+build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
            if run.returncode or run.stdout.splitlines() != EXPECTED:
                raise AssertionError(f'relocation program produced {run.stdout.splitlines()} '
                                     f'(exit {run.returncode})\n{run.stderr}')

print('user-defined relocation operators: `rel`, match bindings and choice '
      'payloads relocate through the operator the definition declares')
