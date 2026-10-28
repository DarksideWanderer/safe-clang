#!/usr/bin/env python3
"""Scoped callable substitution, variance and mutable-storage boundaries."""
import os
import pathlib
import re
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
API = '''
struct View/(a){const unsigned^/a value;};
struct Slot/(a,b){View/a^/b view;};
struct ReadSlot/(a,b){const View/a^/b view;};
struct Cell/(a){View/a data;View/a* get(const self^) safe;};
using First=const unsigned^/a __attribute__((safe_function)) /(a,b)(const unsigned^/a,const unsigned^/b);
using Second=const unsigned^/b __attribute__((safe_function)) /(a,b)(const unsigned^/a,const unsigned^/b);
using Tied=const unsigned^/a __attribute__((safe_function)) /(a)(const unsigned^/a,const unsigned^/a);
using Short=const unsigned^/b __attribute__((safe_function)) /(a,b where a:b)(const unsigned^/a,const unsigned^/b);
using Static=const unsigned^/static __attribute__((safe_function)) (const unsigned^/static,const unsigned^/static);
using StaticKind=void /(where a: static)(const unsigned^/a) safe;
using AnyKind=void /(a)(const unsigned^/a) safe;
using StaticEdge=void /(a,b where a: static,b:a)(const unsigned^/a,const unsigned^/b) safe;
using StaticFree=void /(a,b where a: static)(const unsigned^/a,const unsigned^/b) safe;
using Single=const unsigned^/a /(a)(const unsigned^/a) safe;
using StaticResultLoose=const unsigned^/static (const unsigned^) safe;
using FirstThrow=const unsigned^/a __attribute__((safe_function)) /(a,b)(const unsigned^/a,const unsigned^/b) noexcept;
using UnsafeFirst=const unsigned^/a /(a,b)(const unsigned^/a,const unsigned^/b) unsafe;
using ConsumerFirst=unsigned __attribute__((safe_function)) (First*);
using ConsumerTied=unsigned __attribute__((safe_function)) (Tied*);
using OuterFirst=unsigned __attribute__((safe_function)) (ConsumerFirst*);
using OuterTied=unsigned __attribute__((safe_function)) (ConsumerTied*);
using FactoryFirst=First* () safe;
using FactoryTied=Tied* () safe;
using StoreFirst=void __attribute__((safe_function)) (First**);
using StoreTied=void __attribute__((safe_function)) (Tied**);
using ReadStoreFirst=void __attribute__((safe_function)) (First*const*);
using ReadStoreTied=void __attribute__((safe_function)) (Tied*const*);
using SharedTied=void __attribute__((safe_function)) /(a,c)(const View/a^/c,const unsigned^/a);
using SharedFree=void __attribute__((safe_function)) /(a,b,c)(const View/b^/c,const unsigned^/a);
using MutTied=void __attribute__((safe_function)) /(a,c)(View/a^/c,const unsigned^/a);
using MutFree=void __attribute__((safe_function)) /(a,b,c)(View/b^/c,const unsigned^/a);
using SlotTied=void __attribute__((safe_function)) /(a,s,c)(const Slot/a/s^/c,const unsigned^/a);
using SlotFree=void __attribute__((safe_function)) /(a,b,s,c)(const Slot/b/s^/c,const unsigned^/a);
using ReadTied=void __attribute__((safe_function)) /(a,s,c)(const ReadSlot/a/s^/c,const unsigned^/a);
using ReadFree=void __attribute__((safe_function)) /(a,b,s,c)(const ReadSlot/b/s^/c,const unsigned^/a);
using CellTied=void __attribute__((safe_function)) /(a,c)(const Cell/a^/c,const unsigned^/a);
using CellFree=void __attribute__((safe_function)) /(a,b,c)(const Cell/b^/c,const unsigned^/a);
View/a clone/(a,b,c)(const View/a^/c,const unsigned^/b) safe;
View/b short_clone/(a,b,c where a:b)(const View/a^/c,const unsigned^/b) safe;
using Clone=decltype(clone);
using ShortClone=decltype(short_clone);
const unsigned^/a unsafe_first/(a,b)(const unsigned^/a,const unsigned^/b) unsafe;
static_assert(__is_same(UnsafeFirst,decltype(unsafe_first)));
const unsigned^/a first/(a,b)(const unsigned^/a x,const unsigned^/b y) safe {return x;}
unsigned consume_tied(Tied* f) safe {unsigned a=3u,b=5u;return *f(^const a,^const b);}
First* factory() safe {return &first;}
template<class From,class To> To* adapt(From* f) safe {return f;}
using NativeReadFirst=unsigned(First* const^) safe;
using NativeReadTied=unsigned(Tied* const^) safe;
using NativeWriteFirst=void(First*^) safe;
using NativeWriteTied=void(Tied*^) safe;
using NativeOuterFirst=void(NativeReadFirst*) safe;
using NativeOuterTied=void(NativeReadTied*) safe;
using ScopedMutableTied=void /(outer)(MutTied* const^/outer,const unsigned^/outer) safe;
using ScopedMutableFree=void /(renamed)(MutFree* const^/renamed,const unsigned^/renamed) safe;
using ScopedMutableOuterTied=void(ScopedMutableTied*) safe;
using ScopedMutableOuterFree=void(ScopedMutableFree*) safe;
using NativeFactoryFirst=First* const^/static () safe;
using NativeFactoryTied=Tied* const^/static () safe;
using FirstRow=First* const[2];
using TiedRow=Tied* const[2];
using TiedRow3=Tied* const[3];
using NativeArrayFirst=unsigned(const FirstRow^) safe;
using NativeArrayTied=unsigned(const TiedRow^) safe;
using NativeArrayTied3=unsigned(const TiedRow3^) safe;
using ReferenceArrayFirst=unsigned(const FirstRow&) safe;
using ReferenceArrayTied=unsigned(const TiedRow&) safe;
using PointerArrayFirst=unsigned(const FirstRow*) safe;
using PointerArrayTied=unsigned(const TiedRow*) safe;
using MutableFirstRow=First*[2];
using MutableTiedRow=Tied*[2];
using MutableArrayFirst=void(MutableFirstRow^) safe;
using MutableArrayTied=void(MutableTiedRow^) safe;
using RawSlotFirst=unsigned(First* const*) safe;
using UnsafeReader=unsigned(UnsafeFirst* const^) safe;
using NothrowReader=unsigned(FirstThrow* const^) safe;
template<class F> using Reader=unsigned(F* const^) safe;
using TemplateReaderFirst=Reader<First>;
using TemplateReaderTied=Reader<Tied>;
struct MemberOwner {};
using MemberFirst=First MemberOwner::*;
using MemberTied=Tied MemberOwner::*;
using MemberReaderFirst=void(MemberFirst) safe;
using MemberReaderTied=void(MemberTied) safe;
using MemberSlotFirst=void(First* MemberOwner::*) safe;
using MemberSlotTied=void(Tied* MemberOwner::*) safe;
unsigned read_shared(Tied* const^ slot) safe {
 unsigned a=3u,b=5u;return *(*slot)(^const a,^const b);
}
unsigned read_array(const TiedRow^ slots) safe {
 unsigned a=3u,b=5u;return *(*slots)[0](^const a,^const b);
}
template<class F> unsigned read_generic(F* const^ slot) safe {
 unsigned a=3u,b=5u;return *(*slot)(^const a,^const b);
}
First* const permanent_callback=&first;
First* const^/static factory_slot() safe {unsafe {return ^const permanent_callback;}}
static_assert(!__is_same(First,Tied));
static_assert(!__is_same(First,Short));
'''
# A scalar pack can precede bound parameters in both aliases and functions.
# Check zero/one/many parameters, including the expanded-source encoding past
# index 30. Type identity includes bindings, projections, edges and provenance.
API += """
template<class... Ts> using PackedFirst=const unsigned^/a /(a,b)(Ts...,const unsigned^/a,const unsigned^/b) safe;
template<class... Ts> using PackedTied=const unsigned^/a /(a)(Ts...,const unsigned^/a,const unsigned^/a) safe;
template<class... Ts> using PackedShort=const unsigned^/b /(a,b where a:b)(Ts...,const unsigned^/a,const unsigned^/b) safe;
template<class... Ts> using PackedStatic=void /(a,b where a:static,b:a)(Ts...,const unsigned^/a,const unsigned^/b) safe;
template<class... Ts> using PackedFree=void /(a,b where a:static)(Ts...,const unsigned^/a,const unsigned^/b) safe;
struct RegionPair/(a,b){const unsigned^/a first;const unsigned^/b second;};
template<class... Ts> using PackedMulti=void /(a,b,c)(Ts...,const RegionPair/a/b^/c) safe;
template<class... Ts> using PackedClass=View/a /(a,c)(Ts...,const View/a^/c) safe;
template<class... Ts> const unsigned^/a relay/(a)(Ts... ignored,const unsigned^/a tail) safe {return tail;}
"""
for size in (0, 1, 2, 34):
    arguments = ','.join(['unsigned']*size)
    prefix = arguments+(',' if size else '')
    for name, result, binders, parameters in (
            ('First', 'const unsigned^/a', 'a,b', 'const unsigned^/a,const unsigned^/b'),
            ('Tied', 'const unsigned^/a', 'a', 'const unsigned^/a,const unsigned^/a'),
            ('Short', 'const unsigned^/b', 'a,b where a:b', 'const unsigned^/a,const unsigned^/b'),
            ('Class', 'View/a', 'a,c', 'const View/a^/c'),
            ('Static', 'void', 'a,b where a:static,b:a', 'const unsigned^/a,const unsigned^/b'),
            ('Free', 'void', 'a,b where a:static', 'const unsigned^/a,const unsigned^/b'),
            ('Multi', 'void', 'a,b,c', 'const RegionPair/a/b^/c')):
        API += (f'using Pack{name}{size}=Packed{name}<{arguments}>;'
                f'using Expect{name}{size}={result} /({binders})({prefix}{parameters}) safe;'
                f'static_assert(__is_same(Pack{name}{size},Expect{name}{size}));\n')
    API += (f'using Relay{size}=const unsigned^/a /(a)({prefix}const unsigned^/a) safe;'
            f'static_assert(__is_same(decltype(relay<{arguments}>),Relay{size}));\n')

