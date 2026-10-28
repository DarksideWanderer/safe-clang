#!/usr/bin/env python3
"""Native function effects: canonical identity, conversions, PCM, and null traps."""
import json
import pathlib
import resource
import signal
import subprocess
import sys
import tempfile

clang, root = sys.argv[1:]
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='safecpp-functions-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'functions': 'safe', 'client': 'safe', 'raw': 'unsafe'}}))
    count = 0
    def check(name, body, ok=True, mode='safe', extra=()):
        global count
        source = tmp/(name+'.cppm')
        source.write_text('export module '+('raw' if mode=='unsafe' else 'functions')+';\n'+body)
        result = subprocess.run([clang, '-std=c++20', '-fmodule-'+mode, '-fmodule-safety-policy='+str(policy), '-fprebuilt-module-path='+str(tmp), str(source)]+list(extra or ['-fsyntax-only']), text=True, capture_output=True)
        if (result.returncode == 0) != ok: raise AssertionError(name+'\n'+result.stderr)
        if not ok and ('PLEASE submit a bug report' in result.stderr or 'frontend command failed' in result.stderr): raise AssertionError(result.stderr)
        count += 1
    alias = 'using Safe = unsigned __attribute__((safe_function)) (unsigned);\n'
    check('inferred', 'unsigned target(unsigned n) { return n; } unsigned f() { auto p=&target; return p(2u); }')
    check('identity', alias+'unsigned target(unsigned n) { return n; } static_assert(__is_same(decltype(&target), Safe*));')
    check('drop_effect', alias+'unsigned target(unsigned n) { return n; } unsigned (*p)(unsigned)=&target;')
    check('drop_then_call', 'unsigned target(unsigned n) { return n; } unsigned f() { unsigned (*p)(unsigned)=&target; return p(1u); }', False)
    check('unsafe_upgrade', alias+'unsafe_fn unsigned raw(unsigned n) { return n; } void f() { unsafe { Safe* p=&raw; } }', False)
    check('legacy_upgrade', alias+'using Raw=unsigned(unsigned); void f(Raw* raw) { unsafe { Safe* p=raw; } }', False)
    check('uninitialized', alias+'unsigned f() { Safe* p; return p(1u); }', False)
    check('borrow_alias', 'using Safe = unsigned __attribute__((safe_function)) (unsigned&, const unsigned&); unsigned f(Safe* p) { unsigned x=1u; return p(x,x); }', False)
    check('reference_return', 'using Safe = const unsigned& __attribute__((safe_function)) (const unsigned&); unsigned f(Safe* p) { unsigned x=1u; return p(x); }', False)
    check('redeclare_unsafe', 'unsigned target(unsigned); unsafe_fn unsigned target(unsigned n) { return n; }', False)
    check('unsafe_definition_claim', alias+'unsigned target(unsigned n) __attribute__((safe_function)); unsigned target(unsigned n) { return n; }', False, mode='unsafe')
    borrow = 'using Borrow = const unsigned& __attribute__((safe_function, returns_borrow(0))) (const unsigned&);\n'
    check('typed_borrow', borrow+'unsigned f(Borrow* p) { unsigned x=1u; return p(x); }')
    check('typed_borrow_conflict', borrow+'unsigned f(Borrow* p) { unsigned x=1u; const unsigned& r=p(x); x=2u; return r; }', False)
    check('typed_borrow_temporary', borrow+'unsigned f(Borrow* p) { const unsigned& r=p(1u); return r; }', False)
    check('typed_borrow_bad_index', 'using Borrow = const unsigned& __attribute__((safe_function, returns_borrow(2))) (const unsigned&);', False)
    check('typed_borrow_bad_parameter', 'using Borrow = const unsigned& __attribute__((safe_function, returns_borrow(0))) (unsigned);', False)
    check('typed_borrow_bad_result', 'using Borrow = unsigned __attribute__((safe_function, returns_borrow(0))) (const unsigned&);', False)
    contract = '__attribute__((annotate("safecpp.borrow.from:x"))) '
    check('typed_borrow_identity', borrow+contract+'const unsigned& identity(const unsigned& x) { return x; } static_assert(__is_same(decltype(&identity), Borrow*));')
    check('typed_borrow_wrong_origin', contract+'const unsigned& identity(const unsigned& x, const unsigned& y) { return y; }', False)
    check('typed_borrow_redeclaration', borrow+contract+'const unsigned& identity(const unsigned& x); const unsigned& identity(const unsigned& renamed) { return renamed; } static_assert(__is_same(decltype(&identity), Borrow*));')
    check('typed_borrow_overload', contract+'const unsigned& identity(const unsigned& x) { return x; } unsigned identity(unsigned x, unsigned y) { return x; }')
    check('typed_borrow_region_mismatch', 'using First = const unsigned& __attribute__((safe_function, returns_borrow(0))) (const unsigned&,const unsigned&); using Second = const unsigned& __attribute__((safe_function, returns_borrow(1))) (const unsigned&,const unsigned&); void f(First* p) { Second* q=p; }', False)
    check('typed_borrow_side_effect', 'unsigned index=0u; using Borrow = const unsigned& __attribute__((safe_function, returns_borrow((index=0u,0)))) (const unsigned&);', False)
    check('typed_borrow_intersection', 'using Borrow = const unsigned& __attribute__((safe_function, returns_borrow(0), returns_borrow(1))) (const unsigned&,const unsigned&);')
    native_identity = 'const unsigned^ identity(const unsigned^ x){return ^const x;}'
    check('native_lifetime_elision',native_identity+'using Expected=const unsigned^ __attribute__((safe_function,returns_borrow(0))) (const unsigned^);static_assert(__is_same(decltype(&identity),Expected*));')
    check('native_lifetime_elision_conflict',native_identity+'unsigned f(){unsigned x=1u;const unsigned^ r=identity(^const x);x=2u;return r;}',False)
    check('native_lifetime_elision_local_escape','const unsigned^ bad(const unsigned^ x){unsigned local=1u;return ^const local;}',False)
    check('native_lifetime_elision_temporary',native_identity+'unsigned f(){const unsigned^ r=identity(1u);return r;}',False)
    check('native_lifetime_elision_ambiguous','const unsigned^ bad(const unsigned^ x,const unsigned^ y){return ^const x;}',False)
    check('native_lifetime_elision_template','template<class T> const T^ identity(const T^ x){return ^const x;} unsigned f(){unsigned x=1u;return identity(^const x);}')
    native_callback = 'using NativeCallback=const unsigned^ __attribute__((safe_function)) (const unsigned^);'
    check('native_lifetime_callback_identity',native_callback+native_identity+'static_assert(__is_same(decltype(&identity),NativeCallback*));')
    check('native_lifetime_callback_repeat',native_callback+'unsigned apply(NativeCallback* p){unsigned x=1u;unsigned first=p(^const x);{unsigned y=2u;unsigned second=p(^const y);if(second!=2u)return 0u;}return first;}')
    check('native_lifetime_callback_escape',native_callback+'unsigned apply(NativeCallback* p){const unsigned^ escaped=p(1u);return escaped;}',False)
    check('native_lifetime_callback_freeze',native_callback+'unsigned apply(NativeCallback* p){unsigned x=1u;const unsigned^ r=p(^const x);x=2u;return r;}',False)
    many_parameters = ','.join('const unsigned&' for _ in range(34))
    expanded = 'using Wide=const unsigned& __attribute__((safe_function,returns_borrow(0),returns_borrow(33))) ('+many_parameters+');'
    check('expanded_lifetime_sources', expanded)
    check('expanded_lifetime_order', expanded+'using Reordered=const unsigned& __attribute__((safe_function,returns_borrow(33),returns_borrow(0),returns_borrow(33))) ('+many_parameters+');static_assert(__is_same(Wide,Reordered));')
    check('expanded_lifetime_identity', expanded+'using Other=const unsigned& __attribute__((safe_function,returns_borrow(1),returns_borrow(33))) ('+many_parameters+');static_assert(!__is_same(Wide,Other));')
    wide_arguments = ','.join(['x']*33+['y'])
    check('expanded_lifetime_indirect_freeze', expanded+'unsigned f(Wide* p){unsigned x=1u,y=2u;const unsigned& r=p('+wide_arguments+');y=3u;return r;}',False)
    check('expanded_lifetime_indirect_read', expanded+'unsigned f(Wide* p){unsigned x=1u,y=2u;return p('+wide_arguments+');}')
    check('expanded_lifetime_temporary_escape', expanded+'unsigned f(Wide* p){unsigned x=1u;const unsigned&r=p('+','.join(['x']*33+['2u'])+');return r;}',False)
    check('expanded_lifetime_unrelated_write', expanded+'unsigned f(Wide* p){unsigned x=1u,y=2u,z=3u;const unsigned&r=p('+wide_arguments+');z=4u;return r+z;}')
    named = '__attribute__((annotate("safecpp.borrow.lifetime:a"))) const unsigned& pick(bool first,__attribute__((annotate("safecpp.lifetime:a"))) const unsigned& x,__attribute__((annotate("safecpp.lifetime:a"))) const unsigned& y){if(first)return x;return y;} '
    check('named_lifetime_type', named+'using Both=const unsigned& __attribute__((safe_function,returns_borrow(1),returns_borrow(2))) (bool,const unsigned&,const unsigned&);static_assert(__is_same(decltype(&pick),Both*));')
    check('named_lifetime_indirect_conflict', named+'unsigned f(){unsigned x=1u,y=2u;auto p=&pick;const auto&r=p(true,x,y);y=3u;return r;}',False)
    check('higher_rank_borrow_callback', borrow+'unsigned apply(Borrow* callback){unsigned a=1u;unsigned first=callback(a);{unsigned b=2u;unsigned second=callback(b);if(second!=2u)return 0u;}return first;}')
    check('higher_rank_borrow_escape', borrow+'unsigned apply(Borrow* callback){const unsigned& escaped=callback(1u);return escaped;}',False)
    check('named_lifetime_drop_source' , named+'using One=const unsigned& __attribute__((safe_function,returns_borrow(1))) (bool,const unsigned&,const unsigned&);One* p=&pick;',False)
    pair = 'struct Pair { const unsigned& a; const unsigned& b; }; using PairFn = Pair __attribute__((safe_function, returns_borrow(0), returns_borrow(1))) (const unsigned&,const unsigned&);\n'
    check('typed_object_borrow', pair+'unsigned f(PairFn* p) { unsigned x=1u,y=2u; Pair v=p(x,y); return v.a; }')
    check('typed_object_borrow_conflict', pair+'unsigned f(PairFn* p) { unsigned x=1u,y=2u; Pair v=p(x,y); y=3u; return v.a; }', False)
    check('typed_object_borrow_identity', pair+'__attribute__((annotate("safecpp.borrow.from:x"), annotate("safecpp.borrow.from:y"))) Pair make(const unsigned& x,const unsigned& y) { return Pair{x,y}; } static_assert(__is_same(decltype(&make), PairFn*));')
    check('typed_static_borrow', '__attribute__((annotate("safecpp.borrow.static"))) const unsigned& permanent() { static const unsigned x=7u; return x; } unsigned f() { auto pointer=&permanent; const unsigned& value=pointer(); return value; }')
    check('typed_static_bad', '__attribute__((annotate("safecpp.borrow.static"))) const unsigned& bad() { unsigned x=1u; return x; }', False)
    wide_definition = '__attribute__((annotate("safecpp.borrow.from:p0"),annotate("safecpp.borrow.from:p33"))) const unsigned& wide('+','.join('const unsigned& p'+str(i) for i in range(34))+'){if(p0)return p0;return p33;} static_assert(__is_same(decltype(&wide),Wide*));export Wide* selectWide(){return &wide;}'
    check('factory', native_callback+'export const unsigned^ nativeIdentity(const unsigned^ x){return ^const x;} export NativeCallback* selectNative(){return &nativeIdentity;}'+expanded+wide_definition+alias+borrow+pair+contract+'const unsigned& identity(const unsigned& x) { return x; } export Borrow* selectBorrow() { return &identity; } __attribute__((annotate("safecpp.borrow.from:x"), annotate("safecpp.borrow.from:y"))) Pair makePair(const unsigned& x,const unsigned& y) { return Pair{x,y}; } export PairFn* selectPair() { return &makePair; } unsigned target(unsigned n) { return n; } export Safe* select(bool b) { if(b) return &target; return nullptr; }', extra=['--precompile','-o',str(tmp/'functions.pcm')])
    client = tmp/'client.cppm'
    client.write_text('export module client; import functions; export unsigned run(bool valid) { auto pointer=select(valid); return pointer(42u); } export unsigned runBorrow() { unsigned x=7u; auto pointer=selectBorrow(); const unsigned& result=pointer(x); return result; } export unsigned runNative(){unsigned x=5u;auto p=selectNative();return p(^const x);} export unsigned runWide(){unsigned x=7u,y=9u;auto p=selectWide();return p(x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,x,y);} export unsigned runPair() { unsigned x=2u,y=3u; auto pointer=selectPair(); auto value=pointer(x,y); return value.b; }')
    wide_bad = tmp/'wide_bad.cppm'
    wide_bad.write_text('export module client;import functions;unsigned f(){unsigned x=1u,y=2u;auto p=selectWide();const unsigned&r=p('+wide_arguments+');y=3u;return r;}')
    result = subprocess.run([clang,'-std=c++20','-fmodule-safe','-fmodule-safety-policy='+str(policy),'-fprebuilt-module-path='+str(tmp),str(wide_bad),'-fsyntax-only'],text=True,capture_output=True)
    if result.returncode == 0 or 'PLEASE submit a bug report' in result.stderr: raise AssertionError('expanded lifetime PCM source was lost\n'+result.stderr)
    checked = [clang, '-std=c++20', '-fmodule-safe', '-fmodule-safety-policy='+str(policy), '-fprebuilt-module-path='+str(tmp)]
    subprocess.run(checked+['--precompile',str(client),'-o',str(tmp/'client.pcm')],check=True)
    for name in ('functions','client'):
        subprocess.run([clang,'-std=c++20','-fprebuilt-module-path='+str(tmp),'-c',str(tmp/(name+'.pcm')),'-o',str(tmp/(name+'.o'))],check=True)
    main = tmp/'main.cpp'
    main.write_text('import client; int main(int argc,char**) { return run(argc==1)==42u && runBorrow()==7u && runPair()==3u && runWide()==7u && runNative()==5u ? 0 : 1; }')
    binary = tmp/'test'
    subprocess.run([clang,'--driver-mode=g++','-std=c++20','-fprebuilt-module-path='+str(tmp),str(main),str(tmp/'functions.o'),str(tmp/'client.o'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    result = subprocess.run([str(binary),'null'],capture_output=True)
    if result.returncode not in (-signal.SIGILL,-signal.SIGTRAP,-signal.SIGABRT): raise AssertionError(f'null safe function pointer failed to trap: {result.returncode}')
print(f'{count} native function-type cases, cross-module indirect call and null trap passed')
