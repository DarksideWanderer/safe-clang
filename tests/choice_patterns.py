#!/usr/bin/env python3
"""Exercise `match` patterns: alternatives, `|`, values, ranges and nesting."""
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
policy = root/'build/circle-compatibility.policy.json'
driver = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
          '-fcircle-borrow-values', '-fmodule-safety-policy='+str(policy)]

DECLARATIONS = '''#include <cstdio>

choice Digit { default not_a_digit, digit(int) };
choice Sign { default zero, positive, negative };
choice Two { default none2, left(int), right(int) };
choice Inner { default empty, holds(int) };
choice Outer { default nothing, wraps(Inner) };
'''

BODY = '''
template<class... Args>
void output(const char* format, Args... args) safe {
  unsafe { std::printf(format, args...); }
}

unsigned classify(unsigned value) safe {
  // A value pattern, a range, and an arm that matches anything.
  return match(value) -> unsigned {
    0 => 10u;
    1...9 => 20u;
    _ => 30u;
  };
}

unsigned sign_of(Sign value) safe {
  // Several alternatives share one arm.
  return match(value) -> unsigned {
    .positive | .negative => 1u;
    .zero => 0u;
  };
}

unsigned digit_of(Digit value) safe {
  // A range and a catch-all matched against the payload of the alternative
  // above them.
  return match(value) -> unsigned {
    .digit(0...9) => 1u;
    .digit(_) => 2u;
    .not_a_digit => 0u;
  };
}

int inner_value(Outer value) safe {
  // A pattern nested in the payload of the alternative above it.
  return match(value) -> int {
    .wraps(.holds(v)) => v;
    .wraps(.empty) => 0;
    .nothing => -1;
  };
}

int main() {
  output("values %u %u %u %u %u\\n", classify(0u), classify(1u),
              classify(8u), classify(9u), classify(42u));
  output("signs %u %u\\n", sign_of(.positive), sign_of(.zero));
  output("digits %u %u %u %u\\n", digit_of(.digit(7)), digit_of(.digit(9)), digit_of(.digit(70)),
              digit_of(.not_a_digit));
  output("nested %d %d %d\\n", inner_value(.wraps(.holds(7))),
              inner_value(.wraps(.empty)), inner_value(.nothing));
  return 0;
}
'''

EXPECTED = ['values 10 20 20 30 30', 'signs 1 0', 'digits 1 2 2 0', 'nested 7 0 -1']

REFUSALS = [
    # A value that no arm names cannot be matched.
    ('unsigned f(unsigned v) safe {'
     ' return match(v) -> unsigned { 0 => 1u; }; }',
     'requires an arm that matches anything'),
    # An alternative the choice does not have.
    ('unsigned f(Sign v) safe {'
     ' return match(v) -> unsigned { .sideways => 1u; .zero => 0u; }; }',
     'no choice alternative'),
    # Every alternative of a `|` pattern must bind the same names.
    ('unsigned f(Two v) safe {'
     ' return match(v) -> unsigned { .left(a) | .right(b) => 1u; .none2 => 0u; }; }',
     'must bind the same names'),
    # A catch-all arm cannot hide the arms that follow it.
    ('unsigned f(Sign v) safe {'
     ' return match(v) -> unsigned { _ => 0u; .zero => 1u; }; }',
     'catch-all match arm must come last'),
    # A nested pattern needs the payload's alternatives.
    ('choice Holder { default none, ring(int) };'
     'unsigned f(Holder v) safe {'
     ' return match(v) -> unsigned { .ring(.holds(x)) => 1u; .none => 0u; }; }',
     'choice alternative pattern needs a choice operand'),
    # A `match` needs a value it can test.
    ('struct Wide { unsigned a, b; };'
     'unsigned f(Wide v) safe { return match(v) -> unsigned { _ => 1u; }; }',
     'must be a choice, a bool or an integer'),
]

with tempfile.TemporaryDirectory(prefix='choice-patterns-') as directory:
    tmp = pathlib.Path(directory)
    source = tmp/'patterns.cpp'
    source.write_text(DECLARATIONS+BODY)
    binary = tmp/'patterns'
    build = subprocess.run([str(clang)]+driver+[str(source), '-o', str(binary)],
                           text=True, capture_output=True)
    if build.returncode:
        raise AssertionError('patterns did not build:\n'+build.stderr)
    run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
    if run.returncode or run.stdout.splitlines() != EXPECTED:
        raise AssertionError(f'patterns produced {run.stdout.splitlines()} '
                             f'(exit {run.returncode})\n{run.stderr}')
    for body, needle in REFUSALS:
        source.write_text(DECLARATIONS+body+'\n')
        result = subprocess.run([str(clang)]+driver+['-fsyntax-only', str(source)],
                                text=True, capture_output=True)
        if result.returncode == 0 or needle not in result.stderr:
            raise AssertionError(f'{body} was not refused with {needle}:\n{result.stderr}')

print('match patterns: alternatives, `|`, values, ranges, nested payloads and 6 refusals passed')
