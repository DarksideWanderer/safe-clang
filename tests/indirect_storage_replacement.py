"""Replacement transfers indirect borrows without retaining dead source storage."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values', '-Wno-everything',
         '-I' + str(ROOT / 'downloads/safe-cpp-reference/libsafecxx/single-header'),
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
DECLARATIONS = '''struct Store {std2::vector<std2::string_view> values; Store() safe {}};
struct Nested {Store store; Nested() safe {}};
'''
PREFIX = '#feature on safety\n#include <std2.h>\n' + DECLARATIONS
PRELUDE = ''.join('#include <' + name + '>\n' for name in
                  ('cstdio', 'memory', 'thread', 'mutex', 'shared_mutex', 'new',
                   'cstring', 'atomic', 'string'))
CASES = [
    ('field_live', True, '''int main() safe {
 const char text[]={'o','k'};Store store;
 {std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));store.values := rel source;}
 std2::println(*store.values[0]);return 0;}
''', ''),
    ('field_expired', False, '''int main() safe {Store store;
 {const char text[]={'n','o'};std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));store.values := rel source;}
 std2::println(*store.values[0]);}
''', 'borrow outlives its owner'),
    ('field_moved_parent_expired', False, '''int main() safe {Store store;
 {const char text[]={'n','o'};std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));store.values := rel source;}
 auto moved=rel store;std2::println(*moved.values[0]);}
''', 'borrow outlives its owner'),
    ('nested_field_live', True, '''int main() safe {
 const char text[]={'o','k'};Nested value;
 {std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));value.store.values := rel source;}
 std2::println(*value.store.values[0]);return 0;}
''', ''),
    ('nested_field_expired', False, '''int main() safe {Nested value;
 {const char text[]={'n','o'};std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));value.store.values := rel source;}
 std2::println(*value.store.values[0]);}
''', 'borrow outlives its owner'),
    ('whole_live', True, '''int main() safe {
 const char text[]={'o','k'};std2::vector<std2::string_view> values;
 {std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));values := rel source;}
 std2::println(*values[0]);return 0;}
''', ''),
    ('whole_expired', False, '''int main() safe {
 std2::vector<std2::string_view> values;
 {const char text[]={'n','o'};std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));values := rel source;}
 std2::println(*values[0]);}
''', 'borrow outlives its owner'),
    ('field_releases_old', True, '''int main() safe {
 const char text[]={'o','k'};Store store;
 {const char old[]={'n','o'};store.values^.push_back(std2::string_view(old));}
 std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));store.values := rel source;
 std2::println(*store.values[0]);return 0;}
''', ''),
    ('whole_releases_fields', True, '''int main() safe {
 const char text[]={'o','k'};Store store;
 {const char old[]={'n','o'};store.values^.push_back(std2::string_view(old));}
 Store source;source.values^.push_back(std2::string_view(text));
 store := rel source;std2::println(*store.values[0]);return 0;}
''', ''),
    ('field_retains_permission', False, '''int main() safe {
 char text[]={'o','k'};Store store;std2::vector<std2::string_view> source;
 source^.push_back(std2::string_view(text));store.values := rel source;
 text[0]='n';std2::println(*store.values[0]);}
''', 'mutation conflicts with a live borrow'),
]

with tempfile.TemporaryDirectory(prefix='indirect-storage-replacement-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'replacement_api': 'safe'}}))
    flags = FLAGS + ['-fmodule-safety-policy=' + str(policy)]
    for opt in ('-O0', '-O2'):
        options = [*flags, opt, '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        module = tmp / 'api.cppm'
        pcm = tmp / 'api.pcm'
        obj = tmp / 'api.o'
        module.write_text('module;\n' + PRELUDE +
                          'export module replacement_api;\nexport {\n#include <std2.h>\n' +
                          DECLARATIONS + '}\n')
        for arguments in (['--precompile', str(module), '-o', str(pcm)],
                          ['-c', str(pcm), '-o', str(obj)]):
            built = subprocess.run([str(CLANG), *options, *arguments],
                                   capture_output=True, text=True, timeout=120)
            assert built.returncode == 0, built.stderr
        for imported, name, valid, body, diagnostic in (
                (imported, *case) for imported in (False, True) for case in CASES):
            source = tmp / (name + '.cpp')
            prefix = '#feature on safety\nimport replacement_api;\n' if imported else PREFIX
            source.write_text(prefix + body)
            imports = ['-fmodule-file=replacement_api=' + str(pcm)] if imported else []
            binary = tmp / name
            result = subprocess.run([str(CLANG), *options, *imports, str(source),
                                     *([str(obj)] if imported else []), '-o', str(binary)],
                                    capture_output=True, text=True, timeout=120)
            if valid:
                assert result.returncode == 0, name + '\n' + result.stderr
                ran = subprocess.run([str(binary)], capture_output=True, text=True,
                                     timeout=15, env=dict(os.environ,
                                     ASAN_OPTIONS='detect_stack_use_after_return=1'))
                assert ran.returncode == 0 and ran.stdout == 'ok\n', name + '\n' + ran.stderr
            else:
                assert result.returncode != 0 and diagnostic in result.stderr, name + '\n' + result.stderr
                assert 'PLEASE submit' not in result.stderr, result.stderr
            print(opt, 'PCM' if imported else 'local', name, 'PASS', flush=True)
print('Indirect storage replacement: whole/field/nested/moved owners retain new borrows, release old origins and preserve permissions; local/PCM O0/O2 ASan/UBSan')
