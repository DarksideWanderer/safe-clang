#!/usr/bin/env python3
"""Compile, link and run every untouched official Safe C++ positive test.

The matrix is O0/O2 with and without ASan/UBSan.  ``string_view_test`` needs
``LIBSAFECXX_PANIC_THROWS`` because it intentionally constructs invalid UTF
and catches the resulting panic.  ``source_location_test`` passes a
non-NUL-terminated char buffer to its own ``%s`` print, so ASan correctly
reports the test's stack overread; that file is checked in plain builds only.
"""
import argparse
import concurrent.futures
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CLANG = ROOT / 'llvm-build/bin/clang'
REFERENCE = ROOT / 'downloads/safe-cpp-reference/libsafecxx'
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values',
         '-I' + str(REFERENCE / 'single-header'),
         '-I' + str(REFERENCE / 'test'),
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22', '-w']


def configuration(source, optimization, sanitized):
    exe = source.stem + optimization + ('_san' if sanitized else '_plain')
    options = FLAGS + [optimization]
    if source.name == 'string_view_test.cxx':
        options.append('-DLIBSAFECXX_PANIC_THROWS')
    if sanitized:
        options += ['-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all']
    return exe, options + [str(source)]


def run_one(clang, directory, source, optimization, sanitized):
    exe, options = configuration(source, optimization, sanitized)
    binary = pathlib.Path(directory) / exe
    build = subprocess.run([str(clang)] + options + ['-o', str(binary)],
                           text=True, encoding='utf-8', errors='replace',
                           capture_output=True, timeout=180)
    if build.returncode:
        raise AssertionError(
            f'{source.name} {optimization} '
            f'{"sanitized" if sanitized else "plain"} build failed:\n'
            + build.stderr)
    run = subprocess.run([str(binary)], text=True, encoding='utf-8',
                         errors='replace', capture_output=True,
                         timeout=180,
                         env=dict(os.environ,
                                  ASAN_OPTIONS='detect_stack_use_after_return=1'))
    if run.returncode:
        raise AssertionError(
            f'{source.name} {optimization} '
            f'{"sanitized" if sanitized else "plain"} exited '
            f'{run.returncode}:\n' + run.stderr)
    return (source.name, optimization, sanitized)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('clang', nargs='?', default=str(DEFAULT_CLANG))
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    clang = pathlib.Path(args.clang).resolve()
    sources = sorted((REFERENCE / 'test').glob('*.cxx'))
    if len(sources) != 14:
        raise SystemExit(f'expected 14 official positive tests, found {len(sources)}')
    jobs = []
    for source in sources:
        for optimization in ('-O0', '-O2'):
            jobs.append((source, optimization, False))
            if source.name != 'source_location_test.cxx':
                jobs.append((source, optimization, True))
    with tempfile.TemporaryDirectory(prefix='official-positive-') as directory:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(run_one, clang, directory, *job) for job in jobs]
            for future in concurrent.futures.as_completed(futures):
                name, optimization, sanitized = future.result()
                print('PASS', name, optimization,
                      'ASan/UBSan' if sanitized else 'plain', flush=True)
    print(f'{len(jobs)} official positive configurations passed across '
          f'{len(sources)} files')


if __name__ == '__main__':
    main()
