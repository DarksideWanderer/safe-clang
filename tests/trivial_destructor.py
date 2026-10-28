#!/usr/bin/env python3
"""Circle `= trivial` suppresses subobject destruction in templates too."""
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'

SOURCE = r'''
struct Tracked {
  int* unsafe count;
  Tracked(int* c) safe : count(c) {}
  ~Tracked() safe { unsafe { ++*count; } }
};

struct Direct {
  Tracked t_;
  ~Direct() = trivial;
};

template<class T>
struct ManuallyDrop {
  T t_;
  ~ManuallyDrop() = trivial;
};

template<class T>
struct Defaulted {
  T t_;
  ~Defaulted() = default;
};

static_assert(Direct~is_trivially_destructible);
static_assert(ManuallyDrop<Tracked>~is_trivially_destructible);
static_assert(!Defaulted<Tracked>~is_trivially_destructible);
static_assert(!Tracked~is_trivially_destructible);

int run() unsafe {
  int count = 0;
  {
    Direct value{Tracked(&count)};
  }
  if (count != 0) return 1;
  {
    ManuallyDrop<Tracked> value{Tracked(&count)};
  }
  if (count != 0) return 2;
  {
    Defaulted<Tracked> value{Tracked(&count)};
  }
  if (count != 1) return 3;
  return 0;
}

int main() unsafe { return run(); }
'''

FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values',
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

with tempfile.TemporaryDirectory(prefix='trivial-destructor-') as directory:
    tmp = pathlib.Path(directory)
    source = tmp / 'trivial.cpp'
    source.write_text(SOURCE)
    for optimization in ('-O0', '-O2'):
        for sanitized in (False, True):
            options = FLAGS + [optimization]
            if sanitized:
                options += ['-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all']
            binary = tmp / ('trivial' + optimization + str(sanitized))
            build = subprocess.run([str(CLANG)] + options + [str(source), '-o',
                                   str(binary)], text=True, capture_output=True)
            if build.returncode:
                raise AssertionError('trivial destructor build failed:\n'
                                     + build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True,
                                 env=dict(__import__('os').environ,
                                          ASAN_OPTIONS='detect_stack_use_after_return=1'))
            if run.returncode:
                raise AssertionError(
                    f'trivial destructor exited {run.returncode}:\n' + run.stderr)
print('`= trivial` suppresses subobject destruction in direct, template, and '
      'defaulted comparisons at O0/O2 with and without ASan/UBSan')
