#!/usr/bin/env python3
"""Drop-only destructors permit dangling fields only at drop use.

The positive cases cover both an explicit `drp` and automatic destruction.
The same source with a normal destructor must be rejected once the borrowed
owner has ended.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'

API = r'''
export template<class T+, bool DropOnly>
struct Holder {
  T value;
  explicit Holder(T input) safe : value(input) {}
  [[unsafe::drop_only(T)]] ~Holder() safe requires(DropOnly) {}
  ~Holder() safe requires(!DropOnly) {}
};

export unsigned explicit_good() safe {
  Holder<const int^, true> holder := void();
  {
    int value = 7;
    holder := Holder<const int^, true>(^const value);
  }
  drp holder;
  return 0u;
}

export unsigned automatic_good() safe {
  Holder<const int^, true> holder := void();
  {
    int value = 9;
    holder := Holder<const int^, true>(^const value);
  }
  return 0u;
}
'''

NEGATIVES = [
    (
        'explicit_bad',
        r'''
unsigned bad() safe {
  Holder<const int^, false> holder := void();
  {
    int value = 7;
    holder := Holder<const int^, false>(^const value);
  }
  drp holder;
  return 0u;
}
''',
        'dropping a borrow-carrying object requires drop_only',
    ),
    (
        'automatic_bad',
        r'''
unsigned bad() safe {
  Holder<const int^, false> holder := void();
  {
    int value = 9;
    holder := Holder<const int^, false>(^const value);
  }
  return 0u;
}
''',
        'dropping a borrow-carrying object requires drop_only',
    ),
]

with tempfile.TemporaryDirectory(prefix='circle-drop-only-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'drop_only': 'safe'}}))
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
             '-fcircle-borrow-values',
             '-fmodule-safety-policy=' + str(policy),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

    def run(args, success=True, needle=''):
        result = subprocess.run([str(CLANG)] + args, text=True,
                                capture_output=True, timeout=120)
        assert (result.returncode == 0) == success, result.stderr
        assert 'PLEASE submit' not in result.stderr
        if needle:
            assert needle in result.stderr, result.stderr

    for optimization in ('-O0', '-O2'):
        for sanitizer in ([], ['-fsanitize=address,undefined',
                               '-fno-sanitize-recover=all']):
            options = flags + [optimization] + sanitizer
            module = tmp / 'drop_only.cppm'
            pcm = tmp / 'drop_only.pcm'
            obj = tmp / 'drop_only.o'
            module.write_text('export module drop_only;\n' + API)
            run(options + ['--precompile', str(module), '-o', str(pcm)])
            run(options + ['-c', str(pcm), '-o', str(obj)])
            consumer = tmp / 'main.cpp'
            consumer.write_text('import drop_only;\n'
                                'int main() safe {return explicit_good() + automatic_good() == 0u ? 0 : 1;}\n')
            binary = tmp / 'run'
            run(options + ['-fmodule-file=drop_only=' + str(pcm), str(consumer),
                           str(obj), '-o', str(binary)])
            result = subprocess.run([str(binary)], text=True, capture_output=True,
                                    timeout=30, env=dict(os.environ,
                                    ASAN_OPTIONS='detect_stack_use_after_return=1'))
            assert result.returncode == 0, result.stderr
    for name, body, diagnostic in NEGATIVES:
        source = tmp / (name + '.cpp')
        source.write_text('import drop_only;\n' + body)
        run(flags + ['-fmodule-file=drop_only=' + str(pcm),
                     '-fsyntax-only', str(source)], False, diagnostic)

print('Drop-only destructors: explicit and automatic dangling drops accepted; '
      'normal destructors rejected across O0/O2, PCM and ASan/UBSan')
