#!/usr/bin/env python3
"""`safe(e)` asks for the written safe effect, including through templates."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1
         else root/'llvm-build/bin/clang')

API = '''
unsigned checked(unsigned x) safe { return x + 1u; }
unsigned plain(unsigned x) { return x + 2u; }
unsafe_fn unsigned danger(unsigned x) { return x + 3u; }
template<class F> void thread_like(F f)
  requires(safe(mut f(1u))) {}
'''

COMMON = '''
static_assert(safe(checked(1u)));
static_assert(!safe(danger(1u)));

template<class F> void expect_safe(F f) {
  static_assert(safe(f(1u)));
}
template<class F> void expect_unsafe(F f) {
  static_assert(!safe(f(1u)));
}
'''

INLINE_RUN = COMMON + '''
static_assert(!safe(plain(1u)));

unsigned run() {
  expect_safe(&checked);
  expect_unsafe(&plain);
  expect_unsafe(&danger);
  thread_like(&checked);

  constexpr auto checked_pointer = &checked;
  constexpr auto plain_pointer = &plain;
  static_assert(safe(checked_pointer(1u)));
  static_assert(!safe(plain_pointer(1u)));
  return 0u;
}
'''

IMPORTED_RUN = COMMON + '''
// A named safe module gives an unsuffixed definition the module-wide safe
// default, so its function type is a safe function type across the PCM.
static_assert(safe(plain(1u)));

unsigned run() {
  expect_safe(&checked);
  expect_safe(&plain);
  expect_unsafe(&danger);
  thread_like(&checked);
  return 0u;
}
'''

ENTRY = 'int main() { return static_cast<int>(run()); }\n'

INLINE_NEGATIVES = [
    'void bad() { thread_like(&plain); }',
    'void bad() { thread_like(&danger); }',
    'static_assert(safe(plain(1u)));',
    'static_assert(!safe(checked(1u)));',
]

IMPORTED_NEGATIVES = [
    'void bad() { thread_like(&danger); }',
    'static_assert(!safe(checked(1u)));',
]

with tempfile.TemporaryDirectory(prefix='safe-effect-atom-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps(
        {'version': 1, 'modules': {'safe_atom': 'safe'}}))
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
             '-fcircle-borrow-values',
             '-fmodule-safety-policy='+str(policy),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

    def check(arguments, ok=True):
        result = subprocess.run([str(clang)]+arguments, text=True,
                                capture_output=True, timeout=120)
        assert (result.returncode == 0) == ok, result.stderr
        assert 'PLEASE submit' not in result.stderr, result.stderr
        return result

    module = tmp/'safe_atom.cppm'
    module.write_text('export module safe_atom;\nexport {\n'+API+'\n}\n')
    for optimization in ('-O0', '-O2'):
        for sanitize in (False, True):
            options = flags+[optimization]
            if sanitize:
                options += ['-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all']
            pcm = tmp/'safe_atom.pcm'
            obj = tmp/'safe_atom.o'
            check(options+['--precompile', str(module), '-o', str(pcm)])
            check(options+['-c', str(pcm), '-o', str(obj)])

            inline = tmp/'inline.cpp'
            inline.write_text(API+INLINE_RUN+ENTRY)
            binary = tmp/'inline'
            check(options+[str(inline), '-o', str(binary)])
            subprocess.run([str(binary)], check=True, timeout=60)

            consumer = tmp/'consumer.cpp'
            consumer.write_text('import safe_atom;\n'+IMPORTED_RUN+ENTRY)
            imported = tmp/'imported'
            check(options+['-fmodule-file=safe_atom='+str(pcm),
                           str(consumer), str(obj), '-o', str(imported)])
            subprocess.run([str(imported)], check=True, timeout=60)

            for body in INLINE_NEGATIVES:
                bad = tmp/'bad.cpp'
                bad.write_text(API+body)
                check(options+['-fsyntax-only', str(bad)], ok=False)

            for body in IMPORTED_NEGATIVES:
                bad = tmp/'bad.cpp'
                bad.write_text('import safe_atom;\n'+body)
                check(options+['-fmodule-file=safe_atom='+str(pcm),
                               '-fsyntax-only', str(bad)], ok=False)

print('safe(e): written effect for direct, indirect, template-instantiated '
      'and PCM calls; six refusals; local/PCM O0/O2 plain ASan/UBSan')
