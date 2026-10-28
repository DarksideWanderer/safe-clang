#!/usr/bin/env python3
"""Qualified parameter packs preserve scoped callable contracts and origins."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
API = '''
template<class T+> struct Box/(a){const T^/a value;};
template<class T> struct PlainBox/(a){const T^/a value;};
struct View/(a){const unsigned^/a value;};
template<class... Ts> using P=void /(a)(const Ts^/a...) safe;
template<class... Ts> using M=void /(a)(Ts^/a...) safe;
template<class... Ts> using S=void /(a where a:static)(const Ts^/a...) safe;
template<class... Ts> using C=void /(a,b)(const Box<Ts>/a^/b...) safe;
template<class... Ts> using V=void /(a)(Box<Ts>/a...) safe;
template<class... Ts> using PlainC=void /(a,b)(const PlainBox<Ts>/a^/b...) safe;
template<class... Ts> using PlainV=void /(a)(PlainBox<Ts>/a...) safe;
template<class... Ts> using R=const unsigned^/a /(a)(const Ts^/a...) safe;
template<class... Ts> using Tail=const unsigned^/b /(a,b where a:b)(const Ts^/a...,const unsigned^/b) safe;
const unsigned permanent=19u;
template<class... Ts> const unsigned^/a choose/(a)(const Ts^/a... values) safe {
 const unsigned^ result=^const permanent;((result=values),...);return result;
}
template<class... Ts> const unsigned^/a choose_box/(a,b)(const Box<Ts>/a^/b... values) safe {
 const unsigned^ result=^const permanent;((result=values->value),...);return result;
}
template<class... Ts> View/a choose_value/(a)(Box<Ts>/a... values) safe {
 const unsigned^ result=^const permanent;((result=values.value),...);return View{result};
}
template<class... Ts> const unsigned^/a choose_plain/(a)(PlainBox<Ts>/a... values) safe {
 const unsigned^ result=^const permanent;((result=values.value),...);return result;
}
template<class... Ts> const unsigned^/b static_tail/(a,b where a:static,b:a)
 (const Ts^/a... seeds,const unsigned^/b tail) safe {return tail;}
template<class... Ts> using StaticTail=const unsigned^/b /(a,b where a:static,b:a)
 (const Ts^/a...,const unsigned^/b) safe;
const unsigned^/static implied_static/(a,b where a:static,b:a)
 (const unsigned^/a seed,const unsigned^/b value) safe {return value;}
const unsigned^/static implied_class/(a,b,c where a:static,b:a)
 (const unsigned^/a seed,const PlainBox<unsigned>/b^/c value) safe {return value->value;}
struct StaticSink {
 StaticSink/(a,b where a:static,b:a)(const unsigned^/a seed,const unsigned^/b value) safe {}
};
void loose/(a,b where b:a)(const unsigned^/a first,const unsigned^/b second) safe {}
using Fixed=const unsigned^/static () safe;
'''
IDENTITIES = 0
for size in (0, 1, 2, 34):
    arguments = ','.join(['unsigned']*size)
    for name, result, binders, parameter in (
            ('P', 'void', 'a', 'const unsigned^/a'),
            ('M', 'void', 'a', 'unsigned^/a'),
            ('S', 'void', 'a where a:static', 'const unsigned^/a'),
            ('C', 'void', 'a,b', 'const Box<unsigned>/a^/b'),
            ('V', 'void', 'a', 'Box<unsigned>/a'),
            ('PlainC', 'void', 'a,b', 'const PlainBox<unsigned>/a^/b'),
            ('PlainV', 'void', 'a', 'PlainBox<unsigned>/a'),
            ('R', 'const unsigned^/a', 'a', 'const unsigned^/a')):
        parameters = ','.join([parameter]*size)
        binder = f'/({binders})' if size or name == 'R' else ''
        API += (f'using {name}{size}={name}<{arguments}>;'
                f'using E{name}{size}={result} {binder}({parameters}) safe;'
                f'static_assert(__is_same({name}{size},E{name}{size}));\n')
        IDENTITIES += 1
    # Removing a pack drops its binder and its edges, without leaving a
    # phantom input or losing the remaining input's result provenance.
    parameters = ','.join(['const unsigned^/a']*size+['const unsigned^/b'])
    binders = 'a,b where a:b' if size else 'b'
    API += (f'using T{size}=Tail<{arguments}>;'
            f'using ET{size}=const unsigned^/b /({binders})({parameters}) safe;'
            f'static_assert(__is_same(T{size},ET{size}));\n'
            f'static_assert(__is_same(decltype(choose<{arguments}>),R{size}));\n')
    IDENTITIES += 2
    for function, result, binders, parameter in (
            ('choose_box', 'const unsigned^/a', 'a,b', 'const Box<unsigned>/a^/b'),
            ('choose_value', 'View/a', 'a', 'Box<unsigned>/a'),
            ('choose_plain', 'const unsigned^/a', 'a', 'PlainBox<unsigned>/a')):
        parameters = ','.join([parameter]*size)
        # An empty class result remains generative, with its own binder.
        if not size:
            binders = 'a'
        API += (f'using E_{function}{size}={result} /({binders})({parameters}) safe;'
                f'static_assert(__is_same(decltype({function}<{arguments}>),E_{function}{size}));\n')
        IDENTITIES += 1

# A new specialization must have the same contract before and after any other
# use completes it. Checking only T+ parameters would hide this ordering bug.
API += '''
using Before=const unsigned^/a /(a)(PlainBox<char>/a) safe;
static_assert(sizeof(PlainBox<char>)>0);
using After=const unsigned^/a /(a)(PlainBox<char>/a) safe;
static_assert(__is_same(Before,After));
'''
IDENTITIES += 1

PROGRAM = '''
int main() safe {
 unsigned x=5u,y=7u;
 if(*choose<>()!=19u || *choose<unsigned>(^const x)!=5u)return 1;
 R2* callback=&choose<unsigned,unsigned>;
 if(*callback(^const x,^const y)!=7u)return 2;
 Box<unsigned> first{^const x},second{^const y};
 if(*choose_box<unsigned,unsigned>(^const first,^const second)!=7u)return 3;
 if(*choose_box<>()!=19u || *choose_value<>().value!=19u)return 4;
 if(*choose_value<unsigned,unsigned>(first,second).value!=7u)return 5;
 PlainBox<unsigned> plain_first{^const x},plain_second{^const y};
 if(*choose_plain<unsigned,unsigned>(plain_first,plain_second)!=7u)return 7;
 PlainBox<unsigned> permanent_view{^const permanent};
 if(*implied_static(^const permanent,^const permanent)!=19u)return 8;
 if(*implied_class(^const permanent,^const permanent_view)!=19u)return 9;
 StaticTail<>* static_callback=&static_tail<>;
 if(*static_callback(^const permanent)!=19u)return 10;
 StaticSink sink(^const permanent,^const permanent);
 loose(^const permanent,^const x);
'''
WIDE_TYPES = ','.join(['unsigned']*34)
WIDE_ARGS = ','.join(['^const x']*33+['^const y'])
PROGRAM += (f'R34* wide=&choose<{WIDE_TYPES}>;'
            f'if(*wide({WIDE_ARGS})!=7u)return 6;return 0;}}\n')


def main():
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
             '-fcircle-borrow-values', '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    count = 0
    with tempfile.TemporaryDirectory(prefix='higher-pack-') as temporary:
        directory = pathlib.Path(temporary)
        module, pcm, obj = [directory/name for name in ('packs.cppm', 'packs.pcm', 'packs.o')]
        source, binary = directory/'client.cpp', directory/'client'
        module.write_text('export module packs;\nexport {\n'+API+'}\n')
        imported = ['-fmodule-file=packs='+str(pcm)]

        def compile(options, okay=True):
            nonlocal count
            result = subprocess.run([str(CLANG)]+options, capture_output=True, text=True, timeout=120)
            assert (result.returncode == 0) == okay, (str(options)+'\n'+
                (source.read_text()[-900:] if source.exists() else '')+'\n'+result.stdout+result.stderr)
            if not okay:
                assert 'error:' in result.stderr and 'PLEASE submit' not in result.stderr, result.stderr
            count += 1

        compile(flags+['--precompile', str(module), '-o', str(pcm)])
        cases = [
            ('void good(R2* f) safe {R2* g=f;}', True),
            ('void bad(R0* f) unsafe {Fixed* g=f;}', False),
            ('void bad(Fixed* f) unsafe {R0* g=f;}', False),
            ('void bad(S2* f) unsafe {P2* g=f;}', False),
            ('void good(P2* f) safe {S2* g=f;}', True),
            ('unsigned bad() safe {unsigned x=1u;const unsigned^ saved;'
             '{unsigned y=2u;saved=choose<unsigned,unsigned>(^const x,^const y);}return *saved;}', False),
            ('unsigned bad() safe {unsigned x=1u;const unsigned^ saved;'
             '{unsigned y=2u;R2* f=&choose<unsigned,unsigned>;saved=f(^const x,^const y);}return *saved;}', False),
            ('unsigned bad() safe {const unsigned^ saved;{unsigned y=2u;Box<unsigned> box{^const y};'
             'saved=choose_box<unsigned>(^const box);}return *saved;}', False),
            ('unsigned bad() safe {const unsigned^ saved;{unsigned y=2u;Box<unsigned> box{^const y};'
             'saved=choose_value<unsigned>(box).value;}return *saved;}', False),
            ('unsigned bad() safe {const unsigned^ saved;{unsigned y=2u;PlainBox<unsigned> box{^const y};'
             'saved=choose_plain<unsigned>(box);}return *saved;}', False),
            (f'unsigned bad() safe {{unsigned x=1u;const unsigned^ saved;{{unsigned y=2u;'
             f'R34* f=&choose<{WIDE_TYPES}>;saved=f({WIDE_ARGS});}}return *saved;}}', False),
            ('void bad() safe {unsigned x=1u;S2* f=nullptr;f(^const x,^const x);}', False),
            ('void bad(P2** p) unsafe {auto q=reinterpret_cast<S2**>(p);}', False),
        ]
        # A removed static pack must not discard its incoming outlives edges.
        # Both the original graph and its instantiated graph require the
        # remaining region to be permanent, including in unsafe callers.
        for permission in ('safe', 'unsafe'):
            for body in (
                    'implied_static(^const permanent,^const local);',
                    'decltype(implied_static)* f=&implied_static;f(^const permanent,^const local);',
                    'static_tail<>(^const local);',
                    'StaticTail<>* f=&static_tail<>;f(^const local);',
                    'static_tail<unsigned>(^const permanent,^const local);',
                    'StaticSink sink(^const permanent,^const local);',
                    'PlainBox<unsigned> box{^const local};implied_class(^const permanent,^const box);',
                    'PlainBox<unsigned> box{^const local};decltype(implied_class)* f=&implied_class;'
                    'f(^const permanent,^const box);'):
                cases.append((f'void bad() {permission} {{unsigned local=1u;{body}}}', False))
        cases += [
            ('const PlainBox<unsigned>^/static bad/(a,b where a:static,b:a)'
             '(const unsigned^/a seed,PlainBox<unsigned>/b value) safe {return ^const value;}', False),
            ('const unsigned^ const^/static bad/(a,b where a:static,b:a)'
             '(const unsigned^/a seed,PlainBox<unsigned>/b value) safe {return ^const value.value;}', False),
        ]
        for use_pcm in (False, True):
            prefix = 'import packs;\n' if use_pcm else API
            for body, okay in cases:
                source.write_text(prefix+body)
                compile(flags+(imported if use_pcm else [])+['-fsyntax-only', str(source)], okay)
        for optimization in ('-O0', '-O2'):
            for sanitizer in ([], ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']):
                options = flags+[optimization]+sanitizer
                compile(options+['--precompile', str(module), '-o', str(pcm)])
                compile(options+['-c', str(pcm), '-o', str(obj)])
                for use_pcm in (False, True):
                    source.write_text(('import packs;\n' if use_pcm else API)+PROGRAM)
                    compile(options+(imported if use_pcm else [])+[str(source)]+
                            ([str(obj)] if use_pcm else [])+['-o', str(binary)])
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                    assert result.returncode == 0, result.stderr+str(result.returncode)
    print(f'Qualified callable packs: {2*IDENTITIES} local/PCM type identities, {count} compilations; '
          'zero/one/two/34 elements, borrow/class projections, static constraints, generative empty '
          'results, escaping-source and mutable-storage refusals; 8 O0/O2 plain ASan/UBSan runs passed')


if __name__ == '__main__':
    main()
