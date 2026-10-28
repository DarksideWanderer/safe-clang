#!/usr/bin/env python3
"""Check literal provenance and run the untouched official string_view test."""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'
REFERENCE = ROOT / 'downloads/safe-cpp-reference/libsafecxx'
SOURCE = REFERENCE / 'test/string_view_test.cxx'
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values', '-I' + str(REFERENCE / 'single-header'),
         '-I' + str(REFERENCE / 'test'),
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

if not SOURCE.is_file():
    raise SystemExit('missing pinned official string_view_test source: ' + str(SOURCE))

# The literal operator returns a `/static` class value. A call that only reads
# that value must retain the literal's immutable origin; treating it as an
# opaque mutable-static sentinel makes the untouched official test fail.
check = subprocess.run([str(CLANG)] + FLAGS + ['-Werror=unknown-attributes',
                        '-fsyntax-only', str(SOURCE)], text=True, capture_output=True)
if check.returncode:
    raise AssertionError('official string_view_test syntax check failed:\n'
                         + check.stderr)

with tempfile.TemporaryDirectory(prefix='official-string-view-test-') as directory:
    tmp = pathlib.Path(directory)
    for optimization in ('-O0', '-O2'):
        for sanitized in (False, True):
            options = FLAGS + [optimization, '-DLIBSAFECXX_PANIC_THROWS']
            if sanitized:
                options += ['-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all']
            executable = tmp / ('string_view' + optimization + str(sanitized))
            build = subprocess.run([str(CLANG)] + options + [str(SOURCE), '-o',
                                   str(executable)], text=True, capture_output=True)
            if build.returncode:
                raise AssertionError('official string_view_test build failed:\n'
                                     + build.stderr)
            run = subprocess.run([str(executable)], text=True, capture_output=True,
                                 env=dict(os.environ,
                                          ASAN_OPTIONS='detect_stack_use_after_return=1'))
            if run.returncode:
                raise AssertionError(
                    f'official string_view_test exited {run.returncode}:\n'
                    + run.stderr)

print('Untouched official Safe C++ string_view_test preserves literal provenance '
      'and runs at O0/O2 with and without ASan/UBSan')
