#!/usr/bin/env python3
"""Circle's borrow-copy constructor is not a trivial copy operation."""
import json
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = root/'llvm-build/bin/clang'

POSITIVE = '''#include "std2/std2.h"
struct Trivial { int value = 1; };
struct BorrowCopy {
  int value = 0;
  BorrowCopy() safe = default;
  BorrowCopy(BorrowCopy const^ rhs) safe : value{rhs->value} {}
};
static_assert(Trivial~is_trivially_copyable);
static_assert(!BorrowCopy~is_trivially_copyable);
template<class T> void need(T value) safe requires(T~is_trivially_copyable) {}
void accept() safe {
  need(Trivial{});
  std2::cell<Trivial> value{Trivial{}};
  (void)value.get();
}
'''

NEGATIVES = (
    ('void reject() safe { need(BorrowCopy{}); }',
     'no matching function for call to '),
    ('void reject_cell() safe { std2::cell<BorrowCopy> value{BorrowCopy{}}; }',
     'no matching constructor for initialization of '),
)

with tempfile.TemporaryDirectory(prefix='trivial-copy-borrow-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {}}))
    source = tmp/'source.cpp'
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
             '-fcircle-borrow-values', '-fmodule-safety-policy='+str(policy),
             '-I'+str(root/'include'),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

    source.write_text(POSITIVE)
    result = subprocess.run([str(clang)]+flags+['-fsyntax-only', str(source)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + POSITIVE

    for body, diagnostic in NEGATIVES:
        source.write_text(POSITIVE + '\n' + body + '\n')
        result = subprocess.run([str(clang)]+flags+['-fsyntax-only', str(source)],
                                text=True, capture_output=True)
        assert result.returncode != 0 and diagnostic in result.stderr, result.stderr
        assert 'PLEASE submit' not in result.stderr, result.stderr

print('Circle borrow-copy constructors are excluded from trivial copying and '
      'constrained std2::cell construction; 2 refusals passed')