# Source <= target. Scalar borrow durations are covariant, including mutable
# borrow durations; mutable referent contents, unlike durations, are invariant.
CASES = [
    ('same', 'First', 'First', True),
    ('shared_duration', 'First', 'Tied', True),
    ('cannot_invent_first_result', 'Tied', 'First', False),
    ('shorter_result', 'First', 'Short', True),
    ('cannot_choose_other_result', 'First', 'Second', False),
    ('cannot_extend_result', 'Short', 'First', False),
    ('static_instantiation', 'First', 'Static', True),
    ('static_placeholder_leak', 'Static', 'First', False),
    ('static_kind_specialization', 'AnyKind', 'StaticKind', True),
    ('static_kind_not_fresh', 'StaticKind', 'AnyKind', False),
    ('static_edge_not_fresh', 'StaticEdge', 'StaticFree', False),
    ('static_edge_specialization', 'StaticFree', 'StaticEdge', True),
    ('static_result_does_not_constrain_input', 'Single', 'StaticResultLoose', False),
    ('static_result_covariance', 'StaticResultLoose', 'Single', True),
    ('noexcept_weaken', 'FirstThrow', 'First', True),
    ('noexcept_invent', 'First', 'FirstThrow', False),
    ('safe_weaken', 'First', 'UnsafeFirst', True),
    ('safe_invent', 'UnsafeFirst', 'First', False),
    ('callback_contravariance', 'ConsumerTied', 'ConsumerFirst', True),
    ('callback_wrong_direction', 'ConsumerFirst', 'ConsumerTied', False),
    ('double_contravariance', 'OuterFirst', 'OuterTied', True),
    ('double_contravariance_reverse', 'OuterTied', 'OuterFirst', False),
    ('result_covariance', 'FactoryFirst', 'FactoryTied', True),
    ('result_covariance_reverse', 'FactoryTied', 'FactoryFirst', False),
    ('mutable_callback_slot', 'StoreTied', 'StoreFirst', False),
    ('mutable_callback_slot_reverse', 'StoreFirst', 'StoreTied', False),
    ('readonly_callback_slot', 'ReadStoreTied', 'ReadStoreFirst', True),
    ('readonly_callback_slot_reverse', 'ReadStoreFirst', 'ReadStoreTied', False),
    ('shared_class_region', 'SharedTied', 'SharedFree', True),
    ('shared_class_region_reverse', 'SharedFree', 'SharedTied', True),
    ('mutable_class_region', 'MutTied', 'MutFree', False),
    ('mutable_class_specialization', 'MutFree', 'MutTied', True),
    ('nested_mutable_data', 'SlotTied', 'SlotFree', False),
    ('nested_mutable_specialization', 'SlotFree', 'SlotTied', True),
    ('nested_shared_data', 'ReadTied', 'ReadFree', True),
    ('interior_mutable_data', 'CellTied', 'CellFree', False),
    ('class_result_shorten', 'Clone', 'ShortClone', True),
    ('class_result_extend', 'ShortClone', 'Clone', False),
    ('native_shared_callback', 'NativeReadTied', 'NativeReadFirst', True),
    ('native_shared_reverse', 'NativeReadFirst', 'NativeReadTied', False),
    ('native_mutable_slot', 'NativeWriteTied', 'NativeWriteFirst', False),
    ('native_mutable_slot_reverse', 'NativeWriteFirst', 'NativeWriteTied', False),
    ('native_double_contravariance', 'NativeOuterFirst', 'NativeOuterTied', True),
    ('native_double_reverse', 'NativeOuterTied', 'NativeOuterFirst', False),
    ('independent_outer_and_inner_binders', 'ScopedMutableTied', 'ScopedMutableFree', True),
    ('independent_binders_not_unified', 'ScopedMutableFree', 'ScopedMutableTied', False),
    ('scoped_mutable_double_contravariance', 'ScopedMutableOuterFree', 'ScopedMutableOuterTied', True),
    ('scoped_mutable_double_reverse', 'ScopedMutableOuterTied', 'ScopedMutableOuterFree', False),
    ('native_result_covariance', 'NativeFactoryFirst', 'NativeFactoryTied', True),
    ('native_result_reverse', 'NativeFactoryTied', 'NativeFactoryFirst', False),
    ('native_array_callback', 'NativeArrayTied', 'NativeArrayFirst', True),
    ('native_array_reverse', 'NativeArrayFirst', 'NativeArrayTied', False),
    ('native_array_bound', 'NativeArrayTied3', 'NativeArrayFirst', False),
    ('reference_array_callback', 'ReferenceArrayTied', 'ReferenceArrayFirst', True),
    ('reference_array_reverse', 'ReferenceArrayFirst', 'ReferenceArrayTied', False),
    ('pointer_array_callback', 'PointerArrayTied', 'PointerArrayFirst', True),
    ('pointer_array_reverse', 'PointerArrayFirst', 'PointerArrayTied', False),
    ('mutable_array_callback', 'MutableArrayTied', 'MutableArrayFirst', False),
    ('mutable_array_reverse', 'MutableArrayFirst', 'MutableArrayTied', False),
    ('borrow_handle_representation', 'RawSlotFirst', 'NativeReadFirst', False),
    ('borrow_handle_erasure', 'NativeReadFirst', 'RawSlotFirst', False),
    ('template_reader', 'TemplateReaderTied', 'TemplateReaderFirst', True),
    ('template_reader_reverse', 'TemplateReaderFirst', 'TemplateReaderTied', False),
    ('member_callback', 'MemberReaderTied', 'MemberReaderFirst', True),
    ('member_callback_reverse', 'MemberReaderFirst', 'MemberReaderTied', False),
    ('member_data_slot', 'MemberSlotTied', 'MemberSlotFirst', False),
    ('member_data_slot_reverse', 'MemberSlotFirst', 'MemberSlotTied', False),
    ('nested_safe_weaken', 'UnsafeReader', 'NativeReadFirst', True),
    ('nested_safe_invent', 'NativeReadFirst', 'UnsafeReader', False),
    ('nested_noexcept_weaken', 'NativeReadFirst', 'NothrowReader', True),
    ('nested_noexcept_invent', 'NothrowReader', 'NativeReadFirst', False),
]
for size in (0, 1, 2, 34):
    CASES += [(f'pack_{size}_substitution', f'PackFirst{size}', f'PackTied{size}', True),
              (f'pack_{size}_reverse', f'PackTied{size}', f'PackFirst{size}', False),
              (f'pack_{size}_where', f'PackFirst{size}', f'PackShort{size}', True),
              (f'pack_{size}_where_reverse', f'PackShort{size}', f'PackFirst{size}', False),
              (f'pack_{size}_static_edge', f'PackStatic{size}', f'PackFree{size}', False),
              (f'pack_{size}_static_specialization', f'PackFree{size}', f'PackStatic{size}', True)]
