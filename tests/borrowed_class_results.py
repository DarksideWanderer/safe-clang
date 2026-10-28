#!/usr/bin/env python3
"""Carried data regions survive a shorter borrow of their class carrier."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
API = '''struct View/(a) {const unsigned^/a value;};
struct Pair/(a,b) {View/a first;View/b second;unsigned tag=1u;};
template<class T+> struct Wrapper {T value;};
struct UnsafeCopy {
 unsigned value=0u;
 UnsafeCopy() safe =default;
 UnsafeCopy(const UnsafeCopy&) unsafe =default;
};
template<class T> T copy_any(const T^ input) safe {return *input;}
const unsigned permanent=19u;
const unsigned^/a first/(a,b,c)(const Pair/a/b^/c input) safe {
 return input->first.value;
}
View/a copy_view/(a,c)(const View/a^/c input) safe {return View{input->value};}
Pair/a/b clone/(a,b,c)(const Pair/a/b^/c input) safe {return *input;}
Pair/b/a reverse/(a,b,c)(const Pair/a/b^/c input) safe {
 return Pair{input->second,input->first};
}
Pair/x/y shorten/(a,b,c,x,y where a:x,b:y)(const Pair/a/b^/c input) safe {
 return Pair{input->first,input->second};
}
template<class T+> Wrapper<T>/a/b clone_nested/(a,b,c)(
 const Wrapper<T>/a/b^/c input) safe {return *input;}
template<class T+> const unsigned^/a first_nested/(a,b,c)(
 const Wrapper<T>/a/b^/c input) safe {return input->value.first.value;}
Pair/static/b mixed/(b,c)(const View/b^/c input) safe {
 return Pair{View{^const permanent},View{input->value}};
}
Pair/static/b mixed_forward/(b,c)(const Pair/static/b^/c input) safe {
 return *input;
}
using First=decltype(first);
using Clone=decltype(clone);
using Mixed=decltype(mixed);
First* select_first() safe {return &first;}
Clone* select_clone() safe {return &clone;}
Mixed* select_mixed() safe {return &mixed;}
'''
PROGRAM = '''unsigned run() safe {
 unsigned a=3u,b=5u;
 auto selected=^const a;
 {Pair carrier{View{^const a},View{^const b}};
  selected=select_first()(^const carrier);}
 b=6u;if(*selected!=3u)return 1u;
 {Pair carrier{View{^const a},View{^const b}};
  auto value=select_clone()(^const carrier);
  auto swapped=reverse(^const carrier);
  auto shorter=shorten(^const carrier);
  if(*value.first.value!=3u || *value.second.value!=6u ||
     *swapped.first.value!=6u || *swapped.second.value!=3u ||
     *shorter.first.value!=3u || *shorter.second.value!=6u)return 2u;}
 {View carrier{^const a};auto value=copy_view(^const carrier);
  if(*value.value!=3u)return 3u;}
 {Wrapper<Pair> carrier{Pair{View{^const a},View{^const b}}};
  auto value=clone_nested(^const carrier);auto loan=first_nested(^const carrier);
  if(*value.value.first.value!=3u || *value.value.second.value!=6u ||
     *loan!=3u)return 4u;}
 {View carrier{^const b};auto value=select_mixed()(^const carrier);
  auto forwarded=mixed_forward(^const value);
  if(*value.first.value!=19u || *value.second.value!=6u ||
     *forwarded.first.value!=19u || *forwarded.second.value!=6u)return 5u;}
 return 0u;
}
int main() safe {return static_cast<int>(run());}
'''
BODY_REFUSALS = [
 ('const unsigned^/a wrong/(a,b,c)(const Pair/a/b^/c input) safe {'
  'return input->second.value;}', 'returned reference does not borrow from the declared lifetime source'),
 ('const unsigned^/a wrong/(a,b,c)(const Pair/a/b^/c input) safe {'
  'return ^const input->tag;}', 'returned reference does not borrow from the declared lifetime source'),
 ('Pair/a/b wrong/(a,b,c)(const Pair/a/b^/c input) safe {'
  'return Pair{input->second,input->first};}',
  'class-value result field does not borrow from the parameter bound to its region'),
 ('Pair/static/b wrong/(b,c)(const View/b^/c input) unsafe {'
  'return Pair{View{input->value},View{input->value}};}',
  'class-value result field does not borrow from the parameter bound to its region'),
]
CALL_REFUSALS = [
 ('void wrong() safe {Wrapper<UnsafeCopy> value{};auto copied=copy_any(^const value);}',
  'unsafe or unclassified'),
 ('void wrong() safe {unsigned a=1u,b=2u;Pair carrier{View{^const a},View{^const b}};'
  'auto value=select_first()(^const carrier);a=3u;unsigned read=*value;}',
  'mutation conflicts with a live borrow'),
 ('void wrong() safe {unsigned a=1u,b=2u;Pair carrier{View{^const a},View{^const b}};'
  'auto value=select_clone()(^const carrier);b=3u;unsigned read=*value.second.value;}',
  'mutation conflicts with a live borrow'),
 ('void wrong() safe {unsigned a=1u;View carrier{^const a};'
  'auto value=select_mixed()(^const carrier);a=3u;unsigned read=*value.second.value;}',
  'mutation conflicts with a live borrow'),
 ('void wrong() safe {unsigned a=1u,b=2u;Pair carrier{View{^const a},View{^const b}};'
  'auto value=mixed_forward(^const carrier);}',
  'static class argument requires permanent lifetime regions'),
 ('void wrong() safe {unsigned a=1u;auto value=^const a;'
  '{unsigned b=2u;Pair carrier{View{^const b},View{^const a}};'
  'value=select_first()(^const carrier);}unsigned read=*value;}',
  'borrow outlives its owner'),
]


def main():
    with tempfile.TemporaryDirectory(prefix='circle-borrowed-class-results-') as directory:
        d = pathlib.Path(directory)
        common = ['--driver-mode=g++', '-std=c++20',
                  '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
        native = common + ['-fcircle-safety', '-fcircle-borrow-values']
        checked = common + ['-fmodule-safe']

        def check(args, okay=True, diagnostic=''):
            result = subprocess.run([str(CLANG)]+args, text=True,
                                    capture_output=True, timeout=120)
            assert (result.returncode == 0) == okay, result.stderr
            assert 'PLEASE submit' not in result.stderr, result.stderr
            if diagnostic:
                assert diagnostic in result.stderr, result.stderr

        module = d/'api.cppm'
        module.write_text('export module borrowed_class_results;\nexport {\n'+API+'}\n')
        source = d/'client.cpp'
        for opt in ('-O0', '-O2'):
            for sanitized in (False, True):
                options = native + [opt]
                if sanitized:
                    options += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
                pcm, obj, binary = d/'api.pcm', d/'api.o', d/'run'
                check(options+['--precompile', str(module), '-o', str(pcm)])
                check(options+['-c', str(pcm), '-o', str(obj)])
                imports = ['-fmodule-file=borrowed_class_results='+str(pcm)]
                for imported in (False, True):
                    source.write_text(('import borrowed_class_results;\n' if imported else API)+PROGRAM)
                    check(options+(imports if imported else [])+[str(source)]+
                          ([str(obj)] if imported else [])+['-o', str(binary)])
                    result = subprocess.run([str(binary)], capture_output=True,
                                            text=True, timeout=30)
                    assert result.returncode == 0, result.stderr+str(result.returncode)
        # Diagnostic rules do not depend on optimization; run each negative
        # once per relevant source/PCM entry point.
        for body, diagnostic in BODY_REFUSALS+CALL_REFUSALS:
            for imported in (False, True):
                source.write_text(('import borrowed_class_results;\n' if imported else API)+body)
                check(native+(imports if imported else [])+
                      ['-fsyntax-only', str(source)], False, diagnostic)
        # An auto variable initialized with the reference-mode ^const spelling
        # has that mode's value semantics. Obtain this handle from the imported
        # API instead, so the consumer exercises the PCM's native destination.
        module_only_program = PROGRAM.replace('auto selected=^const a;',
            'auto selected=copy_view(View{^const a}).value;')
        source.write_text('import borrowed_class_results;\n'+module_only_program)
        check(checked+imports+['-fsyntax-only', str(source)])
        # Conversion to an imported borrow must also use the native ABI.
        pcm, obj = d/'module-only.pcm', d/'module-only.o'
        check(native+['-O0', '--precompile', str(module), '-o', str(pcm)])
        check(native+['-O0', '-c', str(pcm), '-o', str(obj)])
        imports = ['-fmodule-file=borrowed_class_results='+str(pcm)]
        check(checked+['-O0']+imports+[str(source), str(obj), '-o', str(binary)])
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr+str(result.returncode)
        for body, diagnostic in CALL_REFUSALS:
            body = body.replace('auto value=^const a;',
                'auto value=copy_view(View{^const a}).value;')
            source.write_text('import borrowed_class_results;\n'+body)
            check(checked+imports+['-fsyntax-only', str(source)], False, diagnostic)
    print('Borrowed class carriers: shared data projections, direct/indirect and T+ '
          'returns, remapping/shortening, mixed static leaves, local/PCM O0/O2 '
          'plain ASan/UBSan and module-only O0 ABI; carrier-independent loans '
          'and 10 refusal cases passed')


if __name__ == '__main__':
    main()
