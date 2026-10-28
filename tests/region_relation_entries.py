#!/usr/bin/env python3
"""One contract matrix for declarations, overrides, impls and conversions.

Diagnostics run once per source/PCM entry. Execution alone uses optimization
and sanitizer configurations. Declaration identity stays exact; conversions
separately check directional substitutability.
"""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
# name, expected equivalence, required signature, supplied signature.
# A signature consists of result, binder, named value parameters.
PARAMS = 'const unsigned^/a x,const unsigned^/b y'
CASES = [
    ('alpha', True, ('void', 'a,b where a:b', PARAMS),
     ('void', 'x,y where x:y', 'const unsigned^/x x,const unsigned^/y y')),
    ('closure', True, ('void', 'a,b where a:b', PARAMS),
     ('void', 'a,m,b where a:m,m:b', PARAMS)),
    ('equivalent_regions', True, ('void', 'a,b where a:b,b:a', PARAMS),
     ('void', 'x', 'const unsigned^/x x,const unsigned^/x y')),
    ('reverse', False, ('void', 'a,b where a:b', PARAMS),
     ('void', 'a,b where b:a', PARAMS)),
    ('erasure', False, ('void', 'a,b where a:b', PARAMS), ('void', 'a,b', PARAMS)),
    ('return_source', False, ('const unsigned^/a', 'a,b', PARAMS),
     ('const unsigned^/b', 'a,b', PARAMS)),
    ('static_parameter', False, ('void', '', 'const unsigned^/static x'),
     ('void', '', 'const unsigned^ x')),
    ('static_result', False, ('const unsigned^/static', '', ''),
     ('const unsigned^/a', 'a', '')),
    ('class_projection', False,
     ('void', 'a,b,c where a:b', 'View/b^/c target,const unsigned^/a input'),
     ('void', 'a,b,c where b:a', 'View/b^/c target,const unsigned^/a input')),
    ('mixed_static', False, ('void', 'b,c', 'const Pair/static/b^/c input'),
     ('void', 'b,c', 'const Pair/b/static^/c input')),
]


def signature(spec, name, receiver=False):
    result, binder, params = spec
    if receiver:
        names, separator, constraints = binder.partition(' where ')
        binder = (names+',' if names else '')+'receiver'
        if separator:
            binder += ' where '+constraints
        params = 'const self^/receiver'+(','+params if params else '')
    return result+' '+name+('/('+binder+')' if binder else '')+'('+params+') safe'


def alias(spec, name):
    result, binder, params = spec
    return ('using '+name+'='+result+' __attribute__((safe_function)) '+
            ('/('+binder+')' if binder else '')+'('+params+');\n')


API = 'struct View/(a){const unsigned^/a value;};\n'
API += 'struct Pair/(a,b){View/a first;View/b second;};\n'
for name, valid, want, have in CASES:
    API += alias(want, 'Want_'+name)+alias(have, 'Have_'+name)
    API += signature(want, 'decl_'+name)+';\n'
    API += 'struct Base_'+name+'{virtual '+signature(want, 'apply')+'=0;};\n'
    API += 'interface I_'+name+'{'+signature(want, 'apply', True)+';};\n'
    API += 'struct V_'+name+'{};\n'

