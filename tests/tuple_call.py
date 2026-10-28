#!/usr/bin/env python3
"""`f.(args)` spreads the elements of the tuple its argument names."""
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
template<class... Args>
void output(const char* format, Args... args) safe {
  unsafe { std::printf(format, args...); }
}

(int, int) pair() noexcept safe { return (1, 2); }
(int, int, int) triple() noexcept safe { return (4, 5, 6); }
int add(int a, int b) noexcept safe { return a + b; }
int digits(int a, int b, int c) noexcept safe { return a * 100 + b * 10 + c; }
unsigned count(int a, int b, int c) noexcept safe { return 3u; }

int main() {
  auto two = pair();
  auto three = triple();
  output("%d %d\\n", add.(two), add.(3, 4));
  output("%d %d\\n", digits.(three), digits.(three.[:]));
  output("%u\\n", count.(three));
  return 0;
}
'''

EXPECTED = ['3 7', '456 456', '3']

with tempfile.TemporaryDirectory(prefix='tuple-call-') as directory:
    tmp = pathlib.Path(directory)
    source = tmp/'tuple_call.cpp'
    source.write_text(PROGRAM)
    binary = tmp/'tuple_call'
    for optimization in ('-O0', '-O2'):
        build = subprocess.run([str(clang)]+driver+[optimization, str(source), '-o', str(binary)],
                               text=True, capture_output=True)
        if build.returncode:
            raise AssertionError('tuple call program did not build:\n'+build.stderr)
        run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
        if run.returncode or run.stdout.splitlines() != EXPECTED:
            raise AssertionError(f'tuple call produced {run.stdout.splitlines()} '
                                 f'(exit {run.returncode})\n{run.stderr}')

print('tupled calls: `f.(tuple)` spreads the elements, and a parenthesized list '
      'stays a call with those arguments')
