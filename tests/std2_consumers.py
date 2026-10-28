#!/usr/bin/env python3
"""Compile, link and run ordinary programs that use `include/std2/std2.h`.

The header's own translation-unit check only says that it parses. A consumer
compiles the generated code, links it and runs it, which is what exercises the
slice borrow representation, the values the compiler forms for the classes the
library declares, and `choice` construction and matching.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
policy = root/'build/circle-compatibility.policy.json'
resource_dir = os.environ.get(
    'MODULE_SAFETY_RESOURCE_DIR', '/opt/homebrew/opt/llvm/lib/clang/22')
flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values',
         '-fmodule-safety-policy='+str(policy), '-I'+str(root/'include'),
         '-resource-dir='+resource_dir]

PROGRAM = '''#include "std2/std2.h"

// A choice the user defines, matched and relocated like the library's.
choice Shape {
  default point,
  disc(int);
};

int main() safe {
  // A literal is the compiler-provided `string_constant`, a view of it, and a
  // heap string built from one.
  std2::println("hello std2");
  std2::string_view sv("literal view");
  std2::println(sv);
  std2::string s("abc");
  // A mutation spells the mutable receiver: the `mut` token enters the
  // mutable context that binds it, exactly as the library's own tests do.
  mut s.append(std2::string_view("def"));
  std2::println(s.str());
  auto string_bytes = std2::slice_from_raw_parts(s.data(), s.size());
  std2::println((*string_bytes)~length);

  // A choice value: the tag and the payload are both written, and matching the
  // alternative reads the payload back.
  std2::optional<int> o = .some(7);
  std2::println(o.is_some());
  std2::println(o.unwrap());
  std2::optional<int> n;
  std2::println(n.is_none());
  std2::optional<int> taken = .some(9);
  auto got = mut taken.take();
  std2::println(got.unwrap());
  std2::println(taken.is_none());
  std2::optional<std2::string> optional_string = .some(std2::string("opt"));
  auto unwrapped = (rel optional_string).unwrap();
  std2::println(unwrapped.size());
  std2::vector<std2::string> strings;
  mut strings.push_back(std2::string("x"));
  mut strings.push_back(std2::string("yz"));
  std2::println(strings.size());
  std2::box<std2::string> string_box(std2::string("box"));
  std2::println((*string_box).size());
  Shape sh = .disc(3);
  std2::println(match(sh) -> int { .disc(r) => r; .point => 0; });

  // Numerics.
  std2::println(static_cast<short>(-3));
  std2::println(3.5);

  // A container grown at run time, read through its checked subscript.
  std2::vector<int> v;
  mut v.push_back(10);
  mut v.push_back(20);
  mut v.push_back(30);
  std2::println(v.size());
  std2::println(*v[1]);

  // `data()` and `size()` on the same vector place a checked raw-parts slice.
  auto vector_bytes = std2::slice_from_raw_parts(v.data(), v.size());
  std2::println((*vector_bytes)~length);

  // The official receiver spelling: a postfix loan selects the mutable
  // explicit object parameter without an extra `mut` token.
  std2::vector<int> postfix;
  postfix^.push_back(40);
  postfix^.push_back(41);
  std2::println(postfix.size());
  std2::println(*postfix[1]);
  auto postfix_slice = postfix^.slice();
  postfix_slice[1] = 43;
  std2::println(*postfix[1]);

  // Braced owning elements relocate into the container. The
  // initializer_list destructor only destroys elements that were not
  // consumed, so the backing array must not destroy the relocated boxes.
  std2::vector<std2::box<int>> boxes = {
      std2::box<int>(11), std2::box<int>(12), std2::box<int>(13)};
  std2::println(boxes.size());
  std2::println(**boxes[0]);
  std2::println(**boxes[1]);
  std2::println(**boxes[2]);

  // An owning box, read through its borrow: `*b` projects the borrow the
  // operator returns to the referent, and `mut *b` binds it mutably.
  std2::box<int> b(5);
  std2::println(*b);
  int^ boxed = mut *b;
  *boxed = 6;
  std2::println(*b);
  std2::box<std2::box<int>> nested(std2::box<int>(7));
  std2::println(**nested);

  // A container of borrow values. The owner ends before the vector, but the
  // drop_only destructor may still relocate and destroy the elements.
  {
    std2::vector<const int^> borrowed;
    {
      int local = 41;
      mut borrowed.push_back(^const local);
    }
    drp borrowed;
  }
  // The same drop-only contract must also hold for automatic destruction at
  // scope end; dropping the vector does not use the dangling element regions.
  {
    std2::vector<const int^> borrowed_scope;
    {
      int local = 42;
      mut borrowed_scope.push_back(^const local);
    }
  }
  return 0;
}
'''

EXPECTED = ['hello std2', 'literal view', 'abcdef', '6', '1', '7', '1', '9', '1',
            '3', '2', '3', '3', '-3',
            '3.500000', '3', '20', '3', '2', '41', '43', '3', '11', '12', '13',
            '5', '6', '7']

tmp = pathlib.Path(tempfile.mkdtemp(prefix='std2-consumers-'))
try:
    source = tmp/'consumer.cpp'
    source.write_text(PROGRAM)
    for optimization in ('-O0', '-O2'):
        for sanitizers in ([], ['-fsanitize=address,undefined',
                                '-fno-sanitize-recover=all']):
            executable = tmp/('consumer'+optimization+str(len(sanitizers)))
            build = subprocess.run(
                [str(clang)]+flags+[optimization]+list(sanitizers) +
                [str(source), '-o', str(executable)],
                text=True, capture_output=True)
            if build.returncode:
                raise AssertionError('consumer did not build:\n'+build.stderr)
            run = subprocess.run(
                [str(executable)], text=True, capture_output=True, timeout=60,
                env=dict(os.environ, ASAN_OPTIONS='detect_stack_use_after_return=1'))
            if run.returncode:
                raise AssertionError(
                    f'consumer exited {run.returncode}:\n{run.stdout}\n'
                    f'{run.stderr}')
            lines = run.stdout.splitlines()
            if lines != EXPECTED:
                raise AssertionError(f'consumer output {lines} != {EXPECTED}')
except BaseException:
    print('std2 consumer artifacts kept at', tmp, file=sys.stderr)
    raise
else:
    shutil.rmtree(tmp)

print('std2.h consumers compile, link and run: literals, string views and '
      'strings, choice construction/matching/take, vectors, boxes')
