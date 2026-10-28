"""Constructor and aggregate values retain indirect payload origins, not slots."""
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
DECLARATIONS = '''using Views=std2::vector<std2::string_view>;
struct Store {Views values; Store(Views input) safe : values(rel input) {}};
struct Aggregate {Views values;};
struct Derived : Store {Derived(Views input) safe : Store(rel input) {}};
struct Delegated {Views values;
 Delegated(Views input) safe : values(rel input) {}
 Delegated(Views input,unsigned) safe : Delegated(rel input) {}};
template<class T> struct Holder {std2::vector<T> values;
 Holder(std2::vector<T> input) safe : values(rel input) {}};
struct ExclusivePair {std2::vector<unsigned^> first,second;
 ExclusivePair() safe {}
 ExclusivePair(std2::vector<unsigned^> a,std2::vector<unsigned^> b) safe
 : first(rel a),second(rel b) {}};
struct BodyStore/(a) {Views/a values;
 BodyStore(std2::string_view/a input) safe {
 for(unsigned i=0;i<2;++i) values^.push_back(input);}};
struct BodyExclusive/(a) {std2::vector<unsigned^>/a values;
 BodyExclusive(unsigned^/a input) safe {values^.push_back(input);}};
struct BodyAlias/(a) {Views/a values;
 BodyAlias(std2::string_view/a input) safe {
 auto target=^values;target->push_back(input);}};
'''
PREFIX = '#feature on safety\n#include <std2.h>\n' + DECLARATIONS
PRELUDE = ''.join('#include <' + name + '>\n' for name in
                  ('cstdio', 'memory', 'thread', 'mutex', 'shared_mutex', 'new',
                   'cstring', 'atomic', 'string'))
CASES = []
for kind, type_name, initializer in (
        ('member', 'Store', 'Store(rel input)'),
        ('aggregate', 'Aggregate', 'Aggregate{rel input}'),
        ('base', 'Derived', 'Derived(rel input)'),
        ('delegating', 'Delegated', 'Delegated(rel input,0u)'),
        ('template', 'Holder<std2::string_view>', 'Holder<std2::string_view>(rel input)')):
    initial = initializer.replace('input', 'empty')
    for live in (True, False):
        data = "const char text[]={'o','k'};"
        body = ('int main() safe {' + (data if live else '') +
                'Views empty;auto result=' + initial + ';{' + ('' if live else data) +
                'Views input;input^.push_back(std2::string_view(text));result := ' + initializer +
                ';}std2::println(*result.values[0]);return 0;}')
        CASES.append((kind + ('_live' if live else '_expired'), live, body,
                      '' if live else 'borrow outlives its owner'))
