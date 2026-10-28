#!/usr/bin/env python3
"""A class value carrying several regions borrows each field from its own region.

`Pair/a/b build/(a,b)(const unsigned^/a x, const unsigned^/b y)` binds one
region per field, so the fields are tracked separately: swapping or duplicating
a region is refused, a field may still be reached through an alias of the
matching owner, a live value keeps both owners borrowed, and the contract
survives a producer PCM.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'

API = "\n".join([
    'struct Pair/(a,b) {',
    '  const unsigned^/a first;',
    '  const unsigned^/b second;',
    '};',
    'Pair/a/b build/(a,b)(const unsigned^/a x, const unsigned^/b y) safe {',
    '  return Pair{x, y};',
    '}',
    # The field follows the borrow's source, so an alias of the parameter that
    # owns its region still satisfies the field's contract.
    'Pair/a/b build_alias/(a,b)(const unsigned^/a x, const unsigned^/b y) safe {',
    '  const unsigned^ first = x;',
    '  return Pair{first, y};',
    '}',
    'unsigned sum(Pair/a/b value) safe { return *value.first + *value.second; }',
    'Pair/a/b shorten/(a,b,x,y where x:a,y:b)(const unsigned^/x x, const unsigned^/y y) safe {',
    '  return Pair{x, y};',
    '}',
    'Pair/a/b shorten_transitive/(a,b,x,y,m,n where x:m,m:a,y:n,n:b)(',
    ' const unsigned^/x x, const unsigned^/y y) safe {return Pair{x,y};}',
    'Pair/x/y forward/(x,y)(Pair/x/y input) safe {return rel input;}',
    'Pair/x/y forward_short/(a,b,x,y where a:x,b:y)(Pair/a/b input,',
    ' const unsigned^/x first, const unsigned^/y second) safe {return rel input;}',
    'Pair/y/x reverse/(x,y)(Pair/x/y input) safe {return Pair{input.second,input.first};}',
    'using Forward=decltype(forward);',
    'Forward* select_forward() safe {return &forward;}',
    'const unsigned^/x first/(x,y)(Pair/x/y input) safe {return input.first;}',
    'using First=decltype(first);',
    'First* select_first() safe {return &first;}',
    ''])
PROGRAM = "\n".join([
    'unsigned run() safe {',
    '  unsigned x = 1u, y = 2u;',
    '  auto pair = build(^const x, ^const y);',
    '  if (*pair.first != 1u || *pair.second != 2u) return 1u;',
    '  if (sum(pair) != 3u) return 2u;',
    '  { auto shorter = shorten(^const x, ^const y);',
    '    if (sum(shorter) != 3u) return 5u; }',
    '  { auto shorter = shorten_transitive(^const x, ^const y);',
    '    if (sum(shorter) != 3u) return 6u; }',
    '  { auto value=forward(build(^const x,^const y));',
    '    if (sum(value)!=3u) return 7u; }',
    '  { auto value=select_forward()(build(^const x,^const y));',
    '    if (sum(value)!=3u) return 8u; }',
    '  { auto value=reverse(build(^const x,^const y));',
    '    if (*value.first!=2u || *value.second!=1u) return 9u; }',
    '  { auto value=forward_short(build(^const x,^const y),^const x,^const y);',
    '    if (sum(value)!=3u) return 10u; }',
    '  { unsigned a=3u,b=4u;auto value=select_first()(build(^const a,^const b));',
    '    b=5u;if (*value!=3u) return 11u; }',
    '  { auto swapped = build(^const y, ^const x);',
    '    if (*swapped.first != 2u || *swapped.second != 1u) return 3u; }',
    '  { auto aliased = build_alias(^const x, ^const y);',
    '    if (*aliased.first != 1u || *aliased.second != 2u) return 4u; }',
    '  return 0u;',
    '}',
    ''])
ENTRY = 'int main() safe { return static_cast<int>(run()); }\n'
FIELD_REFUSALS = [
    ('const unsigned^/x bad/(x,y)(Pair/x/y input) safe {return input.second;}',
     'returned reference does not borrow from the declared lifetime source'),
    ('Pair/x/y bad/(x,y)(Pair/x/y input) safe {return Pair{input.second,input.first};}',
     'class-value result field does not borrow from the parameter bound to its region'),
    ('Pair/x/y bad/(a,b,x,y where x:a,y:b)(Pair/a/b input) safe {return rel input;}',
     'class-value result field does not borrow from the parameter bound to its region'),
    ('Pair/a/b bad/(a,b,x,y where a:x,b:y)(const unsigned^/x x, const unsigned^/y y) safe {return Pair{x,y};}',
     'class-value result field does not borrow from the parameter bound to its region'),
    ('Pair/a/b bad/(a,b,x,y where x:a,y:b)(const unsigned^/x x, const unsigned^/y y) safe {return Pair{y,x};}',
     'class-value result field does not borrow from the parameter bound to its region'),
    # Each field must come from the parameter bound to its own region.
    ('Pair/a/b bad/(a,b)(const unsigned^/a x, const unsigned^/b y) unsafe { return Pair{y, x}; }',
     'class-value result field does not borrow from the parameter bound to its region'),
    ('Pair/a/b bad/(a,b)(const unsigned^/a x, const unsigned^/b y) unsafe { return Pair{x, x}; }',
     'class-value result field does not borrow from the parameter bound to its region'),
    # An alias does not launder a region: this one borrows the other owner.
    ('Pair/a/b bad/(a,b)(const unsigned^/a x, const unsigned^/b y) safe {'
     ' const unsigned^ alias = y; return Pair{alias, y}; }',
     'class-value result field does not borrow from the parameter bound to its region'),
    # A field may not be sourced from storage that dies with the callee.
    ('Pair/a/b bad/(a,b)(const unsigned^/a x, const unsigned^/b y) safe {'
     ' unsigned local = 1u; const unsigned^ alias = ^const local; return Pair{alias, y}; }',
     'class-value result field does not borrow from the parameter bound to its region'),
]
LIVE_REFUSALS = [
    ('unsigned bad() safe {unsigned x=1u,y=2u;auto value=select_first()(build(^const x,^const y));'
     ' x=5u;return *value;}',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe {unsigned x=1u,y=2u;auto pair=select_forward()(build(^const x,^const y));'
     ' x=5u;return *pair.first;}',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe {unsigned x=1u,y=2u;auto pair=reverse(build(^const x,^const y));'
     ' y=5u;return *pair.first;}',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe {unsigned x=1u,y=2u;auto pair=shorten(^const x,^const y);'
     ' x=5u;return *pair.first;}',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe {unsigned x=1u,y=2u;auto pair=shorten_transitive(^const x,^const y);'
     ' y=5u;return *pair.second;}',
     'mutation conflicts with a live borrow'),
    # Both owners stay borrowed while the value is live.
    ('unsigned bad(/*live*/) safe { unsigned x = 1u, y = 2u; auto pair = build(^const x, ^const y);'
     ' x = 5u; return *pair.first; }',
     'mutation conflicts with a live borrow'),
    ('unsigned bad() safe { unsigned x = 1u, y = 2u; auto pair = build(^const x, ^const y);'
     ' y = 6u; return *pair.second; }',
     'mutation conflicts with a live borrow'),
]
LEAK_REFUSALS = [
    ('Pair/x/y bad/(x,y)(Pair/x/y input) safe {auto first=rel input;return rel input;}',
     'use of a relocated object'),
    ('Pair/x/y bad/(x,y)(Pair/x/y input) safe {unsigned local=1u;'
     ' return Pair{^const local,input.second};}',
     'class-value result field does not borrow from the parameter bound to its region'),
    ('Pair/x/y bad/(x,y)(Pair/x/y input) safe {unsigned local=1u;'
     ' return select_forward()(build(^const local,input.second));}',
     'class-value result field does not borrow from the parameter bound to its region'),
    # A field of a local value cannot outlive it.
    ('const unsigned^ leak() safe { unsigned x = 1u, y = 2u; auto pair = build(^const x, ^const y);'
     ' return pair.first; }',
     'returned borrow has unknown lifetime provenance'),
]
REFUSALS = FIELD_REFUSALS + LIVE_REFUSALS + LEAK_REFUSALS


def compile_consumer(flags, text, extra=()):
    source = tmp/'consumer.cpp'
    source.write_text(text)
    return subprocess.run([str(clang)]+flags+list(extra)+['-fsyntax-only', str(source)],
                          capture_output=True, text=True)


with tempfile.TemporaryDirectory(prefix='multi-region-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'pair_api': 'safe'}}))
    common = ['--driver-mode=g++', '-std=c++20', '-fmodule-safety-policy='+str(policy),
              '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    local = common + ['-fcircle-safety', '-fcircle-borrow-values']
    # The module unit is written in the native borrow model, so the producer
    # compiles it the same way the local case does; the importing consumer
    # only needs the module-safety mode to read the recorded contract.
    producer = common + ['-fcircle-safety', '-fcircle-borrow-values']
    checked = common + ['-fmodule-safe']
    # A local definition, compiled and run.
    for opt in ('-O0', '-O2'):
        for sanitized in (False, True):
            options = local + [opt] + (['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
                                       if sanitized else [])
            source = tmp/'main.cpp'
            source.write_text(API + PROGRAM + ENTRY)
            binary = tmp/'run'
            result = subprocess.run([str(clang)]+options+[str(source), '-o', str(binary)],
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            executed = subprocess.run([str(binary)], capture_output=True, text=True)
            assert executed.returncode == 0, (executed.returncode, executed.stderr)
    # The producer keeps the contract, and the importing consumer honours it.
    module = tmp/'api.cppm'
    module.write_text('export module pair_api;\nexport {\n'+API+'\n}\n')
    pcm = tmp/'api.pcm'
    result = subprocess.run([str(clang)]+producer+['--precompile', str(module), '-o', str(pcm)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(clang)]+producer+['-c', str(pcm), '-o', str(tmp/'api.o')],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    imported = ['-fmodule-file=pair_api='+str(pcm)]
    # The module-safety-only consumer accepts the imported value and still
    # refuses to mutate an owner the imported contract keeps borrowed. It has
    # no borrow values, so the two live-borrow cases are the ones its object
    # model can spell.
    assert compile_consumer(checked, 'import pair_api;\n'+PROGRAM, imported).returncode == 0
    for body, diagnostic in LIVE_REFUSALS:
        result = compile_consumer(checked, 'import pair_api;\n'+body, imported)
        assert result.returncode != 0 and diagnostic in result.stderr, (body, result.stderr)
        assert 'PLEASE submit' not in result.stderr, result.stderr
    # In the borrow model the imported consumer links against the module and
    # runs, so the contract is a property of the PCM rather than of the text.
    for opt in ('-O0', '-O2'):
        for sanitized in (False, True):
            options = local + [opt] + (['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
                                       if sanitized else [])
            source = tmp/'imported.cpp'
            source.write_text('import pair_api;\n'+PROGRAM+ENTRY)
            binary = tmp/'run-imported'
            result = subprocess.run([str(clang)]+options+imported+[str(source), str(tmp/'api.o'),
                                                                  '-o', str(binary)],
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            executed = subprocess.run([str(binary)], capture_output=True, text=True)
            assert executed.returncode == 0, (executed.returncode, executed.stderr)
    for body, diagnostic in REFUSALS:
        expected = compile_consumer(local, API + body)
        assert expected.returncode != 0 and diagnostic in expected.stderr, (body, expected.stderr)
        imported_case = compile_consumer(local, 'import pair_api;\n'+body, imported)
        assert imported_case.returncode != 0 and diagnostic in imported_case.stderr, \
            (body, imported_case.stderr)
        assert 'PLEASE submit' not in imported_case.stderr, imported_case.stderr
        assert 'PLEASE submit' not in expected.stderr, expected.stderr
print('Multi-region class values: per-field regions and alias sourcing across local/PCM '
      'O0/O2 plain ASan/UBSan, {} refusals passed'.format(len(REFUSALS)))
