#!/usr/bin/env python3
"""Borrow-slot arrays bind their declared region through every element."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1
         else root/'llvm-build/bin/clang')

API = '''
struct Slots/(a) {
  const unsigned^/a values[2];
};
Slots/a make/(a)(const unsigned^/a x, const unsigned^/a y) safe {
  return Slots{{x, y}};
}
unsigned read(Slots/a value, unsigned index) safe {
  return *value.values[index];
}
struct View/(a) {
  const unsigned^/a value;
  View(const unsigned^/a input) safe : value(input) {}
};
template<class T+> struct SlotsT {
  T values[2];
};
SlotsT<View>/a make_t/(a)(const unsigned^/a x, const unsigned^/a y) safe {
  return SlotsT<View>{{View{x}, View{y}}};
}
unsigned read_t(SlotsT<View>/a value, unsigned index) safe {
  return *value.values[index].value;
}
'''

RUN = '''
unsigned run() safe {
  unsigned x = 1u, y = 2u;
  auto slots = make(^const x, ^const y);
  if (read(slots, 0u) != 1u || read(slots, 1u) != 2u) return 1u;
  {
    auto swapped = make(^const y, ^const x);
    if (read(swapped, 0u) != 2u || read(swapped, 1u) != 1u) return 2u;
  }
  {
    auto views = make_t(^const x, ^const y);
    if (read_t(views, 0u) != 1u || read_t(views, 1u) != 2u) return 3u;
  }
  return 0u;
}
'''

ENTRY = 'int main() safe { return static_cast<int>(run()); }\n'

NEGATIVES = [
    ('unsigned bad() safe { unsigned x=1u,y=2u;'
     ' auto slots=make(^const x,^const y); x=3u; return read(slots,0u); }',
     'mutation conflicts with a live borrow'),
    ('Slots/a bad/(a,b)(const unsigned^/a x, const unsigned^/b y) safe {'
     ' return Slots{{x,y}}; }',
     'returned reference does not borrow from the declared lifetime source'),
    ('Slots/a bad/(a)(const unsigned^/a x) safe {'
     ' unsigned local=1u; return Slots{{x,^const local}}; }',
     'returned reference does not borrow from the declared lifetime source'),
    ('unsigned bad() safe { unsigned x=1u,y=2u;'
     ' auto slots=make(^const x,^const y);'
     ' { const unsigned^/static leaked = slots.values[0]; (void)leaked; }'
     ' return 0u; }',
     'static borrow variable lifetime contract'),
]

with tempfile.TemporaryDirectory(prefix='borrow-slot-arrays-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps(
        {'version': 1, 'modules': {'slot_arrays': 'safe'}}))
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
             '-fcircle-borrow-values',
             '-fmodule-safety-policy='+str(policy),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

    def check(arguments, ok=True, diagnostic=None):
        result = subprocess.run([str(clang)]+arguments, text=True,
                                capture_output=True, timeout=120)
        assert (result.returncode == 0) == ok, result.stderr
        assert 'PLEASE submit' not in result.stderr, result.stderr
        if diagnostic:
            assert diagnostic in result.stderr, result.stderr
        return result

    module = tmp/'slot_arrays.cppm'
    module.write_text('export module slot_arrays;\nexport {\n'+API+'\n}\n')
    for optimization in ('-O0', '-O2'):
        for sanitize in (False, True):
            options = flags+[optimization]
            if sanitize:
                options += ['-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all']
            pcm = tmp/'slot_arrays.pcm'
            obj = tmp/'slot_arrays.o'
            check(options+['--precompile', str(module), '-o', str(pcm)])
            check(options+['-c', str(pcm), '-o', str(obj)])

            inline = tmp/'inline.cpp'
            inline.write_text(API+RUN+ENTRY)
            binary = tmp/'inline'
            check(options+[str(inline), '-o', str(binary)])
            subprocess.run([str(binary)], check=True, timeout=60)

            consumer = tmp/'consumer.cpp'
            consumer.write_text('import slot_arrays;\n'+RUN+ENTRY)
            imported = tmp/'imported'
            check(options+['-fmodule-file=slot_arrays='+str(pcm),
                           str(consumer), str(obj), '-o', str(imported)])
            subprocess.run([str(imported)], check=True, timeout=60)

            for body, diagnostic in NEGATIVES:
                bad = tmp/'bad.cpp'
                bad.write_text('import slot_arrays;\n'+body)
                check(options+['-fmodule-file=slot_arrays='+str(pcm),
                               '-fsyntax-only', str(bad)],
                      ok=False, diagnostic=diagnostic)

print('Borrow-slot arrays: direct and templated fields, element reads, '
      'region preservation and four refusals; local/PCM O0/O2 plain '
      'ASan/UBSan')
