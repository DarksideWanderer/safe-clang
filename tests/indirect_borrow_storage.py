"""Retain element provenance across indirect storage calls and CFG joins."""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'
HEADER = ROOT / 'downloads/safe-cpp-reference/libsafecxx/single-header'
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values', '-Wno-everything', '-I' + str(HEADER),
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
PREFIX = '#feature on safety\n#include <std2.h>\n'
OWNER = "const char text[]={'h','i'}; std2::string_view view=text;"
WRAPPER = '''
void store(std2::vector<std2::string_view>^ values, std2::string_view view) safe {
  values.push_back(view);
}
'''
NEGATIVES = [
    'int main() safe {std2::vector<std2::string_view> v; {' + OWNER +
    'v^.push_back(view);} std2::println(*v[0]);}',
    'int main() safe {std2::vector<std2::string_view> v; {' + OWNER +
    'if(view.size()) v^.push_back(view);} std2::println(*v[0]);}',
    WRAPPER + 'int main() safe {std2::vector<std2::string_view> v; {' + OWNER +
    'store(^v,view);} std2::println(*v[0]);}',
    WRAPPER + 'int main() safe {std2::vector<std2::string_view> v; {' + OWNER +
    'auto callback=&store; callback(^v,view);} std2::println(*v[0]);}',
    'int main() safe {std2::vector<std2::string_view> v; {' + OWNER +
    'v^.push_back(view);} auto moved=rel v; std2::println(*moved[0]);}',
    'int main() safe {std2::vector<std2::string_view> v; {' + OWNER +
    'auto alias=^v; alias.push_back(view);} std2::println(*v[0]);}',
]
POSITIVE = '''int main() safe {
  const char text[]={'h','i'};
  std2::vector<std2::string_view> values;
  values^.push_back(std2::string_view(text));
  std2::println(*values[0]);
  auto moved=rel values;
  std2::println(*moved[0]);
  std2::vector<std2::string_view> drop;
  { const char local[]={'x'}; drop^.push_back(std2::string_view(local)); }
  return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='indirect-borrow-storage-') as directory:
    tmp = pathlib.Path(directory)
    source = tmp / 'test.cpp'
    for optimization in ('-O0', '-O2'):
        for body in NEGATIVES:
            source.write_text(PREFIX + body)
            result = subprocess.run([str(CLANG)] + FLAGS + [optimization, '-fsyntax-only', str(source)],
                                    text=True, capture_output=True)
            if result.returncode == 0 or 'borrow outlives its owner' not in result.stderr:
                raise AssertionError(body + '\n' + result.stderr)
        source.write_text(PREFIX + POSITIVE)
        executable = tmp / 'positive'
        result = subprocess.run([str(CLANG)] + FLAGS + [optimization,
                                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                                str(source), '-o', str(executable)], text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        result = subprocess.run([str(executable)], text=True, capture_output=True,
                                env=dict(os.environ, ASAN_OPTIONS='detect_stack_use_after_return=1'))
        if result.returncode or result.stdout != 'hi\nhi\n':
            raise AssertionError(str(result.returncode) + result.stdout + result.stderr)
print('Indirect borrow storage: direct/wrapper/function-pointer/alias/branch/relocation dangling reads refused; live reads and drop-only pass at O0/O2 with ASan/UBSan')
