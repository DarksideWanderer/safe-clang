#!/usr/bin/env python3
"""Consuming receivers can retire one owned subobject without moving its parent."""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values', '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

API = '''
struct Part {
  unsigned value = 1u;
  Part() noexcept safe = default;
  unsigned take() && noexcept safe { return value; }
};

struct Inner {
  Part part;
  unsigned inner = 2u;
  Inner() noexcept safe = default;
};

struct Outer {
  Inner nested;
  unsigned outer = 3u;
  Outer() noexcept safe = default;
};

struct Base {
  unsigned value = 1u;
  Base() noexcept safe = default;
  virtual unsigned take() && noexcept safe { return value; }
};

struct Derived final : Base {
  Derived() noexcept safe = default;
  unsigned take() && noexcept safe override { return value + 1u; }
};

struct Holder {
  Derived base;
  unsigned other = 7u;
  Holder() noexcept safe = default;
};

struct ThrowingPart {
  unsigned value = 4u;
  ThrowingPart() noexcept safe = default;
  unsigned take() && noexcept(false) safe { throw value; }
};

struct ThrowingWhole {
  ThrowingPart part;
  unsigned other = 5u;
  ThrowingWhole() noexcept safe = default;
};

unsigned field_value() safe {
  Outer value;
  unsigned taken = static_cast<Part&&>(value.nested.part).take();
  return taken + value.nested.inner + value.outer;
}

unsigned base_value() safe {
  Holder holder;
  unsigned taken = static_cast<Base&&>(holder.base).take();
  return taken + holder.other;
}

unsigned whole_value() safe {
  Derived value;
  return static_cast<Base&&>(value).take();
}

unsigned eh_other() safe {
  ThrowingWhole value;
  try {
    static_cast<ThrowingPart&&>(value.part).take();
  } catch (...) {
    return value.other;
  }
  return 0u;
}
'''

MAIN = '''
int main() safe {
  return field_value() == 6u && base_value() == 9u && whole_value() == 2u &&
         eh_other() == 5u ? 0 : 1;
}
'''

NEGATIVE = [
    ('''unsigned bad() safe {
  Outer value;
  static_cast<Part&&>(value.nested.part).take();
  return value.nested.part.value;
}''', 'use of a partially relocated owner or an absent field'),
    ('''struct ParentBad { Part part; ParentBad() noexcept safe = default; ~ParentBad() safe {} };
unsigned bad() safe {
  ParentBad value;
  return static_cast<Part&&>(value.part).take();
}''', 'consuming a subobject requires an owned path'),
    ('''struct Nontrivial { unsigned value = 1u; Nontrivial() noexcept safe = default; ~Nontrivial() safe {} unsigned take() && noexcept safe { return value; } };
struct NontrivialWhole { Nontrivial part; NontrivialWhole() noexcept safe = default; };
unsigned bad() safe {
  NontrivialWhole value;
  return static_cast<Nontrivial&&>(value.part).take();
}''', 'consuming a subobject requires an owned path'),
    ('''unsigned bad() safe {
  ThrowingWhole value;
  try { static_cast<ThrowingPart&&>(value.part).take(); }
  catch (...) { return value.part.value; }
  return 0u;
}''', 'use of a partially relocated owner or an absent field'),
    ('''unsigned bad(Part& part) safe {
  return static_cast<Part&&>(part).take();
}''', 'consuming receiver cannot consume through a borrow'),
    ('''unsigned bad(Derived& value) safe {
  return static_cast<Base&&>(value).take();
}''', 'consuming receiver cannot consume through a borrow'),
    ('''unsigned bad() safe {
  Derived value;
  static_cast<Base&&>(value).take();
  return value.value;
}''', 'use of a moved value'),
]

with tempfile.TemporaryDirectory(prefix='partial-moves-') as directory:
    tmp = pathlib.Path(directory)
    source = tmp / 'test.cpp'
    for optimization in ('-O0', '-O2'):
        for sanitized in (False, True):
            options = FLAGS + [optimization]
            if sanitized:
                options += ['-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all']
            source.write_text(API + MAIN)
            executable = tmp / ('run' + optimization + str(sanitized))
            build = subprocess.run([str(CLANG)] + options + [str(source), '-o',
                                   str(executable)], text=True, capture_output=True)
            if build.returncode:
                raise AssertionError(build.stderr)
            run = subprocess.run([str(executable)], text=True, capture_output=True,
                                 env=dict(os.environ,
                                          ASAN_OPTIONS='detect_stack_use_after_return=1'))
            if run.returncode:
                raise AssertionError(f'partial-move program exited {run.returncode}:\n'
                                     + run.stderr)
            for body, diagnostic in NEGATIVE:
                source.write_text(API + body)
                result = subprocess.run([str(CLANG)] + options + ['-fsyntax-only',
                                       str(source)], text=True, capture_output=True)
                if result.returncode == 0 or diagnostic not in result.stderr or \
                        'PLEASE submit' in result.stderr:
                    raise AssertionError('missing expected partial-move refusal '
                                         + diagnostic + ':\n' + result.stderr)

print('Partial owned subobject moves: field, nested field, virtual base-field '
      'dispatch and EH paths pass at O0/O2 with ASan/UBSan; moved-field, '
      'unsafe-parent, non-trivial-drop and borrow refusals passed')
