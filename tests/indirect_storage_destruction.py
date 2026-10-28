"""Custom drops cannot read expired indirect payloads, including EH cleanup."""
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
DECLARATIONS = '''struct Store {std2::vector<std2::string_view> values;
 Store() safe {} ~Store() safe {std2::println(*values[0]);}};
struct Wrapper {Store store; Wrapper() safe {}};
'''
PREFIX = '#feature on safety\n#include <std2.h>\n' + DECLARATIONS
PRELUDE = ''.join('#include <' + name + '>\n' for name in
                  ('cstdio', 'memory', 'thread', 'mutex', 'shared_mutex', 'new',
                   'cstring', 'atomic', 'string'))
CASES = [
    ('nested_element_expired', False, '''int main() safe {
 std2::vector<std2::vector<Store>> outer;
 {const char text[]={'n','o'};Store store;std2::vector<Store> inner;
 store.values^.push_back(std2::string_view(text));inner^.push_back(rel store);
 outer^.push_back(rel inner);}}
'''),
    ('field_replacement_live', True, '''int main() safe {
 const char text[]={'o','k'};Wrapper value;
 value.store.values^.push_back(std2::string_view(text));Store source;
 source.values^.push_back(std2::string_view(text));value.store := rel source;return 0;}
'''),
    ('field_replacement_expired', False, '''int main() safe {Wrapper value;
 {const char text[]={'n','o'};value.store.values^.push_back(std2::string_view(text));}
 Store source;source.values^.push_back(std2::string_view("ok"));
 value.store := rel source;}
'''),
    ('nested_drop_only_expired', True, '''int main() safe {
 std2::vector<std2::vector<std2::string_view>> values;
 {const char text[]={'n','o'};std2::vector<std2::string_view> inner;
 inner^.push_back(std2::string_view(text));values^.push_back(rel inner);}
 return 0;}
'''),
    ('container_element_live', True, '''int main() safe {
 const char text[]={'o','k'};std2::vector<Store> stores;
 {Store store;store.values^.push_back(std2::string_view(text));
 stores^.push_back(rel store);}return 0;}
'''),
    ('container_element_expired', False, '''int main() safe {
 std2::vector<Store> stores;
 {const char text[]={'n','o'};Store store;
 store.values^.push_back(std2::string_view(text));stores^.push_back(rel store);}}
'''),
    ('drop_live', True, '''int main() safe {const char text[]={'o','k'};
 Store store;store.values^.push_back(std2::string_view(text));return 0;}
'''),
    ('drop_expired', False, '''int main() safe {Store store;
 {const char text[]={'n','o'};store.values^.push_back(std2::string_view(text));}}
'''),
    ('implicit_nested_live', True, '''int main() safe {const char text[]={'o','k'};
 Wrapper value;value.store.values^.push_back(std2::string_view(text));return 0;}
'''),
    ('implicit_nested_expired', False, '''int main() safe {Wrapper value;
 {const char text[]={'n','o'};value.store.values^.push_back(std2::string_view(text));}}
'''),
    ('exception_live', True, '''int main() safe {const char text[]={'o','k'};
 try {Store store;store.values^.push_back(std2::string_view(text));throw 7;}
 catch(int n) {return n==7?0:1;}}
'''),
    ('exception_expired', False, '''int main() safe {
 try {Store store;
 {const char text[]={'n','o'};store.values^.push_back(std2::string_view(text));}
 throw 7;}catch(int) {return 0;}}
'''),
    ('replacement_expired', False, '''int main() safe {Store store;
 {const char text[]={'n','o'};store.values^.push_back(std2::string_view(text));}
 Store source;source.values^.push_back(std2::string_view("ok"));
 store := rel source;}
'''),
]
with tempfile.TemporaryDirectory(prefix='indirect-storage-destruction-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'destruction_api': 'safe'}}))
    flags = FLAGS + ['-fmodule-safety-policy=' + str(policy)]
    for opt in ('-O0', '-O2'):
        options = [*flags, opt, '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        module = tmp / 'api.cppm'
        pcm = tmp / 'api.pcm'
        obj = tmp / 'api.o'
        module.write_text('module;\n' + PRELUDE +
                          'export module destruction_api;\nexport {\n#include <std2.h>\n' +
                          DECLARATIONS + '}\n')
        for arguments in (['--precompile', str(module), '-o', str(pcm)],
                          ['-c', str(pcm), '-o', str(obj)]):
            built = subprocess.run([str(CLANG), *options, *arguments],
                                   capture_output=True, text=True, timeout=120)
            assert built.returncode == 0, built.stderr
        for imported, name, valid, body in (
                (imported, *case) for imported in (False, True) for case in CASES):
            source = tmp / (name + '.cpp')
            prefix = '#feature on safety\nimport destruction_api;\n' if imported else PREFIX
            source.write_text(prefix + body)
            imports = ['-fmodule-file=destruction_api=' + str(pcm)] if imported else []
            binary = tmp / name
            result = subprocess.run([str(CLANG), *options, *imports, str(source),
                                     *([str(obj)] if imported else []), '-o', str(binary)],
                                    capture_output=True, text=True, timeout=120)
            if valid:
                assert result.returncode == 0, name + '\n' + result.stderr
                ran = subprocess.run([str(binary)], capture_output=True, text=True,
                                     timeout=15, env=dict(os.environ,
                                     ASAN_OPTIONS='detect_stack_use_after_return=1'))
                output = ('' if name == 'nested_drop_only_expired' else
                          'ok\nok\n' if name == 'field_replacement_live' else 'ok\n')
                assert ran.returncode == 0 and ran.stdout == output, name + '\n' + ran.stderr
            else:
                assert result.returncode != 0 and (
                    'dropping a borrow-carrying object requires drop_only' in result.stderr), name + '\n' + result.stderr
                assert 'PLEASE submit' not in result.stderr, result.stderr
            print(opt, 'PCM' if imported else 'local', name, 'PASS', flush=True)
print('Indirect storage destruction: explicit/implicit-nested/EH/replacement drops check payload liveness; local/PCM O0/O2 ASan/UBSan')