PROGRAM = '''
int main() safe {
 unsigned a=7u,b=11u;
 Tied* tied=&first;Short* shorter=adapt<First,Short>(&first);
 if(*tied(^const a,^const b)!=7u || *shorter(^const a,^const b)!=7u)return 1;
 ConsumerFirst* consumer=&consume_tied;
 if(consumer(&first)!=3u)return 2;
 FactoryTied* make=&factory;
 if(*make()(^const a,^const b)!=7u)return 3;
 First* callback=&first;
 NativeReadFirst* reader=&read_shared;
 if(reader(^const callback)!=3u)return 4;
 NativeReadFirst* generic=&read_generic<Tied>;
 if(generic(^const callback)!=3u)return 5;
 FirstRow row{&first,&first};
 NativeArrayFirst* array=&read_array;
 if(array(^const row)!=3u)return 6;
 auto shared=^const callback;
 Tied* const^ renamed=shared;
 if(*(*renamed)(^const a,^const b)!=7u)return 7;
 if(read_shared(^const callback)!=3u)return 8;
 NativeFactoryTied* borrowed_factory=&factory_slot;
 if(*(*borrowed_factory())(^const a,^const b)!=7u)return 9;
 if(*relay<unsigned,unsigned>(1u,2u,^const a)!=7u)return 10;
 Relay2* selected=&relay<unsigned,unsigned>;
 if(*selected(1u,2u,^const a)!=7u)return 11;
 const unsigned permanent=13u;
 return 0;
}
'''


