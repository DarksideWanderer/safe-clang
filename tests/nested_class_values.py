#!/usr/bin/env python3
"""A class value nested inside a class value projects its own regions.

`struct Outer/(a) { Inner/a inner; }` binds the nested record's region to the
enclosing record's `a`, so a borrow read through the nested value follows the
owner of that region: the projection survives three levels, copies, relocation
and a producer PCM, while a field sourced from another region is refused.
Dependent T+ carriers defer arity to substitution and preserve separate regions
in module-only consumers, including static payloads without permanent storage.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'

API = "\n".join([
    'struct Inner/(a) { const unsigned^/a value; };',
    'struct Outer/(a) { Inner/a inner; };',
    'struct Leaf/(a) { const unsigned^/a value; };',
    'struct Mid/(a) { Leaf/a leaf; };',
    'struct Deep/(a) { Mid/a mid; };',
    'struct Pair2/(a,b) { Inner/a first; Inner/b second; };',
    'struct Tagged/(a) {Inner/a data;unsigned tag;};',
    # The nested field names the enclosing region, so the projection resolves
    # through the enclosing record rather than by spelling.
    'struct Mapped/(a,b) { Inner/b first; Inner/a second; };',
    'template<class T+> struct Wrapper {T value;unsigned tag=1u;};',
    'template<class T+> Wrapper<T>/x/y relay_generic/(x,y)(Wrapper<T>/x/y input) safe {',
    ' return rel input;}',
    'template<class T+> const unsigned^/static leak_parameter_storage(Wrapper<T>/static/static input) safe {',
    ' return ^const input.tag;}',
    'template<class T+> const unsigned^/x first_generic/(x,y)(Wrapper<T>/x/y input) safe {',
    ' return input.value.first.value;}',
    'const unsigned permanent_first=7u,permanent_second=8u;',
    'template<class T+> Wrapper<T>/static/static static_generic(Wrapper<T>/static/static input) safe {',
    ' return rel input;}',
    'Outer/a make/(a)(const unsigned^/a x) safe { return Outer{Inner{x}}; }',
    'Outer/a relay/(a)(Outer/a input) safe { return rel input; }',
    'const unsigned^/a leaf/(a)(Outer/a input) safe { return input.inner.value; }',
    'unsigned sum(Outer/a input) safe { return *input.inner.value; }',
    'unsigned inspect_tag/(a)(Tagged/a input) safe {auto tag=^const input.tag;return *tag;}',
    # A nested value built from the parameter keeps its source, so an inner
    # local value still projects the parameter's region.
    'Outer/a through/(a)(const unsigned^/a x) safe { Inner inner{x}; return Outer{inner}; }',
    'Deep/a make_deep/(a)(const unsigned^/a x) safe { return Deep{Mid{Leaf{x}}}; }',
    'unsigned sum_deep(Deep/a input) safe { return *input.mid.leaf.value; }',
    'Pair2/a/b make_pair/(a,b)(const unsigned^/a x, const unsigned^/b y) safe {',
    '  return Pair2{Inner{x}, Inner{y}};',
    '}',
    'unsigned sum_pair(Pair2/a/b input) safe {',
    '  return *input.first.value + *input.second.value;',
    '}',
    'Pair2/x/y relay_pair/(x,y)(Pair2/x/y input) safe {return rel input;}',
    'template<unsigned N> Pair2/x/y relay_template/(x,y)(Pair2/x/y input) safe {return rel input;}',
    'Mapped/x/y relay_mapped/(x,y)(Mapped/x/y input) safe {return rel input;}',
    'Mapped/a/b make_mapped/(a,b)(const unsigned^/a x, const unsigned^/b y) safe {',
    '  return Mapped{Inner{y}, Inner{x}};',
    '}',
    'unsigned sum_mapped(Mapped/a/b input) safe {',
    '  return *input.first.value * 10u + *input.second.value;',
    '}',
    ''])
PROGRAM = "\n".join([
    'unsigned run() safe {',
    '  unsigned x = 1u, y = 2u, z = 3u;',
    '  auto outer = make(^const x);',
    '  if (*outer.inner.value != 1u) return 1u;',
    '  if (sum(outer) != 1u) return 2u;',
    '  if (*leaf(outer) != 1u) return 3u;',
    '  if (*through(^const x).inner.value != 1u) return 10u;',
    '  if (inspect_tag(Tagged{Inner{^const x},9u}) != 9u) return 18u;',
    # A copy and a relocation carry the same projection.
    '  { auto copied = outer; if (*copied.inner.value != 1u) return 4u;',
    '    auto moved = rel copied; if (sum(moved) != 1u) return 5u; }',
    '  { auto relayed = relay(rel outer); if (*relayed.inner.value != 1u) return 6u; }',
    '  { auto deep = make_deep(^const z); if (sum_deep(deep) != 3u) return 7u; }',
    '  { auto pair = make_pair(^const x, ^const y); if (sum_pair(pair) != 3u) return 8u; }',
    '  { auto pair=relay_pair(make_pair(^const x,^const y));',
    '    if (sum_pair(pair)!=3u) return 11u; }',
    '  { auto pair=relay_template<1>(make_pair(^const x,^const y));',
    '    if (sum_pair(pair)!=3u) return 12u; }',
    '  { auto mapped=relay_mapped(make_mapped(^const x,^const y));',
    '    if (sum_mapped(mapped)!=21u) return 13u; }',
    '  { Wrapper<Pair2> input{make_pair(^const x,^const y)};',
    '    auto value=relay_generic(rel input);',
    '    if (sum_pair(value.value)!=3u) return 14u; }',
    '  { Wrapper<Mapped> input{make_mapped(^const x,^const y)};',
    '    auto value=relay_generic(rel input);',
    '    if (sum_mapped(value.value)!=21u) return 15u; }',
    '  { unsigned a=4u,b=5u;Wrapper<Pair2> input{make_pair(^const a,^const b)};',
    '    auto value=first_generic(rel input);b=6u;',
    '    if (*value!=4u) return 16u; }',
    '  { Wrapper<Pair2> input{Pair2{Inner{^const permanent_first},Inner{^const permanent_second}}};',
    '    auto value=static_generic(rel input);',
    '    if (sum_pair(value.value)!=15u) return 17u; }',
    # The nested field names the enclosing record\'s second region, so the
    # fields are sourced the other way round.
    '  { auto mapped = make_mapped(^const x, ^const y);',
    '    if (sum_mapped(mapped) != 21u) return 9u; }',
    '  return 0u;',
    '}',
    ''])
ENTRY = 'int main() safe { return static_cast<int>(run()); }\n'
FIELD_REFUSALS = [
    ('const unsigned^/a bad/(a)(Tagged/a input) safe {return ^const input.tag;}',
     'returned reference does not borrow from the declared lifetime source'),
    ('const unsigned^/a bad/(a)(Tagged/a input) unsafe {return ^const input.tag;}',
     'returned reference does not borrow from the declared lifetime source'),
    ('const unsigned^/a bad/(a)(Tagged/a input) safe {auto alias=^const input.tag;return alias;}',
     'returned reference does not borrow from the declared lifetime source'),
    ('void bad() safe {unsigned x=1u,y=2u;Wrapper<Mapped> input{make_mapped(^const x,^const y)};'
     ' auto value=first_generic(rel input);}',
     'returned reference does not borrow from the declared lifetime source'),
    ('template<class T+> Wrapper<T>/x/y swapped/(x,y)(Wrapper<T>/x/y input) safe {'
     ' return Wrapper<T>{T{input.value.second,input.value.first}};}'
     ' void bad() safe {unsigned x=1u,y=2u;Wrapper<Pair2> input{make_pair(^const x,^const y)};'
     ' auto value=swapped(rel input);}',
     'class-value result field does not borrow from the parameter bound to its region'),
    ('Pair2/x/y bad/(x,y)(Pair2/x/y input) safe {'
     ' return Pair2{input.second,input.first};}',
     'class-value result field does not borrow from the parameter bound to its region'),
    ('Mapped/x/y bad/(x,y)(Mapped/x/y input) safe {'
     ' return Mapped{input.second,input.first};}',
     'class-value result field does not borrow from the parameter bound to its region'),
    # The nested fields swap the regions their types declare.
    ('Pair2/a/b bad/(a,b)(const unsigned^/a x, const unsigned^/b y) unsafe {'
     ' return Pair2{Inner{y}, Inner{x}}; }',
     'class-value result field does not borrow from the parameter bound to its region'),
    # A remapped field still has to come from the parameter of that region.
    ('Mapped/a/b bad/(a,b)(const unsigned^/a x, const unsigned^/b y) unsafe {'
     ' return Mapped{Inner{x}, Inner{y}}; }',
     'class-value result field does not borrow from the parameter bound to its region'),
    # A nested field may not be sourced from storage that dies with the callee.
    ('Pair2/a/b bad/(a,b)(const unsigned^/a x, const unsigned^/b y) unsafe {'
     ' unsigned local = 1u; return Pair2{Inner{x}, Inner{^const local}}; }',
     'class-value result field does not borrow from the parameter bound to its region'),
    # A field borrowing from the region of one level cannot satisfy another.
    ('Pair2/a/b bad/(a,b)(const unsigned^/a x, const unsigned^/b y) unsafe {'
     ' return Pair2{Inner{x}, Inner{x}}; }',
     'class-value result field does not borrow from the parameter bound to its region'),
]
LIVE_REFUSALS = [
    ('unsigned bad() safe {'
     ' Wrapper<Pair2> input{Pair2{Inner{^const permanent_first},Inner{^const permanent_second}}};'
     ' auto value=leak_parameter_storage(rel input);return *value;}',
     'static return lifetime contract requires permanent non-thread-local borrow origins'),
    ('unsigned bad() safe {unsigned x=1u,y=2u;Wrapper<Pair2> input{make_pair(^const x,^const y)};'
     ' auto value=first_generic(rel input);x=6u;return *value;}',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe {unsigned x=1u,y=2u;Wrapper<Pair2> input{make_pair(^const x,^const y)};'
     ' auto value=relay_generic(rel input);y=6u;return *value.value.second.value;}',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe {unsigned x=1u,y=2u;'
     ' auto pair=relay_template<1>(make_pair(^const x,^const y));'
     ' y=6u;return *pair.second.value;}',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe { unsigned x = 1u; auto outer = make(^const x); x = 5u;'
     ' return *outer.inner.value; }',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe { unsigned x = 1u, y = 2u; auto pair = make_pair(^const x, ^const y);'
     ' y = 6u; return *pair.second.value; }',
     'mutation conflicts with a live borrow'),
]
LEAK_REFUSALS = [
    ('const unsigned^/static bad() safe {'
     ' Wrapper<Pair2> input{Pair2{Inner{^const permanent_first},Inner{^const permanent_second}}};'
     ' auto value=static_generic(rel input);return ^const value.tag;}',
     'static return lifetime contract requires permanent non-thread-local borrow origins'),
    ('const unsigned^ leak() safe { unsigned x = 1u; auto outer = make(^const x);'
     ' return outer.inner.value; }',
     'returned borrow has unknown lifetime provenance'),
    # A single-region nested result may not be sourced from a local either.
    ('Outer/a bad/(a)(const unsigned^/a x) unsafe { unsigned local = 1u;'
     ' Inner inner{^const local}; return Outer{inner}; }',
     'returned reference does not borrow from the declared lifetime source'),
]
# Nested shapes this subset does not model are refused where the field is
# declared, not silently accepted.
SHAPE_REFUSALS = [
    ('void bad() safe {unsigned x=1u,y=2u;Wrapper<Pair2> input{make_pair(^const x,^const y)};'
     ' auto value=static_generic(rel input);}',
     'static lifetime contract requires permanent non-thread-local borrow origins'),
    ('void bad() safe {Wrapper<unsigned> input{1u};auto value=relay_generic(rel input);}',
     'class lifetime argument count mismatch: expected 0, got 2'),
    ('template<class T> struct Declared/(a) {const T^/a value;};'
     ' template<class T> void bad/(x,y)(Declared<T>/x/y input) safe;',
     'class lifetime argument count mismatch: expected 1, got 2'),
    ('void bad() safe {unsigned x=1u;Wrapper<Inner> input{Inner{^const x}};'
     ' auto value=relay_generic(rel input);}',
     'class lifetime argument count mismatch: expected 1, got 2'),
    ('struct Bad/(a) { Inner/static inner; };',
     'borrow value fields require class lifetime parameters'),
    ('struct Bad/(a) { Inner/zzz inner; };',
     'borrow value fields require class lifetime parameters'),
    ('struct Wide/(a,b) { const unsigned^/a first; const unsigned^/b second; };'
     'struct Bad/(a,b) { Wide/a/b inner; };',
     'borrow value fields require class lifetime parameters'),
]
REFUSALS = FIELD_REFUSALS + LIVE_REFUSALS + LEAK_REFUSALS + SHAPE_REFUSALS


def compile_source(flags, text, extra=()):
    source = tmp/'consumer.cpp'
    source.write_text(text)
    return subprocess.run([str(clang)]+flags+list(extra)+['-fsyntax-only', str(source)],
                          capture_output=True, text=True)


with tempfile.TemporaryDirectory(prefix='nested-class-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'nested_api': 'safe'}}))
    common = ['--driver-mode=g++', '-std=c++20', '-fmodule-safety-policy='+str(policy),
              '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    model = common + ['-fcircle-safety', '-fcircle-borrow-values']
    # The module unit is written in the native borrow model, so the producer
    # compiles it the same way the local case does.
    producer = model
    # A consumer that only enables the module-safety mode still reads the
    # projection off the imported declarations.
    checked = common + ['-fmodule-safe']
    # A local definition, compiled and run.
    for opt in ('-O0', '-O2'):
        for sanitized in (False, True):
            options = model + [opt] + (['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
                                       if sanitized else [])
            source = tmp/'main.cpp'
            source.write_text(API + PROGRAM + ENTRY)
            binary = tmp/'run'
            result = subprocess.run([str(clang)]+options+[str(source), '-o', str(binary)],
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            executed = subprocess.run([str(binary)], capture_output=True, text=True)
            assert executed.returncode == 0, (executed.returncode, executed.stderr)
    # The producer keeps the projection, and the importing consumers honour it.
    module = tmp/'api.cppm'
    module.write_text('export module nested_api;\nexport {\n'+API+'\n}\n')
    pcm = tmp/'api.pcm'
    object = tmp/'api.o'
    result = subprocess.run([str(clang)]+producer+['--precompile', str(module), '-o', str(pcm)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(clang)]+producer+['-c', str(pcm), '-o', str(object)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    imported = ['-fmodule-file=nested_api='+str(pcm)]
    # The module-safety-only consumer accepts an imported nested value and
    # still refuses to mutate an owner the contract keeps borrowed.
    result = compile_source(checked, 'import nested_api;\n'+PROGRAM, imported)
    assert result.returncode == 0, result.stderr
    for body, diagnostic in LIVE_REFUSALS:
        result = compile_source(checked, 'import nested_api;\n'+body, imported)
        assert result.returncode != 0 and diagnostic in result.stderr, (body, result.stderr)
        assert 'PLEASE submit' not in result.stderr, result.stderr
    # In the borrow model the imported consumer links against the module and
    # runs, so the projection is a property of the PCM rather than of the text.
    for opt in ('-O2',):
        for sanitized in (False, True):
            options = model + [opt] + (['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
                                       if sanitized else [])
            source = tmp/'imported.cpp'
            source.write_text('import nested_api;\n'+PROGRAM+ENTRY)
            binary = tmp/'run-imported'
            result = subprocess.run([str(clang)]+options+imported+[str(source), str(object),
                                                                  '-o', str(binary)],
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            executed = subprocess.run([str(binary)], capture_output=True, text=True)
            assert executed.returncode == 0, (executed.returncode, executed.stderr)
    for body, diagnostic in REFUSALS:
        expected = compile_source(model, API + body)
        assert expected.returncode != 0 and diagnostic in expected.stderr, (body, expected.stderr)
        assert 'PLEASE submit' not in expected.stderr, expected.stderr
        imported_case = compile_source(model, 'import nested_api;\n'+body, imported)
        assert imported_case.returncode != 0 and diagnostic in imported_case.stderr, \
            (body, imported_case.stderr)
        assert 'PLEASE submit' not in imported_case.stderr, imported_case.stderr
print('Nested class values: two and three levels, T+ arity and scoped/static projections, '
      'copies, relocation and remapped regions '
      'across local/PCM O0/O2 plain ASan/UBSan, {} refusals passed'.format(len(REFUSALS)))