CASES.extend([
    ('body_live', True, '''int main() safe {const char text[]={'o','k'};
 BodyStore value{std2::string_view(text)};std2::println(*value.values[0]);return 0;}
''', ''),
    ('body_alias_live', True, '''int main() safe {const char text[]={'o','k'};
 BodyAlias value{std2::string_view(text)};std2::println(*value.values[0]);return 0;}
''', ''),
    ('body_expired', False, '''int main() safe {BodyStore value{std2::string_view("ok")};
 {const char text[]={'n','o'};value := BodyStore{std2::string_view(text)};}
 std2::println(*value.values[0]);}
''', 'borrow outlives its owner'),
    ('body_retained_permission', False, '''int main() safe {char text[]={'o','k'};
 BodyStore value{std2::string_view(text)};text[0]='n';std2::println(*value.values[0]);}
''', 'mutation conflicts with a live borrow'),
    ('body_local_escape', False, '''struct LocalStore/(a) {Views/a values;
 LocalStore(std2::string_view/a input) safe {const char local[]={'n','o'};
 values^.push_back(std2::string_view(local));}};
 int main() safe {LocalStore value{std2::string_view("ok")};
 std2::println(*value.values[0]);}
''', 'class field lifetime contract does not preserve its declared region'),
    ('body_alias_local_escape', False, '''struct AliasStore/(a) {Views/a values;
 AliasStore(std2::string_view/a input) safe {const char local[]={'n','o'};
 auto target=^values;target->push_back(std2::string_view(local));}};
 int main() safe {AliasStore value{std2::string_view("ok")};
 std2::println(*value.values[0]);}
''', 'class field lifetime contract does not preserve its declared region'),
    ('body_wrong_region', False, '''struct WrongStore/(a,b) {Views/a values;
 WrongStore(std2::string_view/a first,std2::string_view/b second) safe {
 values^.push_back(second);}};
 int main() safe {WrongStore value{std2::string_view("ok"),std2::string_view("no")};
 std2::println(*value.values[0]);}
''', 'class field lifetime contract does not preserve its declared region'),
    ('body_uninitialized_member', False, '''struct EarlyStore/(a) {
 unsigned marker;Views/a values;
 EarlyStore(std2::string_view/a input) safe
 : marker((values^.push_back(input),0u)) {}};
 int main() safe {EarlyStore value{std2::string_view("ok")};
 std2::println(*value.values[0]);}
''', 'constructor member storage is not initialized'),
    ('body_exclusive_live', True, '''int main() safe {unsigned a=1;
 BodyExclusive value{^a};**value.values[0]=3;std2::println("ok");return 0;}
''', ''),
    ('body_exclusive_conflict', False, '''int main() safe {unsigned a=1;
 BodyExclusive value{^a};std2::println(a);**value.values[0]=3;}
''', 'access conflicts with a live exclusive borrow'),
    ('empty_exclusive_pair', True, '''int main() safe {ExclusivePair value;
 std2::println("ok");return 0;}
''', ''),
    ('disjoint_exclusive_pair', True, '''int main() safe {unsigned a=1,b=2;
 std2::vector<unsigned^> first,second;first^.push_back(^a);second^.push_back(^b);
 ExclusivePair value(rel first,rel second);
 **value.first[0]=3;**value.second[0]=4;std2::println("ok");return 0;}
''', ''),
    ('overlapping_exclusive_pair', False, '''int main() safe {unsigned a=1;
 std2::vector<unsigned^> first,second;first^.push_back(^a);second^.push_back(^a);
 ExclusivePair value(rel first,rel second);**value.first[0]=3;**value.second[0]=4;}
''', 'conflicts with a live'),
    ('copied_view_live', True, '''int main() safe {const char text[]={'o','k'};
 std2::string_view copy="ok";
 {Views input;input^.push_back(std2::string_view(text));Store value(rel input);
 copy := std2::string_view(*value.values[0]);}std2::println(copy);return 0;}
''', ''),
    ('copied_view_expired', False, '''int main() safe {std2::string_view copy="ok";
 {const char text[]={'n','o'};Views input;input^.push_back(std2::string_view(text));
 Store value(rel input);copy := std2::string_view(*value.values[0]);}
 std2::println(copy);}
''', 'borrow outlives its owner'),
    ('retained_permission', False, '''int main() safe {char text[]={'o','k'};
 Views input;input^.push_back(std2::string_view(text));Store value(rel input);
 text[0]='n';std2::println(*value.values[0]);}
''', 'mutation conflicts with a live borrow'),
])

with tempfile.TemporaryDirectory(prefix='indirect-storage-construction-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'construction_api': 'safe'}}))
    flags = FLAGS + ['-fmodule-safety-policy=' + str(policy)]
    for opt in ('-O0', '-O2'):
        options = [*flags, opt, '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        module = tmp / 'api.cppm'
        pcm = tmp / 'api.pcm'
        obj = tmp / 'api.o'
        module.write_text('module;\n' + PRELUDE +
                          'export module construction_api;\nexport {\n#include <std2.h>\n' +
                          DECLARATIONS + '}\n')
        for arguments in (['--precompile', str(module), '-o', str(pcm)],
                          ['-c', str(pcm), '-o', str(obj)]):
            built = subprocess.run([str(CLANG), *options, *arguments],
                                   capture_output=True, text=True, timeout=120)
            assert built.returncode == 0, built.stderr
        for imported, name, valid, body, diagnostic in (
                (imported, *case) for imported in (False, True) for case in CASES):
            source = tmp / (name + '.cpp')
            prefix = '#feature on safety\nimport construction_api;\n' if imported else PREFIX
            source.write_text(prefix + body)
            imports = ['-fmodule-file=construction_api=' + str(pcm)] if imported else []
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
print('Indirect storage construction: member/base/delegating/template/aggregate provenance, copied views and permissions; local/PCM O0/O2 ASan/UBSan')