def main():
    flags = ['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values',
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    with tempfile.TemporaryDirectory(prefix='higher-ranked-') as directory:
        d = pathlib.Path(directory)
        module, pcm, obj, source, binary = (d/n for n in ('api.cppm','api.pcm','api.o','client.cpp','run'))
        module.write_text('export module higher;export {\n'+API+'}\n')

        def compile(options, okay=True):
            r = subprocess.run([str(CLANG)]+options,capture_output=True,text=True,timeout=120)
            assert (r.returncode == 0) == okay, r.stderr+'\n'+source.read_text()
            assert 'PLEASE submit' not in r.stderr, r.stderr
            if not okay: assert 'error:' in r.stderr, r.stderr

        source.write_text(API)
        compile(flags+['--precompile',str(module),'-o',str(pcm)])
        imported = ['-fmodule-file=higher='+str(pcm)]
        count = 0
        for name, src, dst, okay in CASES:
            bodies = [f'void check({src}* f) unsafe {{{dst}* g=f;}}',
                      f'void check({src}* f) unsafe {{auto g=reinterpret_cast<{dst}*>(f);}}',
                      f'void check({src}* f) unsafe {{auto g=adapt<{src},{dst}>(f);}}']
            for entry, body in enumerate(bodies):
                for use_pcm in (False, True):
                    source.write_text(('import higher;\n' if use_pcm else API)+body)
                    # Unsafe reinterpretation of an unchanged region contract
                    # retains the existing explicit effect-cast rules. It is
                    # not a standard conversion or evidence of subtyping.
                    accepted = okay or (entry == 1 and name in ('noexcept_invent', 'safe_invent'))
                    compile(flags+(imported if use_pcm else [])+['-fsyntax-only',str(source)],accepted)
                    count += 1
        # The direct member-pointer entry uses exactly the same relation as
        # nested callback parameters. Member data still names invariant storage.
        for src, dst, okay in (('MemberFirst','MemberTied',True),
                               ('MemberTied','MemberFirst',False)):
            for expression in ('p', f'reinterpret_cast<{dst}>(p)',
                               f'member_adapt<{dst}>(p)'):
                body = ('template<class To,class From> To member_adapt(From p) unsafe {return p;}'
                        f'void check({src} p) unsafe {{{dst} q={expression};}}')
                for use_pcm in (False, True):
                    source.write_text(('import higher;\n' if use_pcm else API)+body)
                    compile(flags+(imported if use_pcm else [])+['-fsyntax-only',str(source)],okay)
                    count += 1
        for body in (
                'void good(First*const& slot) unsafe {auto& view=reinterpret_cast<Tied*const&>(slot);}',
                'void good(First& code) unsafe {auto& view=reinterpret_cast<Tied&>(code);}'):
            for use_pcm in (False, True):
                source.write_text(('import higher;\n' if use_pcm else API)+body)
                compile(flags+(imported if use_pcm else [])+['-fsyntax-only',str(source)])
                count += 1
        # Actual storage remains invariant; a subtype relation on the values
        # cannot authorize rewriting a mutable pointer to such a value.
        for body in ('void check(First** f) unsafe {auto g=reinterpret_cast<Tied**>(f);}',
                     'void check(Tied** f) unsafe {auto g=reinterpret_cast<First**>(f);}'):
            source.write_text(API+body)
            compile(flags+['-fsyntax-only',str(source)],False)
        for body in (
                'unsigned bad() safe {unsigned longer=1u;const unsigned^ saved;'
                '{unsigned shorter=2u;Tied* f=&first;saved=f(^const longer,^const shorter);}'
                'return *saved;}',
                'unsigned bad() safe {unsigned longer=1u;const unsigned^ saved;'
                '{unsigned shorter=2u;FactoryTied* f=&factory;'
                'saved=f()(^const longer,^const shorter);}return *saved;}',
                'unsigned bad(UnsafeFirst* f) safe {unsigned x=1u;return *f(^const x,^const x);}',
                'void bad(Tied* const^ slot) unsafe {First* const^ wrong=slot;}',
                'void bad(First*& slot) unsafe {auto& changed=reinterpret_cast<Tied*&>(slot);}',
                'void bad(Tied*& slot) unsafe {auto& changed=reinterpret_cast<First*&>(slot);}',
                'void bad(First*& slot) unsafe {auto& changed=(Tied*&)slot;}',
                'void bad(First*& slot) unsafe {auto&& changed=reinterpret_cast<Tied*&&>(slot);}',
                'void bad(Tied* const& slot) unsafe {auto& changed=reinterpret_cast<First* const&>(slot);}',
                'void bad(First* const^ slot) unsafe {auto erased=reinterpret_cast<const void*>(slot);}',
                'void bad(First* const^ slot) unsafe {auto erased=__builtin_bit_cast(const void*,slot);}',
                'void bad(First*^ slot) unsafe {auto changed=__builtin_bit_cast(Tied*^,slot);}',
                'void bad(First* MemberOwner::* slot) unsafe {'
                'auto changed=reinterpret_cast<Tied* MemberOwner::*>(slot);}',
                'void bad(Tied* MemberOwner::* slot) unsafe {'
                'auto changed=reinterpret_cast<First* MemberOwner::*>(slot);}',
                'void bad(First* MemberOwner::* slot) unsafe {'
                'auto changed=__builtin_bit_cast(Tied* MemberOwner::*,slot);}',
                'void bad(Tied* MemberOwner::* slot) unsafe {'
                'auto changed=__builtin_bit_cast(First* MemberOwner::*,slot);}',
                'unsigned bad() safe {const unsigned^ saved;{unsigned shorter=2u;'
                'Relay2* f=&relay<unsigned,unsigned>;saved=f(1u,2u,^const shorter);}'
                'return *saved;}',
                'unsigned bad() safe {const unsigned^ saved;{unsigned shorter=2u;'
                'saved=relay<unsigned,unsigned>(1u,2u,^const shorter);}return *saved;}',
                'using Bad=void() safe unsafe;'):
            for use_pcm in (False,True):
                source.write_text(('import higher;\n' if use_pcm else API)+body)
                compile(flags+(imported if use_pcm else [])+['-fsyntax-only',str(source)],False)
        for opt in ('-O0','-O2'):
            for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
                options = flags+[opt]+san
                compile(options+['--precompile',str(module),'-o',str(pcm)])
                compile(options+['-c',str(pcm),'-o',str(obj)])
                for use_pcm in (False,True):
                    source.write_text(('import higher;\n' if use_pcm else API)+PROGRAM)
                    compile(options+(imported if use_pcm else [])+[str(source)]+
                            ([str(obj)] if use_pcm else [])+['-o',str(binary)])
                    r = subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
                    assert r.returncode == 0, r.stderr+str(r.returncode)
        # Signature normalization must retain real ABI distinctions. A linked
        # provider intentionally violates the client's declared return type;
        # the indirect call must still trip UBSan's function check.
        provider = d/'wrong.cpp'
        provider.write_text('extern "C" unsigned wrong(const unsigned^ x) unsafe {return *x;}')
        source.write_text('extern "C" const unsigned^ wrong(const unsigned^ x) unsafe;'
                          'int main() unsafe {unsigned x=1u;auto f=&wrong;auto r=f(^const x);return 0;}')
        compile(flags+['-O0','-fsanitize=undefined','-fno-sanitize-recover=all',
                       str(provider),str(source),'-o',str(binary)])
        r = subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
        assert r.returncode != 0 and 'incorrect function type' in r.stderr, r.stderr
        # CFI and KCFI consume the same erased signature view. Check their IR
        # identifiers without depending on a platform LTO linker/runtime.
        source.write_text(API+PROGRAM+
                          'unsigned other(const unsigned^ x,const unsigned^ y) unsafe {return 0u;}')
        ir = d/'signatures.ll'
        compile(flags+['-O0','-S','-emit-llvm','-flto','-fvisibility=hidden',
                       '-fsanitize=cfi-icall',str(source),'-o',str(ir)])
        llvm = ir.read_text()

        def metadata(name, annotation, text):
            return re.search(r'^define .*@_Z'+str(len(name))+name+r'[^\n]*?!'+annotation+r' !(\d+)',
                             text,re.MULTILINE).group(1)

        def cfi(name):
            return re.search(r'^!'+metadata(name,'type',llvm)+r' = !\{i64 0, !"([^"]+)"',
                             llvm,re.MULTILINE).group(1)

        first_id, other_id = cfi('first'), cfi('other')
        assert first_id != other_id
        assert 'metadata !"'+first_id+'"' in llvm
        assert 'metadata !"'+cfi('read_shared')+'"' in llvm
        assert 'metadata !"'+cfi('read_array')+'"' in llvm
        assert 'lifetime_bindings' not in first_id and 'returnsBorrow' not in first_id
        compile(flags+['-O0','-S','-emit-llvm','-target','aarch64-unknown-linux-gnu',
                       '-fsanitize=kcfi',str(source),'-o',str(ir)])
        llvm = ir.read_text()

        def kcfi(name):
            return re.search(r'^!'+metadata(name,'kcfi_type',llvm)+r' = !\{i32 (-?\d+)\}',
                             llvm,re.MULTILINE).group(1)

        assert kcfi('first') != kcfi('other')
        assert '"kcfi"(i32 '+kcfi('first')+')' in llvm
        assert '"kcfi"(i32 '+kcfi('read_shared')+')' in llvm
        assert '"kcfi"(i32 '+kcfi('read_array')+')' in llvm
        # A compact type DAG must not expand into 2**24 relation or runtime
        # signature queries. Both parameter and result repeat the same type.
        dag = ('using A0=void /(a,b)(const unsigned^/a,const unsigned^/b) safe;\n'
               'using B0=void /(a)(const unsigned^/a,const unsigned^/a) safe;\n')
        for level in range(1,25):
            for letter in ('A','B'):
                dag += f'using {letter}{level}={letter}{level-1}*({letter}{level-1}*) safe;\n'
        dag += 'using C0=A0;using D0=B0;\n'
        for level in range(1,25):
            for letter in ('C','D'):
                previous = f'{letter}{level-1}'
                dag += (f'using {letter}{level}={previous}* const^/a /(a)'
                        f'({previous}* const^/a) safe;\n')
        source.write_text(dag+'void check(A24* f) unsafe {B24* g=f;}\n'
                          'A24* echo(A24* f) safe {return f;}\n'
                          'void check_native(C24* f) unsafe {D24* g=f;}\n'
                          'C24* echo_native(C24* f) safe {return f;}\n')
        compile(flags+['-O0','-S','-emit-llvm','-fsanitize=undefined',
                       str(source),'-o',str(ir)])
    print(f'Scoped callable relations: {count} local/PCM implicit/cast/template checks; '
          'shared covariance, mutable contents invariance, nested contravariance, '
          'static leak/effect/return/storage refusals; 8 O0/O2 plain ASan/UBSan runs, '
          'real ABI-mismatch UBSan trap, CFI/KCFI IR identifiers and 24-level type DAG passed')


if __name__ == '__main__':
    main()
