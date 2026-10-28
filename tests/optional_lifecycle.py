#!/usr/bin/env python3
"""Compile and run official and dependent optional choice lifecycles."""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else (
    ROOT / 'llvm-build/bin/clang')
REFERENCE = ROOT / 'downloads/safe-cpp-reference/libsafecxx'
OFFICIAL = REFERENCE / 'test/optional_test.cxx'
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values', '-I' + str(ROOT / 'include'),
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
OFFICIAL_FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
                  '-fcircle-borrow-values',
                  '-I' + str(REFERENCE / 'single-header'),
                  '-I' + str(REFERENCE / 'test'),
                  '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

PROGRAM = r'''#include "std2/std2.h"

struct Less {
  static bool invoke/(a)(int^/a x) safe {
    return *x < 100;
  }
};

static std2::optional<int> local_choice() safe {
  std2::optional<int> value = .some(23);
  return value;
}

static unsigned result_and_replace() safe {
  {
    std2::optional<int> value = .some(41);
    std2::expected<int, int> result = value.ok_or(7);
    if (result.unwrap() != 41) return 1u;
  }
  {
    std2::optional<int> value = .none;
    std2::expected<int, int> result = value.ok_or(99);
    int recovered = match(rel result) -> int {
      .ok(inner) => inner;
      .err(error) => error;
    };
    if (recovered != 99) return 2u;
  }
  {
    std2::vector<int> first{1, 2, 3, 4};
    std2::optional<std2::vector<int>> value = .some(rel first);
    std2::vector<int> second{4, 3, 2, 1, 1, 2, 3, 4};
    value = .some(rel second);
    std2::vector<int> result = (rel value).unwrap();
    if (result.size() != 8u) return 3u;
  }
  return 0u;
}

static unsigned take_predicate_and_local_result() safe {
  {
    std2::optional<int> value = .some(7);
    auto taken = mut value.take_if(addr Less::invoke);
    if (!taken.is_some() || !value.is_none()) return 1u;
  }
  {
    std2::optional<int> value = .some(101);
    auto taken = mut value.take_if(addr Less::invoke);
    if (taken.is_some() || value.is_none()) return 2u;
  }
  {
    auto value = local_choice();
    if (!value.is_some() || value.unwrap() != 23) return 3u;
  }
  return 0u;
}

int main() safe {
  unsigned failures = 0u;
  failures |= result_and_replace();
  failures |= take_predicate_and_local_result();
  return static_cast<int>(failures);
}
'''


def run(source, flags, tmp, label):
    for optimization in ('-O0', '-O2'):
        for sanitized in (False, True):
            options = flags + [optimization]
            if sanitized:
                options += ['-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all']
            executable = tmp / (label + optimization + str(sanitized))
            build = subprocess.run(
                [str(CLANG)] + options + [str(source), '-o', str(executable)],
                text=True, capture_output=True)
            if build.returncode:
                raise AssertionError(
                    f'{label} build failed at {optimization}, '
                    f'sanitized={sanitized}:\n{build.stderr}')
            executed = subprocess.run(
                [str(executable)], text=True, capture_output=True, timeout=60,
                env=dict(os.environ,
                         ASAN_OPTIONS='detect_stack_use_after_return=1'))
            if executed.returncode:
                raise AssertionError(
                    f'{label} exited {executed.returncode} at {optimization}, '
                    f'sanitized={sanitized}:\n{executed.stdout}\n'
                    f'{executed.stderr}')


if not OFFICIAL.is_file():
    raise SystemExit('missing pinned official optional_test source: ' +
                     str(OFFICIAL))

with tempfile.TemporaryDirectory(prefix='optional-lifecycle-') as directory:
    temporary = pathlib.Path(directory)
    consumer = temporary / 'optional_lifecycle.cpp'
    consumer.write_text(PROGRAM)
    run(OFFICIAL, OFFICIAL_FLAGS, temporary, 'official-optional')
    run(consumer, FLAGS, temporary, 'optional-lifecycle')

print('Official optional_test and dependent ok_or/drop-replace/take_if/local '
      'choice results compile, link and run at O0/O2 with and without '
      'ASan/UBSan')