CALL_API = '''
void replace/(a,b,c where a:b)(View/b^/c target,const unsigned^/a input) safe {
 target->value=input;
}
void replace_transitive/(a,m,b,c where a:m,m:b)(
 View/b^/c target,const unsigned^/a input) safe {target->value=input;}
using Setter=decltype(replace);
Setter* select() safe {return &replace_transitive;}
template<class T> void generic/(a,b,c where a:b)(
 View/b^/c target,const T^/a input) safe {replace(target,input);}
const unsigned permanent=17u;
unsigned inspect(const View/static^ input) safe {return *input->value;}
using Inspector=decltype(inspect);
Inspector* select_inspector() safe {return &inspect;}
interface Change {
 void set/(a,b,c,r where a:b)(const self^/r,View/b^/c target,
 const unsigned^/a input) safe;
};
struct Agent{};
impl Agent:Change {
 void set/(x,m,y,z,r where x:m,m:y)(const self^/r,View/y^/z target,
 const unsigned^/x input) safe override {replace(target,input);}
};
void dispatched/(a,b,c,r where a:b)(const Agent^/r agent,View/b^/c target,
 const unsigned^/a input) safe {agent.Change::set(target,input);}
interface Produce {typename result_type;result_type view(const self^) safe;};
struct Producer {unsigned value;};
impl Producer:Produce {
 using result_type=View;
 result_type view(const self^) safe override {return View{^const self->value};}
};
struct Poly {Poly() safe {} virtual ~Poly() safe {}};
struct Child:Poly {unsigned value=9u;Child() safe {}};
'''
PROGRAM = '''int main() safe {
 unsigned a=1u,b=2u;View target{^const a};Agent agent{};
 replace(^target,^const b);if(*target.value!=2u)return 1;
 select()(^target,^const a);if(*target.value!=1u)return 2;
 generic(^target,^const b);if(*target.value!=2u)return 3;
 dispatched(^const agent,^target,^const a);if(*target.value!=1u)return 4;
 Producer producer{23u};auto view=producer.Produce::view();
 if(*view.value!=23u)return 6;
 Child child{};if(child.value!=9u)return 7;
 View static_view{^const permanent};
 return inspect(^const static_view)==17u &&
        select_inspector()(^const static_view)==17u?0:5;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='region-relation-entries-') as directory:
        d = pathlib.Path(directory)
        common = ['--driver-mode=g++', '-std=c++20',
                  '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
        native = common+['-fcircle-safety', '-fcircle-borrow-values']
        source, module, pcm, obj = d/'client.cpp', d/'api.cppm', d/'api.pcm', d/'api.o'

        def check(flags, okay=True, diagnostic=''):
            result = subprocess.run([str(CLANG)]+flags, text=True,
                                    capture_output=True, timeout=120)
            assert (result.returncode == 0) == okay, result.stderr+'\n'+(
                source.read_text() if source.exists() else module.read_text())
            assert 'PLEASE submit' not in result.stderr, result.stderr
            if diagnostic:
                assert diagnostic in result.stderr, result.stderr

        module.write_text('export module region_relations;\nexport {\n'+API+CALL_API+'}\n')
        check(native+['--precompile', str(module), '-o', str(pcm)])
        imports = ['-fmodule-file=region_relations='+str(pcm)]
        count = 0
        for name, valid, want, have in CASES:
            entries = {
                'redeclare': signature(have, 'decl_'+name)+';',
                'override': 'struct Derived_'+name+':Base_'+name+'{'+
                            signature(have, 'apply')+' override;};',
                'impl': 'impl V_'+name+':I_'+name+'{'+
                        signature(have, 'apply', True)+' override;};',
                'conversion': 'void convert(Have_'+name+'* source) unsafe {'+
                              'auto result=reinterpret_cast<Want_'+name+'*>(source);}',
                'implicit_conversion': 'void convert(Have_'+name+'* source) unsafe {'+
                              'Want_'+name+'* result=source;}',
            }
            for entry, body in entries.items():
                # A callable with independent/shared durations can serve a
                # constrained target without acquiring the target's identity.
                accepted = valid or (entry in ('conversion', 'implicit_conversion')
                                     and name in ('reverse', 'erasure', 'static_parameter',
                                                  'class_projection'))
                for imported in (False, True):
                    source.write_text(('module region_relations;\n' if imported else API)+body)
                    check(native+(imports if imported else [])+
                          ['-fsyntax-only', str(source)], accepted)
                    count += 1
            source.write_text('import region_relations;\nstatic_assert(__is_same(Want_'+
                              name+',Have_'+name+')=='+str(valid).lower()+');')
            check(common+['-fmodule-safe']+imports+['-fsyntax-only', str(source)])

        # The same actual lifetime relation is checked at every call entry,
        # including unsafe callers. These diagnostics do not depend on -O.
        for call in ('replace(^target,^const short_data)',
                     'select()(^target,^const short_data)',
                     'generic(^target,^const short_data)',
                     'dispatched(^const agent,^target,^const short_data)'):
            for effect in ('safe', 'unsafe'):
                body = ('void bad() '+effect+' {unsigned long_data=1u;Agent agent{};'
                        'View target{^const long_data};{unsigned short_data=2u;'+
                        call+';}unsigned read=*target.value;}')
                for imported in (False, True):
                    source.write_text(('import region_relations;\n' if imported else API+CALL_API)+body)
                    check(native+(imports if imported else [])+['-fsyntax-only', str(source)],
                          False, 'mutable class argument does not preserve its lifetime region')

        # Callback storage and nested callbacks retain the complete contract.
        extra = [
            ('struct DtorBase {DtorBase() safe {}virtual ~DtorBase() safe {}};'
             'struct UnsafePart {~UnsafePart() unsafe {}};'
             'struct DtorDerived:DtorBase {UnsafePart part;DtorDerived() safe {}};'
             'void bad() safe {DtorDerived value;}', False),
            ('struct UnsafeOverride:Base_alpha {'+
             signature(CASES[0][2], 'apply').removesuffix('safe')+'unsafe override;};', False),
            ('interface Assoc {typename value;value get(const self^) safe;};'
             'struct AssocOwner {};impl AssocOwner:Assoc {using value=View;'
             'View/static get(const self^) safe override;};', False),
            ('void bad(Want_reverse** source) unsafe {void* p=reinterpret_cast<void*>(source);}', False),
            ('void good(Want_reverse** source) unsafe {auto p=reinterpret_cast<Want_reverse**>(source);}', True),
            ('void bad(Have_return_source* unsafe source) unsafe {auto p=reinterpret_cast<Want_return_source*>(source);}', False),
            ('void bad(Have_return_source* source) unsafe {auto p=(Want_return_source*)source;}', False),
            ('void bad(Have_return_source* source) unsafe {auto p=__builtin_bit_cast(Want_return_source*,source);}', False),
            ('void bad(Have_return_source* source) unsafe {Want_return_source& p=reinterpret_cast<Want_return_source&>(*source);}', False),
            ('using X=void(Want_return_source*);using Y=void(Have_return_source*);'
             'void bad(X* source) unsafe {auto p=reinterpret_cast<Y*>(source);}', False),
            ('using X=Want_return_source*();using Y=Have_return_source*();'
             'void bad(X* source) unsafe {auto p=reinterpret_cast<Y*>(source);}', False),
            ('using X=void(Want_static_result*);using Y=void(Have_static_result*);'
             'void bad(X* source) unsafe {auto p=reinterpret_cast<Y*>(source);}', False),
        ]
        for body, valid in extra:
            for imported in (False, True):
                source.write_text(('import region_relations;\n' if imported else API)+body)
                check(native+(imports if imported else [])+['-fsyntax-only', str(source)], valid)

        for opt in ('-O0', '-O2'):
            for sanitized in (False, True):
                options = native+[opt]+(['-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all'] if sanitized else [])
                check(options+['--precompile', str(module), '-o', str(pcm)])
                check(options+['-c', str(pcm), '-o', str(obj)])
                for imported in (False, True):
                    source.write_text(('import region_relations;\n' if imported else API+CALL_API)+PROGRAM)
                    binary = d/'run'
                    check(options+(imports if imported else [])+[str(source)]+
                          ([str(obj)] if imported else [])+['-o', str(binary)])
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                    assert result.returncode == 0, result.stderr+str(result.returncode)
    print(f'Region relation entries: {len(CASES)} shared rules, {count} local/PCM '
          'declaration/override/impl/explicit+implicit conversion checks; imported '
          'type identity, direct/indirect/template/impl caller contracts and '
          'nested/storage callback refusals; O0/O2 plain ASan/UBSan execution passed')


if __name__ == '__main__':
    main()
