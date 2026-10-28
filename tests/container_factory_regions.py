"""Borrow-carrying official containers returned through checked APIs and PCMs."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'
PREFIX = '#feature on safety\n#include <std2.h>\n'
PRELUDE = ''.join('#include <' + name + '>\n' for name in
                  ('cstdio', 'memory', 'thread', 'mutex', 'shared_mutex', 'new',
                   'cstring', 'atomic', 'string'))
API = '''
export std2::vector<std2::string_view>/a empty/(a)(std2::string_view/a input) safe {
 std2::vector<std2::string_view> result;return rel result;
}
export std2::vector<std2::string_view>/a make/(a)(std2::string_view/a input) safe {
 std2::vector<std2::string_view> result;
 result^.push_back(input);return rel result;
}
export std2::vector<std2::string_view>/a forward/(a)(std2::vector<std2::string_view>/a input) safe {
 return rel input;
}
export std2::string_view/a extract_first/(a)(std2::vector<std2::string_view>/a input) safe {
 return std2::string_view(*input[0]);
}
export using Factory=std2::vector<std2::string_view>/a /(a)(std2::string_view/a) safe;
'''
MAIN = '''int main() safe {
 const char text[]={'o','k'};
 auto blank=empty(std2::string_view(text));if(blank.size()!=0)return 1;
 auto first=make(std2::string_view(text));
 auto second=forward(rel first);
 std2::println(*second[0]);
 Factory* callback=&make;
 auto third=callback(std2::string_view(text));
 std2::println(*third[0]);
 auto extracted=extract_first(rel third);std2::println(extracted);
 std2::string_view copy="ok";
 {auto temporary=make(std2::string_view(text));
 copy := std2::string_view(*temporary[0]);}
 std2::println(copy);return 0;
}
'''
NEGATIVES = [
 ('''std2::vector<std2::string_view>/a bad/(a)(std2::string_view/a input) safe {
 const char local[]={'n','o'};std2::vector<std2::string_view> result;
 result^.push_back(std2::string_view(local));return rel result;}
''', 'does not borrow from'),
 ('''int main() safe {std2::vector<std2::string_view> result;
 {const char text[]={'n','o'};result := make(std2::string_view(text));}
 std2::println(*result[0]);}
''', 'borrow outlives its owner'),
 ('''int main() safe {std2::string_view result="ok";
 {const char text[]={'n','o'};auto values=make(std2::string_view(text));
 result := extract_first(rel values);}
 std2::println(result);}
''', 'borrow outlives its owner'),
 ('''std2::vector<std2::string_view>/a bad/(a)(std2::string_view/a input) unsafe {
 const char local[]={'n','o'};std2::vector<std2::string_view> result;
 result^.push_back(std2::string_view(local));return rel result;}
''', 'does not borrow from'),
 ('''int main() safe {std2::vector<std2::string_view> result;
 Factory* callback=&make;
 {const char text[]={'n','o'};result := callback(std2::string_view(text));}
 std2::println(*result[0]);}
''', 'borrow outlives its owner'),
]

with tempfile.TemporaryDirectory(prefix='container-factory-regions-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'container_factory': 'safe'}}))
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
             '-fcircle-borrow-values', '-Wno-everything',
             '-I' + str(ROOT / 'downloads/safe-cpp-reference/libsafecxx/single-header'),
             '-fmodule-safety-policy=' + str(policy),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    def compile(arguments, okay=True, diagnostic=''):
        result = subprocess.run([str(CLANG)] + arguments, text=True,
                                capture_output=True, timeout=120)
        assert (result.returncode == 0) == okay, result.stderr
        assert 'PLEASE submit' not in result.stderr, result.stderr
        assert diagnostic in result.stderr, result.stderr

    for opt in ('-O0', '-O2'):
        options = flags + [opt, '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        module = tmp / 'api.cppm'
        pcm = tmp / 'api.pcm'
        obj = tmp / 'api.o'
        source = tmp / 'client.cpp'
        exe = tmp / 'run'
        module.write_text('module;\n' + PRELUDE +
                          'export module container_factory;\n'
                          'export {\n#include <std2.h>\n}\n' + API)
        compile(options + ['--precompile', str(module), '-o', str(pcm)])
        compile(options + ['-c', str(pcm), '-o', str(obj)])
        for imported in (False, True):
            prefix = ('#feature on safety\nimport container_factory;\n' if imported
                      else PREFIX + API.replace('export ', ''))
            imports = ['-fmodule-file=container_factory=' + str(pcm)] if imported else []
            source.write_text(prefix + MAIN)
            compile(options + imports + [str(source)] + ([str(obj)] if imported else []) + ['-o', str(exe)])
            ran = subprocess.run([str(exe)], text=True, capture_output=True, timeout=30,
                                 env=dict(os.environ, ASAN_OPTIONS='detect_stack_use_after_return=1'))
            assert ran.returncode == 0 and ran.stdout == 'ok\nok\nok\nok\n', ran.stderr + ran.stdout
            for body, diagnostic in NEGATIVES:
                source.write_text(prefix + body)
                compile(options + imports + ['-fsyntax-only', str(source)], False, diagnostic)
print(f'Official container factories: direct/indirect/forwarded results and copied elements run; local/PCM O0/O2 ASan/UBSan, {4 * len(NEGATIVES)} contract/lifetime refusals')
