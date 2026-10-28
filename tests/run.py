#!/usr/bin/env python3
import hashlib, json, pathlib, subprocess, sys, tempfile
clang, plugin, root = sys.argv[1:]
base = [clang, '-std=c++20', '-I'+root+'/include', '-Xclang', '-load', '-Xclang', plugin, '-Xclang', '-add-plugin', '-Xclang', 'module-safety']
count = 0
with tempfile.TemporaryDirectory(prefix='module-safety-') as tmp:
    tmp = pathlib.Path(tmp)
    def run(name, source, ok, mode='safe', flags=(), needle='module-safety:'):
        global count
        path = tmp/(name+('.cppm' if 'export module' in source else '.cpp'))
        path.write_text(source)
        cmd = base + ['-Xclang', '-plugin-arg-module-safety', '-Xclang', mode] + list(flags) + [str(path)]
        if not flags: cmd += ['-fsyntax-only']
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        diagnosed = needle in result.stderr or (needle == 'module-safety:' and 'error:' in result.stderr)
        if (result.returncode == 0) != ok or (not ok and not diagnosed) or 'PLEASE submit' in result.stderr or 'frontend command failed' in result.stderr:
            raise AssertionError(f'{name}: {cmd}\n{result.stderr}')
        count += 1
        return result
    def unit(body): return 'export module test;\n'+body
    run('openmp_unmodeled', unit('unsigned f() { unsigned x=0u;\n#pragma omp parallel shared(x)\n{ ++x; }\nreturn x; }'), False, flags=['-fopenmp','-fsyntax-only'])
    run('scalar', unit('export unsigned id(unsigned n) { return n; }'), True)
    tls='inline thread_local unsigned global=1u; '
    run('tls_live_borrow_direct_write',unit(tls+'unsigned f(){const unsigned& r=global;global=2u;return r;}'),False,needle='mutation conflicts')
    run('tls_live_borrow_indirect_write',unit(tls+'void change(){global=2u;}unsigned f(){const unsigned& r=global;change();return r;}'),False,needle='call may invalidate')
    run('tls_live_borrow_transitive_write',unit(tls+'void change(){global=2u;}void nested(){change();}unsigned f(){const unsigned& r=global;nested();return r;}'),False,needle='call may invalidate')
    run('tls_live_borrow_readonly_call',unit(tls+'unsigned read(){return global;}unsigned f(){const unsigned& r=global;return read()+r;}'),True)
    run('tls_live_borrow_pure_call',unit(tls+'unsigned pure(){return 2u;}unsigned f(){const unsigned& r=global;return pure()+r;}'),True)
    run('tls_live_borrow_opaque_call',unit(tls+'void opaque();unsigned f(){const unsigned& r=global;opaque();return r;}'),False,needle='call may invalidate')
    run('tls_live_borrow_recursive_write',unit(tls+'void first(unsigned);void second(unsigned n){if(n)first(n);global=2u;}void first(unsigned n){if(n)second(n);}unsigned f(){const unsigned& r=global;first(1u);return r;}'),False,needle='call may invalidate')
    run('tls_loan_ends_before_mutation',unit(tls+'void change(){global=2u;}unsigned f(){unsigned copy;{const unsigned& r=global;copy=r;}change();return copy;}'),True)
    run('consuming_receiver_capture',unit('struct X{unsigned take()&&{return 1u;}};unsigned f(){X x;auto callback=[&x]()mutable{return static_cast<X&&>(x).take();};return callback();}'),False,needle='consume through a capture')
    run('consuming_receiver_init_capture',unit('struct X{unsigned take()&&{return 1u;}};unsigned f(){auto callback=[x=X{}]()mutable{return static_cast<X&&>(x).take();};return callback();}'),False,needle='consume through a capture')
    consuming='struct X{unsigned n=1u;unsigned take() && {return n;}}; '
    run('consuming_receiver_value',unit(consuming+'unsigned f(){X x;return static_cast<X&&>(x).take();}'),True)
    run('consuming_receiver_read_after',unit(consuming+'unsigned f(){X x;static_cast<X&&>(x).take();return x.n;}'),False,needle='use of a moved value')
    run('consuming_receiver_twice',unit(consuming+'unsigned f(){X x;static_cast<X&&>(x).take();return static_cast<X&&>(x).take();}'),False,needle='use of a moved value')
    run('consuming_receiver_borrow',unit(consuming+'unsigned f(){X x;X& r=x;return static_cast<X&&>(r).take();}'),False,needle='cannot consume through a borrow')
    run('consuming_receiver_live_loan',unit(consuming+'unsigned f(){X x;const X& r=x;static_cast<X&&>(x).take();return r.n;}'),False,needle='borrow')
    run('consuming_receiver_reinitialize',unit(consuming+'unsigned f(){X x;static_cast<X&&>(x).take();x=X{};return x.n;}'),True)
    run('consuming_receiver_partial_restore',unit(consuming+'unsigned f(){X x;static_cast<X&&>(x).take();x.n=2u;return x.n;}'),False,needle='use of a moved value')
    run('consuming_receiver_temporary',unit(consuming+'unsigned f(){return X{}.take();}'),True)
    run('consuming_receiver_subobject',unit(consuming+'struct Y{X x;};unsigned f(){Y y;return static_cast<X&&>(y.x).take();}'),True)
    run('consuming_receiver_const',unit('struct X{unsigned n=1u;unsigned take() const && {return n;}};'),False,needle='unqualified owner')
    run('consuming_receiver_drop',unit('struct X{unsigned n=1u;~X(){} unsigned take() && {return n;}};'),False,needle='moved-from destructor')
    run('consuming_receiver_returns_self',unit('#include "module_safety.h"\nstruct X{unsigned n=1u;SAFETY_RETURNS_THIS const unsigned& take() && {return n;}};'),False,needle='cannot return a borrow of itself')
    run('consuming_receiver_exception',unit('struct X{unsigned n=1u;unsigned take() && {throw 1u;}};unsigned f(){X x;try{static_cast<X&&>(x).take();}catch(...){return x.n;}return 0u;}'),False,needle='use of a moved value')
    run('consuming_receiver_operator',unit('struct X{unsigned n=1u;unsigned operator()() && {return n;}};unsigned f(){X x;static_cast<X&&>(x)();return x.n;}'),False,needle='use of a moved value')
    run('consuming_receiver_this_owned',unit('struct X{unsigned n=1u;unsigned take() && {return n;}unsigned again() && {return static_cast<X&&>(*this).take();}};'),True)
    run('consuming_receiver_this_borrowed',unit('struct X{unsigned n=1u;unsigned take() && {return n;}unsigned again() & {return static_cast<X&&>(*this).take();}};'),False,needle='ownership of this')
    run('consuming_receiver_this_reuse',unit('struct X{unsigned n=1u;unsigned take() && {return n;}unsigned again() && {static_cast<X&&>(*this).take();return n;}};'),False,needle='moved receiver')
    run('consuming_receiver_this_subobject',unit(consuming+'struct Y{X x;unsigned take() && {return static_cast<X&&>(x).take();}};'),False,needle='partial-move')
    run('consuming_receiver_parameter',unit(consuming+'unsigned f(X value){return static_cast<X&&>(value).take();}'),True)
    run('consuming_receiver_unchecked',unit(consuming+'unsigned f(){X x;static_cast<X&&>(x).take();return x.n;}'),True,mode='unsafe')
    run('consuming_receiver_unconsumed_this',unit('struct X{unsigned n=1u;unsigned read() & {return n;}unsigned take() && {return read();}};'),True)
    run('consuming_receiver_inherited_drop',unit(consuming+'struct Y:X{~Y(){}};unsigned f(){Y y;return static_cast<Y&&>(y).take();}'),False,needle='actual owner')
    run('consuming_receiver_branch',unit(consuming+'unsigned f(bool condition){X x;if(condition)static_cast<X&&>(x).take();return x.n;}'),False,needle='moved')
    run('ctor_uninitialized_array_field',unit('struct S{unsigned data[2];S(){}};void f(){S value;}'),False,needle='does not initialize a scalar field or array')
    run('ctor_uninitialized_nested_array_field',unit('struct S{unsigned data[2][3];S(){}};void f(){S value;}'),False,needle='does not initialize a scalar field or array')
    run('ctor_initialized_array_field',unit('struct S{unsigned data[2];S():data{}{}};void f(){S value;}'),True)
    run('ctor_default_array_field',unit('struct S{unsigned data[2]{};S(){}};void f(){S value;}'),True)
    run('defaulted_array_value_initialization',unit('struct S{unsigned data[2];S()=default;};void f(){S value{};}'),True)
    simple_union='union U{unsigned a;float b;}; '
    for name,assignment in [('operator','alias=second'),('explicit','alias.operator=(second)')]:
        run('union_alias_assign_'+name,unit(simple_union+'unsigned f(){U first{.a=1u};U second{.b=3.0f};{U&alias=first;'+assignment+';}return first.a;}'),False,needle='not active')
        run('union_alias_assign_known_'+name,unit(simple_union+'float f(){U first{.a=1u};U second{.b=3.0f};{U&alias=first;'+assignment+';}return first.b;}'),True)
    run('union_copy_from_alias',unit(simple_union+'float f(){U original{.b=3.0f};const U&alias=original;U copied(alias);return copied.b;}'),True)
    movable = 'struct X { unsigned a=1u; X(){} X(X&& v):a(v.a){} }; '
    run('ctor_initializer_cannot_consume_borrow', unit(movable+'struct Y { X owned; Y(X& x):owned(static_cast<X&&>(x)){} };'), False, needle='ownership through a borrow')
    run('pinned_owned_parameter_self_reference_escape',unit('struct __attribute__((annotate("safecpp.pinned"))) Self {unsigned value;const unsigned& ref;__attribute__((annotate("safecpp.stores.self"))) Self():value(1u),ref(value){}Self(const Self&)=delete;Self(Self&&)=delete;};__attribute__((annotate("safecpp.borrow.from:value"))) const unsigned& escape(Self value){return value.ref;}'),False,needle='returned reference does not borrow')
    run('ctor_initializer_move_then_read', unit(movable+'struct Y { X owned; unsigned n; Y(X x):owned(static_cast<X&&>(x)),n(x.a){} };'), False, needle='use of a moved value')
    run('ctor_initializer_move_then_body_read', unit(movable+'struct Y { X owned; Y(X x):owned(static_cast<X&&>(x)){unsigned n=x.a;} };'), False, needle='use of a moved value')
    run('ctor_base_initializer_move_then_read', unit(movable+'struct Y:X { unsigned n; Y(X x):X(static_cast<X&&>(x)),n(x.a){} };'), False, needle='use of a moved value')
    run('ctor_initializer_read_then_move', unit(movable+'struct Y { unsigned n; X owned; Y(X x):n(x.a),owned(static_cast<X&&>(x)){} };'), True)
    run('ctor_function_try_missing_eh', unit('struct X { unsigned a=1u; X(){} X(X&& v):a(v.a){throw 1u;} }; struct Y { X owned; Y(X x) try :owned(static_cast<X&&>(x)){} catch(...){unsigned n=x.a;throw;} };'), False, needle='use of a moved value')
    run('local_ctor_missing_eh', unit('struct X { X(){throw 1u;} }; void f(){try{X x;}catch(...){}}'), True)
    run('local_dtor_missing_eh', unit('struct X { X() noexcept {} ~X() noexcept(false){throw 1u;} }; void f(){try{X x;}catch(...){}}'), True)
    run('local_noexcept_construction_handlers', unit('struct X { X() noexcept {} ~X() noexcept {} }; void f(){try{X x;throw 1u;}catch(...){}}'), True)
    for kind,body in [('ctor','X() try:a(1u){throw 1u;}'),('dtor','X():a(1u){} ~X() noexcept(false) try{throw 1u;}')]:
        run('function_try_dead_object_'+kind,unit('struct X {unsigned a;'+body+'catch(...){unsigned n=a;throw;} };'),False,flags=['-Wno-exceptions','-fsyntax-only'],needle='members have already been destroyed')
    throwing='struct X {X(){throw 1u;}}; '
    run('ctor_exception_skips_assignment',unit(throwing+'unsigned f(){unsigned n;try{X x;n=1u;}catch(...){return n;}return n;}'),False,needle='not initialized on every control-flow path')
    run('ctor_exception_preserves_prior_assignment',unit(throwing+'unsigned f(){unsigned n;try{n=1u;X x;}catch(...){return n;}return n;}'),True)
    run('ctor_exception_ends_local_loan',unit(throwing+'void f(unsigned& n){try{unsigned& r=n;X x;}catch(...){n=2u;}}'),True)
    run('local_ctor_exception_consumes_argument',unit('struct X {unsigned a=1u;X(){} X(X&& x):a(x.a){throw 1u;}};unsigned f(X x){try{X y(static_cast<X&&>(x));}catch(...){return x.a;}return 0u;}'),False,needle='use of a moved value')
    union_prefix='union U{unsigned a;float b;};void activate(U& u){u.b=3.0f;} '
    for name,body in {
        'constructor': 'struct Switch{Switch(U& u){activate(u);}};unsigned f(){U u{1u};Switch s(u);return u.a;}',
        'pointer_constructor': 'struct Switch{Switch(U* u){unsafe{u->b=3.0f;}}};unsigned f(){U u{1u};Switch s(&u);return u.a;}',
        'borrow_record_call': 'struct View{U& u;};void change(const View& v){activate(v.u);}unsigned f(){U u{1u};{View v{u};change(v);}return u.a;}',
        'borrow_record_method': 'struct View{U& u;void change(){activate(u);}};unsigned f(){U u{1u};{View v{u};v.change();}return u.a;}',
        'borrow_record_assignment': 'struct View{U& u;void operator=(const View&){activate(u);}};unsigned f(){U u{1u};U other{1u};{View v{u};View source{other};v=source;}return u.a;}',
        'drop': 'struct Drop{U& u;~Drop(){activate(u);}};unsigned f(){U u{1u};{Drop d{u};}return u.a;}',
        'throwing_drop': 'struct Drop{U& u;~Drop() noexcept(false){activate(u);throw 1u;}};unsigned f(){U u{1u};try{Drop d{u};}catch(...){return u.a;}return 0u;}',
        'temporary_drop': 'struct Drop{U& u;~Drop(){activate(u);}};unsigned f(){U u{1u};Drop{u};return u.a;}',
        'unwinding_drop': 'void fail(){throw 1u;}struct Drop{U& u;~Drop(){activate(u);}};unsigned f(){U u{1u};try{Drop d{u};fail();}catch(...){return u.a;}return 0u;}',
    }.items():
        run('union_mutation_'+name,unit(union_prefix+body),False,needle='union member is not active')
    run('union_readonly_record_call',unit(union_prefix+'struct View{const U& u;};void inspect(const View&){} unsigned f(){U u{1u};{View v{u};inspect(v);}return u.a;}'),True)
    run('union_trivial_move_preserves_tag',unit(union_prefix+'unsigned f(){U u{1u};U v(static_cast<U&&>(u));return v.a;}'),True)
    defaults='struct X{X(){throw 1u;}}; '
    run('default_member_constructor_exception',unit(defaults+'struct Aggregate{X field{};};unsigned f(){unsigned n;try{Aggregate x{};n=1u;}catch(...){return n;}return n;}'),False,needle='not initialized on every control-flow path')
    run('default_array_constructor_exception',unit(defaults+'struct Aggregate{X field[2]{};};unsigned f(){unsigned n;try{Aggregate x{};n=1u;}catch(...){return n;}return n;}'),False,needle='not initialized on every control-flow path')
    run('default_argument_constructor_exception',unit(defaults+'void consume(X value=X{}) noexcept {} unsigned f(){unsigned n;try{consume();n=1u;}catch(...){return n;}return n;}'),False,needle='not initialized on every control-flow path')
    run('default_argument_destructor_exception',unit('struct X{X()noexcept{} ~X()noexcept(false){throw 1u;}};void consume(const X& value=X{})noexcept{} unsigned f(){unsigned n;try{consume();n=1u;}catch(...){return n;}return n;}'),False,needle='not initialized on every control-flow path')
    run('default_noexcept_argument',unit('struct X{X()noexcept{} ~X()noexcept{}};void consume(X value=X{})noexcept{} unsigned f(){unsigned n;try{consume();n=1u;}catch(...){return n;}return n;}'),True)
    run('default_immediate_argument',unit('consteval unsigned immediate(){return 1u;} void consume(unsigned value=immediate())noexcept{} unsigned f(){unsigned n;try{consume();n=1u;}catch(...){return n;}return n;}'),True)
    run('implicit_array_filler_unsafe_constructor',unit('struct X{unsafe_fn X(){}};void f(){X array[2]{};}'),False,needle='unsafe or unclassified')
    run('array_filler_constructor_exception',unit(defaults+'unsigned f(){unsigned n;try{X array[2]{};n=1u;}catch(...){return n;}return n;}'),False,needle='not initialized on every control-flow path')
    rtti='struct Base{virtual ~Base(){}};struct Derived:Base{}; '
    run('dynamic_cast_exception_skips_assignment',unit(rtti+'unsigned f(Base& b){unsigned n;try{const auto&d=dynamic_cast<const Derived&>(b);n=1u;}catch(...){return n;}return n;}'),False,needle='not initialized on every control-flow path')
    run('dynamic_cast_exception_preserves_assignment',unit(rtti+'unsigned f(Base& b){unsigned n=1u;try{const auto&d=dynamic_cast<const Derived&>(b);n=2u;}catch(...){return n;}return n;}'),True)
    run('typeid_exception_skips_assignment','module;\n#include <typeinfo>\n'+unit(rtti+'unsigned f(Base* p){unsigned n;try{unsafe{typeid(*p);}n=1u;}catch(...){return n;}return n;}'),False,needle='not initialized on every control-flow path')
    run('unsupported_cxx23',unit('unsigned f(){return 1u;}'),False,flags=['-std=c++23','-fsyntax-only'])
    run('unsupported_cxx17',unit('unsigned f(){return 1u;}'),False,flags=['-std=c++17','-fsyntax-only'])
    run('nothrow_cpp_semantics', unit('__attribute__((nothrow)) void f(){throw 1u;}'), True)
    runtime_fold = 'constexpr int choose(int x){unsafe{return __builtin_constant_p(x)?1:2147483647;}} '
    for name, expression in [('add', 'choose(1)+1'), ('mul', 'choose(1)*2')]:
        run('runtime_fold_'+name, unit(runtime_fold+'int f(){return '+expression+';}'), plugin == 'native')
    run('runtime_fold_negation', unit('constexpr int choose(int x){unsafe{return __builtin_constant_p(x)?1:(-2147483647-1);}} int f(){return -choose(1);}'), False)
    run('runtime_fold_int_float', unit('constexpr unsigned __int128 choose(int x){unsafe{return __builtin_constant_p(x)?1:~(unsigned __int128)0;}} float f(){return choose(1);}'), False)
    run('materialized_constant_arithmetic', unit('constexpr int k=2;consteval int immediate(){return 3;}int f(){return k+immediate()+1;}'), True)
    view_prefix='struct View{const unsigned& value;}; '
    return_view='__attribute__((annotate("safecpp.borrow.from:value"))) const View& f(bool c,const View& value){View local=value;return '
    for name,expression in [('branch','c?local:value'),('cast_branch','static_cast<const View&>(c?local:value)'),('temporary','View{value.value}')]:
        run('view_storage_'+name,unit(view_prefix+return_view+expression+';}'),False)
    run('view_storage_static_temporary',unit(view_prefix+'constexpr unsigned g=1u;__attribute__((annotate("safecpp.borrow.static"))) const View& f(){return View{g};}'),False)
    run('view_storage_alias_ok',unit(view_prefix+'__attribute__((annotate("safecpp.borrow.from:value"))) const View& f(bool c,const View& value){const View& alias=value;return c?alias:value;}'),True)
    for name, body in {
        'pure_promise': '__attribute__((pure)) unsigned f(unsigned& x){x=2u;return x;}',
        'const_promise': '__attribute__((const)) unsigned f(unsigned& x){x=2u;return x;}',
        'weak_import': '__attribute__((weak_import)) unsigned missing();unsigned f(){return missing();}',
        'weak_symbol': '__attribute__((weak)) unsigned missing();unsigned f(){return missing();}',
        'weak_variable': 'extern const unsigned x __attribute__((weak_import));unsigned f(){return x;}',
        'asm_variable': 'extern const unsigned x asm("_foreign");unsigned f(){return x;}',
        'naked_abi': '__attribute__((naked)) void f(){}',
        'returns_twice_abi': '__attribute__((returns_twice)) void f(){}',
        'pragma_metadata': '\n#pragma clang attribute push (__attribute__((annotate("safecpp.safe"))), apply_to=function)\nunsigned f(){return 1u;}\n#pragma clang attribute pop\n',
    }.items():
        run(name, unit(body), False)
    for name, body in {
        'missing_return': 'unsigned f(bool b) { if (b) return 1u; }',
        'empty_return': 'unsigned f() {}',
        'loop_return': 'unsigned f(bool b) { while (b) { return 1u; } }',
        'catch_return': 'unsigned f() { try { throw 1u; } catch (...) {} }',
        'call_catch_return': 'unsigned g(); unsigned f() { try { return g(); } catch (...) {} }',
        'lambda_return': 'unsigned f(bool b) { auto g=[b]() -> unsigned { if(b) return 1u; }; return g(); }',
        'template_return': 'template<class T> unsigned f(T b) { if(b) return 1u; } unsigned g() { return f(false); }',
    }.items():
        run(name, unit(body), False, flags=['-Wno-return-type', '-fsyntax-only'], needle='non-void function can reach its end')
    for name, body in {
        'complete_returns': 'unsigned f(bool b) { if(b) return 1u; else return 2u; }',
        'throw_exit': 'unsigned f() { throw 1u; }',
        'infinite_exit': 'unsigned f() { for (;;) {} }',
        'cleanup_return': 'struct X { ~X() {} }; unsigned f() { X x; return 1u; }',
        'catch_complete': 'unsigned f() { try { throw 1u; } catch (...) { return 1u; } }',
        'void_fallthrough': 'void f() {}',
    }.items():
        run(name, unit(body), True)
    for name, body in {
        'wide_float_implicit': 'float f(unsigned __int128 x) { return x; }',
        'wide_float_explicit': 'float f(unsigned __int128 x) { return static_cast<float>(x); }',
        'wide_half': '_Float16 f(unsigned x) { return x; }',
    }.items():
        run(name, unit(body), False, needle='integer-to-floating conversion may exceed')
    for name, body in {
        'signed_wide_float': 'float f(__int128 x) { return x; }',
        'wide_double': 'double f(unsigned __int128 x) { return x; }',
        'implicit_narrowing': 'unsigned char f(unsigned x) { return x; }',
    }.items():
        result = run(name, unit(body), True)
        assert 'module-safety: implicit conversion from' in result.stderr, result.stderr
    for name, body in {
        'implicit_promotion': 'unsigned f(unsigned char x) { return x; }',
        'implicit_bool': 'bool f(unsigned x) { return x; }',
        'implicit_argument': 'void g(double x) {} void f(unsigned x) { g(x); }',
        'implicit_constant': 'unsigned char f() { return 42u; }',
        'implicit_float_constant': 'float f() { return 42u; }',
        'wide_constant_float': 'float f() { constexpr unsigned __int128 n=42u; return n; }',
    }.items():
        result = run(name, unit(body), True)
        assert 'module-safety: implicit conversion from' not in result.stderr, result.stderr
    result = run('explicit_conversion_intent', unit('double f(unsigned x) { return static_cast<double>(x); }'), True)
    assert 'module-safety: implicit conversion from' not in result.stderr, result.stderr
    run('implicit_warning_as_error', unit('float f(unsigned x) { return x; }'), False,
        flags=['-Werror', '-fsyntax-only'], needle='module-safety: implicit conversion from')
    run('dynamic_global_order', unit('struct A { unsigned n; A():n(1u){} unsigned get()const{return n;} }; extern const A later; unsigned read(){return later.get();} const unsigned earlier=read(); const A later;'), False, needle='dynamic static initialization')
    run('recursive_static_init', unit('unsigned f(){static const unsigned n=f();return n;}'), False, needle='dynamic static initialization')
    run('static_destruction', unit('struct A { unsigned n=1u; ~A(){} }; const A a{};'), False, needle='static destruction')
    run('throw_borrow_escape', unit('struct View { const unsigned& r; }; void f(){unsigned x=7u;throw View{x};}'), False, needle='exception payload cannot carry')
    run('catch_scalar_read', unit('unsigned f(){try {throw 7u;} catch(const unsigned& value){return value;}}'), True)
    run('constexpr_global_object', unit('struct A { unsigned n; constexpr A():n(1u){} }; constinit const A a; unsigned f(){return a.n;}'), True)
    run('packed_reference', unit('struct __attribute__((packed)) P{char c;unsigned n;}; unsigned f(){alignas(8) P p{0,42u};const unsigned&r=p.n;return r;}'), False, needle='unaligned access model')
    run('pragma_pack_reference', unit('#pragma pack(push,1)\nstruct P{char c;unsigned n;};\n#pragma pack(pop)\nunsigned f(){P p{0,42u};const unsigned&r=p.n;return r;}'), False, needle='unaligned access model')
    run('typedef_alignment', unit('typedef unsigned U __attribute__((aligned(1))); unsigned f(){U x=42u;const unsigned&r=x;return r;}'), False, needle='under-aligned storage')
    run('legacy_packed_type', 'module; struct __attribute__((packed)) P{char c;unsigned n;}; export module test; unsigned f(const P&p){const unsigned&r=p.n;return r;}', False, needle='unaligned storage')
    for option in ['-ffast-math', '-ffinite-math-only']:
        run('unsafe_math_flags', unit('double f(double x){return x;}'), False,
            flags=[option, '-fsyntax-only'], needle='floating-point assumptions invalidate')
    run('pure_virtual_ctor_helper', unit('struct B { B(){helper();} B(const B&)=delete; B&operator=(const B&)=delete; void helper(){f();} virtual void f()=0; }; struct D:B{D()=default;D(const D&)=delete;D&operator=(const D&)=delete;void f()override{}}; void run(){D d;}'), False, needle='during construction or destruction')
    run('pure_virtual_dtor_helper', unit('struct B { B()=default; B(const B&)=delete; B&operator=(const B&)=delete; ~B(){helper();} void helper(){f();} virtual void f()=0; }; struct D:B{D()=default;D(const D&)=delete;D&operator=(const D&)=delete;void f()override{}}; void run(){D d;}'), False, needle='during construction or destruction')
    run('partial_polymorphic_escape', unit('struct B; void helper(B&); struct B { B(){helper(*this);} B(const B&)=delete; B&operator=(const B&)=delete; virtual void f()=0; }; void helper(B&b){b.f();}'), False, needle='polymorphic object escapes')
    run('partial_polymorphic_alias', unit('struct B { B(){B&alias=*this;alias.f();} B(const B&)=delete; B&operator=(const B&)=delete; virtual void f()=0; };'), False, needle='polymorphic object escapes')
    run('pointer', unit('export int f(int* p) { return *p; }'), False)
    run('unchecked', unit('export int f(int* p) { return *p; }'), True, 'unsafe')
    # Native command-selected safety also checks ordinary translation units.
    # The separately loaded prototype plugin still requires a named module.
    run('nonmodule', 'int f() { return 1; }', plugin == 'native')
    if plugin == 'native':
        run('nonmodule_pointer', 'int f(int* p) { return *p; }', False)
    run('badmode', unit(''), False, 'unsaf')
    prefix = 'module;\n#include "module_safety.h"\nexport module test;\n'
    run('scope', prefix+'export int f(int* p) { SAFETY_UNSAFE { return *p; } return 0; }', True)
    run('scope_end', prefix+'export int f(int* p) { SAFETY_UNSAFE { (void)*p; } return *p; }', False)
    run('scope_else', prefix+'export int f(int* p) { SAFETY_UNSAFE { return 0; } else { return *p; } }', False)
    run('scope_lambda', prefix+'export void f(int* p) { SAFETY_UNSAFE { auto l = [p]() { return *p; }; } }', False)
    run('unsafe_fn', prefix+'SAFETY_UNSAFE_FN int raw(int* p) { return *p; }\nexport int f(int* p) { return raw(p); }', False)
    run('unsafe_wrapper', prefix+'SAFETY_UNSAFE_FN int raw(int* p) { return *p; }\nexport int f(int* p) { SAFETY_UNSAFE { return raw(p); } return 0; }', True)
    for name, body in {
        'array':'int f() { int a[1] = {0}; return a[2]; }',
        'new':'void f() { auto p = new int(0); }',
        'delete':'void f(int* p) { delete p; }',
        'negation':'int f(int a) { return -a; }',
        'overflow':'int f(int a) { return a + 1; }',
        'divide':'unsigned f(unsigned a, unsigned b) { return a / b; }',
        'shift':'unsigned f(unsigned a, unsigned b) { return a << b; }',
        'uninit':'int f() { int x; return x; }',
        'cast':'int* f(void* p) { return reinterpret_cast<int*>(p); }',
        'indirect':'unsigned f(unsigned (*p)()) { return p(); }',
    }.items():
        # Native division and known-array indexing have mandatory runtime
        # checks, exercised at O0/O2 with sanitizers in native_panic_checks.py.
        # The separately loaded prototype has no such CodeGen support.
        run(name, unit(body), plugin == 'native' and name in ('array', 'divide', 'overflow'))
    run('declared_module_api', unit('int external(); int f() { return external(); }'), True)
    run('template', unit('template<class T> int read(T p) { return *p; } int f(int* p) { return read(p); }'), False)
    run('forward', unit('unsigned id(unsigned); unsigned f() { return id(1u); } unsigned id(unsigned n) { return n; }'), True)
    run('global_init', unit('int* p = new int(1);'), False)
    run('partition', 'export module package:part; export unsigned id(unsigned x) { return x; }', True)
    run('legacy', 'module;\nextern int old();\nexport module test;\nint f() { return old(); }', False)
    run('legacy_headers', 'module;\n#include <vector>\n#include <utility>\nexport module test; export unsigned f() { return 1u; }', True)
    forged_header = tmp/'forged.h'
    forged_header.write_text('__attribute__((annotate("safecpp.safe"))) unsigned legacy(unsigned);')
    run('forged_header', 'module;\n#include "'+str(forged_header)+'"\nexport module test; unsigned f() { return legacy(1u); }', False)
    run('safe_provider', 'export module provider; export unsigned id(unsigned x) { return x; }', True,
        flags=['--precompile', '-o', str(tmp/'provider.pcm')])
    run('safe_import', 'export module user; import provider; export unsigned f() { return id(4u); }', True,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('unsafe_provider', 'export module raw; export int load(int* p) { return *p; }', True, 'unsafe',
        flags=['--precompile', '-o', str(tmp/'raw.pcm')])
    run('import_wrapper', 'module;\n#include "module_safety.h"\nexport module user; import raw; export int f(int* p) { SAFETY_UNSAFE { return load(p); } return 0; }', True,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('unsafe_import', 'export module user; import raw; int f(int* p) { return load(p); }', False,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('implementation', 'module provider; unsigned other() { return id(2u); }', True,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('mode_conflict', 'module provider; unsigned g() { return 1u; }', False, 'unsafe',
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('keyword_unsafe', unit('int f(int* p) { unsafe { return *p; } return 0; }'), True)
    run('keyword_restore', unit('int f(int* p) { unsafe { (void)*p; } return *p; }'), False)
    run('keyword_unsafe_fn', unit('unsafe_fn int raw(int* p) { return *p; } int f(int* p) { return raw(p); }'), False)
    for name, body, ok in [
        ('init_both', 'int f(bool b) { int x; if (b) x=1; else x=2; return x; }', True),
        ('init_one', 'int f(bool b) { int x; if (b) x=1; return x; }', False),
        ('init_loop', 'unsigned f(bool b) { unsigned x; while(b) { x=1u; b=false; } return x; }', False),
        ('init_do', 'unsigned f(bool b) { unsigned x; do { x=1u; b=false; } while(b); return x; }', True),
        ('init_self', 'int f() { int x=x; return x; }', False),
        ('borrow_shared_write', 'int f() { int x=1; const int& r=x; x=2; return r; }', False),
        ('borrow_exclusive_read', 'int f() { int x=1; int& r=x; int y=x; return r; }', False),
        ('borrow_exclusive_twice', 'int f() { int x=1; int& a=x; int& b=x; return a == b; }', False),
        ('borrow_last_use', 'int f() { int x=1; const int& r=x; int y=r; x=2; return y; }', True),
        ('borrow_scoped', 'int f() { int x=1; { const int& r=x; int y=r; } x=2; return x; }', True),
        ('borrow_arguments', 'int use(int& a, const int& b) { return a == b; } int f() { int x=1; return use(x,x); }', False),
        ('binding_copy', 'struct S { unsigned x=1u; }; unsigned f() { S s; auto [x]=s; return x; }', True),
        ('binding_borrow', 'struct S { unsigned x=1u; }; unsigned f() { S s; auto& [x]=s; s.x=2u; return x; }', False),
        ('binding_last_use', 'struct S { unsigned x=1u; }; unsigned f() { S s; auto& [x]=s; unsigned y=x; s.x=2u; return y; }', True),
    ]:
        run(name, unit(body), ok)
    for name, body, ok in [
        ('dangling_return', 'int& f() { int x=1; return x; }', False),
        ('borrow_identity', 'SAFETY_RETURNS_BORROW(x) const int& id(const int& x) { return x; } int f() { int x=1; return id(x); }', True),
        ('borrow_wrong_origin', 'SAFETY_RETURNS_BORROW(x) const int& id(const int& x) { int y=1; return y; }', False),
        ('borrow_identity_conflict', 'SAFETY_RETURNS_BORROW(x) const int& id(const int& x) { return x; } int f() { int x=1; const int& r=id(x); x=2; return r; }', False),
        ('borrow_call_argument_alias', 'SAFETY_RETURNS_BORROW(x) unsigned& id(unsigned& x) { return x; } unsigned use(unsigned& a, const unsigned& b) { a=2u; return b; } unsigned f() { unsigned x=1u; return use(id(x),x); }', False),
        ('borrow_intersection_contract', 'SAFETY_RETURNS_BORROW(x) SAFETY_RETURNS_BORROW(y) const int& f(const int& x,const int& y) { return x; }', True),
        ('borrow_missing_parameter', 'SAFETY_RETURNS_BORROW(missing) const int& f(const int& x) { return x; }', False),
        ('borrow_renamed_definition', 'SAFETY_RETURNS_BORROW(x) const int& id(const int& x); const int& id(const int& renamed) { return renamed; } int f() { int x=1; return id(x); }', True),
        ('borrow_stored', 'struct Ref { int& ref; };', True),
        ('object_shared_read', 'struct View { const unsigned& ref; }; unsigned f() { unsigned x=1u; View v{x}; return v.ref; }', True),
        ('object_shared_mutation', 'struct View { const unsigned& ref; }; unsigned f() { unsigned x=1u; View v{x}; x=2u; return v.ref; }', False),
        ('object_exclusive_read_owner', 'struct View { unsigned& ref; }; unsigned f() { unsigned x=1u; View v{x}; unsigned y=x; return v.ref; }', False),
        ('object_exclusive_write', 'struct View { unsigned& ref; }; unsigned f() { unsigned x=1u; View v{x}; v.ref=2u; return v.ref; }', True),
        ('object_copy_shared', 'struct View { const unsigned& ref; }; unsigned f() { unsigned x=1u; View a{x}; View b=a; return b.ref; }', True),
        ('object_copy_exclusive', 'struct View { unsigned& ref; }; unsigned f() { unsigned x=1u; View a{x}; View b=a; return b.ref; }', False),
        ('object_nested', 'struct View { const unsigned& ref; }; struct Outer { View inner; }; unsigned f() { unsigned x=1u; Outer v{{x}}; return v.inner.ref; }', True),
        ('object_nested_conflict', 'struct View { const unsigned& ref; }; struct Outer { View inner; }; unsigned f() { unsigned x=1u; Outer v{{x}}; x=2u; return v.inner.ref; }', False),
        ('object_temporary', 'struct View { const unsigned& ref; }; unsigned f() { View v{1u}; return v.ref; }', True),
        ('object_return_local', 'struct View { const unsigned& ref; }; View f() { unsigned x=1u; return View{x}; }', False),
        ('object_return_contract', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) View make(const unsigned& x) { return View{x}; } unsigned f() { unsigned x=1u; View v=make(x); return v.ref; }', True),
        ('object_return_conflict', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) View make(const unsigned& x) { return View{x}; } unsigned f() { unsigned x=1u; View v=make(x); x=2u; return v.ref; }', False),
        ('object_custom_constructor', 'struct View { const unsigned& ref; View(const unsigned& x):ref(x) {} }; unsigned f() { unsigned x=1u; View v(x); return v.ref; }', True),
        ('object_temporary_escape', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) View f(const unsigned& x) { View v{1u}; return v; }', False),
        ('object_two_owners', 'struct View { const unsigned& a; const unsigned& b; }; unsigned f() { unsigned x=1u,y=2u; View v{x,y}; y=3u; return v.a; }', False),
        ('object_return_wrong_origin', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) View make(const unsigned& x) { unsigned y=1u; return View{y}; }', False),
        ('object_move', 'struct View { unsigned& ref; }; unsigned f() { unsigned x=1u; View a{x}; View b(static_cast<View&&>(a)); return b.ref; }', True),
        ('object_move_use', 'struct View { unsigned& ref; }; unsigned f() { unsigned x=1u; View a{x}; View b(static_cast<View&&>(a)); return a.ref; }', False),
        ('object_borrow_through_parameter', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) View copy(View x) { return x; } unsigned f() { unsigned x=1u; View a{x}; View b=copy(a); return b.ref; }', True),
        ('object_ctor_conflict', 'struct View { const unsigned& ref; View(const unsigned& x):ref(x) {} }; unsigned f() { unsigned x=1u; View v(x); x=2u; return v.ref; }', False),
        ('object_ctor_temporary', 'struct View { const unsigned& ref; View(const unsigned& x):ref(x) {} }; unsigned f() { View v(1u); return v.ref; }', False),
        ('object_ctor_self_reference', 'struct View { unsigned x; const unsigned& ref; View():x(1u),ref(x) {} }; unsigned f() { View v; return v.ref; }', False),
        ('object_dtor_borrow', 'struct View { const unsigned& ref; View(const unsigned& x):ref(x) {} ~View() { auto x=ref; } }; unsigned f() { unsigned x=1u; View v(x); x=2u; return x; }', False),
        ('object_dtor_valid', 'struct View { const unsigned& ref; View(const unsigned& x):ref(x) {} ~View() { auto x=ref; } }; unsigned f() { unsigned x=1u; { View v(x); } x=2u; return x; }', True),
        ('object_argument_alias', 'struct View { const unsigned& ref; }; unsigned use(View v, unsigned& x) { x=2u; return v.ref; } unsigned f() { unsigned x=1u; View v{x}; return use(v,x); }', False),
        ('object_field_alias', 'struct View { unsigned& a; unsigned& b; }; unsigned f() { unsigned x=1u; View v{x,x}; return v.a; }', False),
        ('object_field_shared_alias', 'struct View { const unsigned& a; const unsigned& b; }; unsigned f() { unsigned x=1u; View v{x,x}; return v.a; }', True),
        ('object_multiple_return', 'struct Pair { const unsigned& a; const unsigned& b; }; SAFETY_RETURNS_BORROW(x) SAFETY_RETURNS_BORROW(y) Pair make(const unsigned& x,const unsigned& y) { return Pair{x,y}; } unsigned f() { unsigned x=1u,y=2u; Pair p=make(x,y); return p.b; }', True),
        ('object_multiple_conflict', 'struct Pair { const unsigned& a; const unsigned& b; }; SAFETY_RETURNS_BORROW(x) SAFETY_RETURNS_BORROW(y) Pair make(const unsigned& x,const unsigned& y) { return Pair{x,y}; } unsigned f() { unsigned x=1u,y=2u; Pair p=make(x,y); y=3u; return p.a; }', False),
        ('object_multiple_wrong_origin', 'struct Pair { const unsigned& a; const unsigned& b; }; SAFETY_RETURNS_BORROW(x) SAFETY_RETURNS_BORROW(y) Pair make(const unsigned& x,const unsigned& y) { unsigned z=1u; return Pair{x,z}; }', False),
        ('object_generic', 'template<class T> struct View { const T& ref; }; template<class T> SAFETY_RETURNS_BORROW(x) View<T> make(const T& x) { return View<T>{x}; } unsigned f() { unsigned x=1u; auto v=make(x); return v.ref; }', True),
        ('object_generic_conflict', 'template<class T> struct View { const T& ref; }; template<class T> SAFETY_RETURNS_BORROW(x) View<T> make(const T& x) { return View<T>{x}; } unsigned f() { unsigned x=1u; auto v=make(x); x=2u; return v.ref; }', False),
        ('object_parameter_move', 'struct View { unsigned& ref; }; SAFETY_RETURNS_BORROW(x) View relay(View x) { View y(static_cast<View&&>(x)); return y; } unsigned f() { unsigned x=1u; View v{x}; View w=relay(static_cast<View&&>(v)); return w.ref; }', True),
        ('object_parameter_storage_escape', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) const View& bad(View x) { return x; }', False),
        ('object_parameter_field_escape', 'struct View { unsigned value; const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) const unsigned& bad(View x) { return x.value; }', False),
        ('object_parameter_referent', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) const unsigned& get(View x) { return x.ref; } unsigned f() { unsigned x=1u; View v{x}; return get(v); }', True),
        ('send_exclusive_borrow', 'void transfer(SAFETY_SEND unsigned& value) {}', True),
        ('object_nested_storage_return', 'struct View { const unsigned& ref; }; struct Outer { const View& inner; }; SAFETY_RETURNS_BORROW(x) Outer bad(const unsigned& x) { View v{x}; return Outer{v}; }', False),
        ('object_extended_temporary_conflict', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) View make(const unsigned& x) { return View{x}; } unsigned f() { unsigned x=1u; const View& v=make(x); x=2u; return v.ref; }', False),
        ('object_reference_return_storage', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) const View& id(const View& x) { return x; } struct Outer { const View& inner; }; SAFETY_RETURNS_BORROW(x) Outer bad(const unsigned& x) { View v{x}; return Outer{id(v)}; }', False),
        ('object_const_interior_alias', 'struct View { unsigned& ref; }; unsigned use(const View& v,const unsigned& x) { v.ref=2u; return x; } unsigned f() { unsigned x=1u; View v{x}; return use(v,x); }', False),
        ('send_recursive_trait_modes', 'struct Node { const Node& shared; Node& exclusive; }; void transfer(SAFETY_SEND Node value) {}', False),
        ('send_scalar', 'void transfer(SAFETY_SEND unsigned value) {}', True),
        ('send_owned_record', 'struct Value { unsigned x; }; void transfer(SAFETY_SEND Value value) {}', True),
        ('send_raw_pointer', 'void transfer(SAFETY_SEND unsigned* value) {}', False),
        ('send_borrow', 'void transfer(SAFETY_SEND const unsigned& value) {}', True),
        ('send_borrow_record', 'struct View { const unsigned& ref; }; void transfer(SAFETY_SEND View value) {}', True),
        ('send_record_requirement', 'struct SAFETY_SEND_TYPE Value { unsigned x; };', True),
        ('send_record_requirement_bad', 'struct SAFETY_SEND_TYPE Value { unsigned* x; };', False),
        ('send_audited_owner', 'struct SAFETY_UNSAFE_IMPL_SEND Value { unsigned* x; }; void transfer(SAFETY_SEND Value value) {}', True),
        ('send_audit_no_lifetime_escape', 'struct SAFETY_UNSAFE_IMPL_SEND Value { const unsigned& x; }; void transfer(SAFETY_STATIC_SEND Value value) {}', False),
        ('sync_recursive', 'struct Node { const Node& next; }; void share(SAFETY_SYNC const Node& value) {}', True),
        ('sync_scalar', 'void share(SAFETY_SYNC const unsigned& value) {}', True),
        ('sync_exclusive', 'void share(SAFETY_SYNC unsigned& value) {}', False),
        ('sync_raw_storage', 'struct Value { unsigned* x; }; void share(SAFETY_SYNC const Value& value) {}', False),
        ('sync_const_view', 'struct View { const unsigned& ref; }; void share(SAFETY_SYNC const View& value) {}', True),
        ('sync_exclusive_view', 'struct View { unsigned& ref; }; void share(SAFETY_SYNC const View& value) {}', False),
        ('closure_scoped_ref', 'unsigned f() { unsigned x=1u; auto l=[&x] { return x; }; return l(); }', True),
        ('closure_ref_conflict', 'unsigned f() { unsigned x=1u; auto l=[&x] { return x; }; x=2u; return l(); }', False),
        ('closure_shared_factory', 'SAFETY_RETURNS_BORROW(x) auto factory(const unsigned& x) { return [&x] { return x; }; } unsigned f() { unsigned x=1u; auto l=factory(x); return l(); }', True),
        ('closure_shared_factory_conflict', 'SAFETY_RETURNS_BORROW(x) auto factory(const unsigned& x) { return [&x] { return x; }; } unsigned f() { unsigned x=1u; auto l=factory(x); x=2u; return l(); }', False),
        ('closure_borrowed_value', 'struct View { const unsigned& ref; }; unsigned f() { unsigned x=1u; View v{x}; auto l=[v] { return v.ref; }; return l(); }', True),
        ('closure_value_conflict', 'struct View { const unsigned& ref; }; unsigned f() { unsigned x=1u; View v{x}; auto l=[v] { return v.ref; }; x=2u; return l(); }', False),
        ('this_storage_escape', 'struct View { unsigned owned=1u; const unsigned& ref; SAFETY_RETURNS_THIS const unsigned& get() const { return owned; } }; SAFETY_RETURNS_BORROW(x) const unsigned& bad(const unsigned& x) { View v{1u,x}; return v.get(); }', False),
        ('closure_owned_pair', 'unsigned f() { unsigned x=1u,y=2u; auto l=[x,y] { return x+y; }; return l(); }', True),
        ('closure_reference_result', 'unsigned f() { const unsigned x=1u; auto l=[&x]() -> const unsigned& { return x; }; const unsigned& r=l(); return r; }', True),
        ('closure_owned_result_escape', 'SAFETY_RETURNS_BORROW(x) const unsigned& bad(const unsigned& x) { auto l=[x]() -> const unsigned& { return x; }; return l(); }', False),
        ('reborrow_shared', 'unsigned f() { unsigned x=1u; unsigned& a=x; const unsigned& b=a; return b; }', True),
        ('reborrow_exclusive', 'unsigned f() { unsigned x=1u; unsigned& a=x; unsigned& b=a; b=2u; return b; }', True),
        ('reborrow_parent_frozen', 'unsigned f() { unsigned x=1u; unsigned& a=x; unsigned& b=a; a=2u; return b; }', False),
        ('reborrow_shared_parent_write', 'unsigned f() { unsigned x=1u; unsigned& a=x; const unsigned& b=a; a=2u; return b; }', False),
        ('reborrow_last_use', 'unsigned f() { unsigned x=1u; unsigned& a=x; const unsigned& b=a; unsigned y=b; a=2u; return y; }', True),
        ('reborrow_object_field', 'struct View { unsigned& ref; }; unsigned f() { unsigned x=1u; View v{x}; const unsigned& r=v.ref; return r; }', True),
        ('reborrow_object_frozen', 'struct View { unsigned& ref; }; unsigned f() { unsigned x=1u; View v{x}; const unsigned& r=v.ref; v.ref=2u; return r; }', False),
        ('borrowed_base', 'struct Base { const unsigned& ref; }; struct Derived:Base { unsigned value; }; unsigned f() { unsigned x=1u; Derived d{{x},2u}; return d.ref; }', True),
        ('borrowed_base_conflict', 'struct Base { const unsigned& ref; }; struct Derived:Base { unsigned value; }; unsigned f() { unsigned x=1u; Derived d{{x},2u}; x=2u; return d.ref; }', False),
        ('borrowed_base_constructor', 'struct Base { const unsigned& ref; Base(const unsigned& x):ref(x) {} }; struct Derived:Base { Derived(const unsigned& x):Base(x) {} }; unsigned f() { unsigned x=1u; Derived d(x); return d.ref; }', True),
        ('borrowed_array_fields', 'struct View { const unsigned& ref; }; struct Views { View elements[2]; }; unsigned f() { unsigned x=1u,y=2u; Views v{{{x},{y}}}; x=2u; Views copy=v; return y; }', False),
        ('global_borrow_permanent', 'const unsigned owner=1u; struct View { const unsigned& ref; }; const View v{owner}; unsigned f() { return v.ref; }', True),
        ('global_borrow_temporary', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_BORROW(x) View make(const unsigned& x) { return View{x}; } const View v=make(1u); unsigned f() { return v.ref; }', False),
        ('global_borrow_extended', 'struct View { const unsigned& ref; }; const View v{1u}; unsigned f() { return v.ref; }', True),
        ('ctor_storage_contract', 'struct View { const unsigned& ref; SAFETY_STORES_BORROW(x) View(const unsigned& x):ref(x) {} }; unsigned f() { unsigned x=1u; View v(x); return v.ref; }', True),
        ('ctor_storage_wrong_source', 'struct View { const unsigned& ref; SAFETY_STORES_BORROW(x) View(const unsigned& x,const unsigned& y):ref(y) {} };', False),
        ('ctor_storage_rename', 'struct View { const unsigned& ref; SAFETY_STORES_BORROW(x) View(const unsigned& x); }; View::View(const unsigned& renamed):ref(renamed) {} unsigned f() { unsigned x=1u; View v(x); return v.ref; }', True),
        ('ctor_storage_changed', 'struct View { const unsigned& ref; SAFETY_STORES_BORROW(x) View(const unsigned& x,const unsigned& y); }; SAFETY_STORES_BORROW(y) View::View(const unsigned& x,const unsigned& y):ref(y) {}', False),
        ('borrowed_base_field_alias', 'struct Base { unsigned& a; }; struct Derived:Base { unsigned& b; }; unsigned f() { unsigned x=1u; Derived d{{x},x}; return d.b; }', False),
        ('unsafe_weaken_declaration', 'unsigned target(unsigned); unsafe_fn unsigned target(unsigned x) { return x; }', False),
        ('borrowed_move_dtor_rejected', 'struct View { const unsigned& ref; View(const unsigned& x):ref(x) {} View(View&&)=default; ~View() { auto x=ref; } }; unsigned f() { unsigned x=1u; View a{x}; View b(static_cast<View&&>(a)); return b.ref; }', False),
        ('static_borrow', 'SAFETY_RETURNS_STATIC const unsigned& permanent() { static const unsigned value=1u; return value; } unsigned f() { const unsigned& r=permanent(); return r; }', True),
        ('static_borrow_local', 'SAFETY_RETURNS_STATIC const unsigned& bad() { unsigned value=1u; return value; }', False),
        ('static_borrow_tls', 'thread_local const unsigned value=1u; SAFETY_RETURNS_STATIC const unsigned& bad() { return value; }', False),
        ('static_borrow_record', 'struct View { const unsigned& ref; }; SAFETY_RETURNS_STATIC View permanent() { static const unsigned value=1u; return View{value}; } unsigned f() { View v=permanent(); return v.ref; }', True),
        ('pinned_self', 'struct SAFETY_PINNED Self { unsigned value; const unsigned& ref; SAFETY_STORES_SELF Self():value(1u),ref(value) {} Self(const Self&)=delete; Self(Self&&)=delete; }; unsigned f() { Self s; return s.ref; }', True),
        ('pinned_self_move', 'struct SAFETY_PINNED Self { unsigned value; const unsigned& ref; Self():value(1u),ref(value) {} Self(const Self&)=delete; Self(Self&&)=delete; }; unsigned f() { Self s; Self t(static_cast<Self&&>(s)); return t.ref; }', False),
        ('pinned_requires_deleted', 'struct SAFETY_PINNED Self { unsigned value; const unsigned& ref; Self():value(1u),ref(value) {} };', False),
        ('pinned_reference_escape', 'struct SAFETY_PINNED Self { unsigned value; const unsigned& ref; Self():value(1u),ref(value) {} Self(const Self&)=delete; Self(Self&&)=delete; }; SAFETY_RETURNS_BORROW(x) const unsigned& bad(const unsigned& x) { Self s; return s.ref; }', False),
        ('asm_linkage_requires_unsafe', 'unsigned external(unsigned) asm("unclassified_external"); unsigned f() { return external(1u); }', False),
        ('cleanup_requires_unsafe', 'unsafe_fn void clean(unsigned* p) {} unsigned f() { unsigned x __attribute__((cleanup(clean)))=1u; return x; }', False),
        ('automatic_callback_rejected', '__attribute__((constructor)) void startup() {}', False),
        ('noreturn_normal_exit', '[[noreturn]] void f() {}', False),
        ('noreturn_throw', '[[noreturn]] void f() { throw 1; }', True),
        ('nonnull_unmodeled', '__attribute__((nonnull)) unsigned f(unsigned* p) { return 1u; }', False),
        ('capture_ref', 'auto f() { int x=1; return [&x] { return x; }; }', False),
        ('capture_value', 'int f() { int x=1; auto l=[x] { return x; }; return l(); }', True),
        ('unsafe_captured_this', 'struct S { unsigned x=1u; auto f() { unsafe { return [this] { return x; }; } } };', False),
        ('ctor_partial', 'struct S { int x; S() {} };', False),
        ('ctor_initialized', 'struct S { int x; S():x(1) {} }; int f() { S s; return s.x; }', True),
        ('ctor_self_read', 'struct S { unsigned x; S():x(x) {} };', False),
        ('ctor_member_order', 'struct S { unsigned x; unsigned y; S():x(y),y(1u) {} };', False),
        ('ctor_previous_member', 'struct S { unsigned x; unsigned y; S():x(1u),y(x) {} };', True),
        ('ctor_default_self_read', 'struct S { unsigned x=x; }; unsigned f() { S s; return s.x; }', False),
        ('ctor_partial_method', 'struct S { unsigned x; unsigned get() { return x; } S():x(get()) {} };', False),
        ('ctor_partial_argument', 'struct S; unsigned read(S&); struct S { unsigned x; S():x(read(*this)) {} }; unsigned read(S& s) { return s.x; }', False),
        ('shared_state', 'unsigned counter=0u; unsigned f() { return ++counter; }', False),
        ('tls_state', 'thread_local unsigned counter=0u; unsigned f() { return ++counter; }', True),
        ('forge_safe', '__attribute__((annotate("safecpp.safe"))) int f() { return 1; }', False),
        ('forge_module', 'namespace __attribute__((annotate("safecpp.module.safe.v1"))) forged {}', False),
        ('unsafe_dtor', 'struct S { SAFETY_UNSAFE_FN ~S() { unsafe {} } }; void f() { S s{}; }', False),
        ('unsafe_dtor_scope', 'struct S { SAFETY_UNSAFE_FN ~S() { unsafe {} } }; void f() { unsafe { S s{}; } }', True),
    ]:
        run(name, prefix+body, ok, needle="" if name=="unsafe_weaken_declaration" else "module-safety:")
    for name, body, ok in [
        ('unsequenced', 'unsigned f() { unsigned x=1u; return x++ + x++; }', False),
        ('sequenced', 'unsigned f() { unsigned x=1u; return (x++, x++); }', True),
        ('unevaluated', 'unsigned f(int* p) { return sizeof(*p); }', True),
        ('unevaluated_decltype', 'void f(int* p) { using T=decltype(*p); }', True),
        ('temporary_borrow', 'int f() { const int& r=1; return r; }', True),
        ('temporary_dangling_call', 'SAFETY_RETURNS_BORROW(x) const int& id(const int& x) { return x; } int f() { const int& r=id(1); return r; }', False),
        ('explicit_dtor', 'struct S { ~S() {} }; void f() { S s{}; s.~S(); }', False),
        ('bit_cast', 'bool f(unsigned char n) { return __builtin_bit_cast(bool, n); }', False),
        ('member_pointer', 'struct S { int x=0; }; int f(S& s, int S::*p) { return s.*p; }', False),
        ('virtual_unsafe_override', 'struct B { virtual int f() { return 1; } }; struct D : B { SAFETY_UNSAFE_FN int f() override { return 2; } };', False),
        ('enum_cast', 'enum E { A=0, B=1 }; E f(unsigned n) { return static_cast<E>(n); }', False),
        ('float_narrow', 'float f(double n) { return static_cast<float>(n); }', False),
        ('union_active_member', 'union U { int x; double y; }; int f() { U u{1}; return u.x; }', True),
        ('union_inactive_member', 'union U { int x; double y; }; double f() { U u{1}; return u.y; }', False),
        ('mutable_field', 'struct S { mutable unsigned x=0u; unsigned f() const { return ++x; } };', False),
        ('raw_atomic', 'int f(int* p) { return __atomic_load_n(p, __ATOMIC_RELAXED); }', False),
        ('atomic_storage', 'unsigned f() { _Atomic(unsigned) value; return value; }', False),
        ('inherited_unsafe_constructor', 'struct B { unsafe_fn B(unsigned* p) { *p=1u; } }; struct D : B { using B::B; }; void f(unsigned* p) { D d(p); }', False),
        ('extended_vector', 'using V = int __attribute__((vector_size(16))); V f(V a, V b) { return a+b; }', False),
    ]:
        run(name, prefix+body, ok, needle="" if name=="unsafe_weaken_declaration" else "module-safety:")
    plain = tmp/'plain.cppm'
    policy = tmp/'policy.json'
    policy.write_text('{"version":1,"modules":{"test":"safe","raw":"unsafe"}}')
    policy_flags = ['-Xclang', '-plugin-arg-module-safety', '-Xclang', 'policy='+str(policy)]
    run('policy_partition_conflict', 'export module test:standalone; unsigned f() { return 1u; }', False, 'unsafe', flags=policy_flags+['-fsyntax-only'])
    run('policy_missing_module', 'export module missing; unsigned f() { return 1u; }', False, flags=policy_flags+['-fsyntax-only'])
    run('policy_empty_module', 'export module test;', True, flags=policy_flags+['--precompile', '-o', str(tmp/'test.pcm')])
    plain.write_text('export module plain; export unsigned f() { return 0u; }')
    subprocess.run([clang, '-std=c++20', '--precompile', str(plain), '-o', str(tmp/'plain.pcm')], check=True)
    run('unchecked_pcm', 'export module checked; import plain; unsigned g() { return f(); }', False,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    fingerprint_input = ''.join(hashlib.sha256((pathlib.Path(root)/'src'/name).read_bytes()).hexdigest() for name in ('ModuleSafety.cpp','FlowAnalysis.cpp','FlowAnalysis.h','SafetyContracts.h','SafetyTraversal.h'))
    if plugin == 'native':
        fingerprint_input += 'native-frontend:'+json.loads((pathlib.Path(root)/'frontend/source-hashes.json').read_text())['patch_sha256']
    fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()
    counterfeit = tmp/'counterfeit.cppm'
    counterfeit.write_text('export module counterfeit; namespace __attribute__((annotate("safecpp.module.safe.v3"), annotate("safecpp.module.checker:'+fingerprint+'"))) forged {} export __attribute__((annotate("safecpp.safe"))) unsigned load(unsigned* p) { return *p; }')
    subprocess.run([clang, '-std=c++20', '--precompile', str(counterfeit), '-o', str(tmp/'counterfeit.pcm')], check=True)
    run('counterfeit_pcm', 'export module checked; import counterfeit; unsigned f(unsigned* p) { return load(p); }', False,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    runtime = subprocess.run(base + ['-Xclang', '-plugin-arg-module-safety', '-Xclang', 'safe', '--precompile', root+'/runtime/safety.cppm', '-o', str(tmp/'safety.pcm')], text=True, capture_output=True)
    if runtime.returncode: raise AssertionError(runtime.stderr)
    run('runtime_client', 'export module integration; import safety; export unsigned verify() { std2::vector<unsigned> v; v.push_back(3u); v.push_back(5u); std2::array<unsigned, 2u> a; a.set(0u, v.get(0u)); return std2::checked_add(a[0u], v.pop_back()); }', True,
        flags=['-fprebuilt-module-path='+str(tmp), '--precompile', '-o', str(tmp/'integration.pcm')])
    for name, body, ok in [
        ('move_ok', 'unsigned f() { std2::vector<unsigned> a; a.push_back(2u); std2::vector<unsigned> b(static_cast<std2::vector<unsigned>&&>(a)); return b.get(0u); }', True),
        ('move_helper_use', 'unsigned f() { std2::vector<unsigned> a; std2::vector<unsigned> b(std2::move(a)); return a.get(0u); }', False),
        ('move_use', 'unsigned f() { std2::vector<unsigned> a; std2::vector<unsigned> b(static_cast<std2::vector<unsigned>&&>(a)); return a.get(0u); }', False),
        ('move_borrow', 'unsigned f() { std2::vector<unsigned> a; const auto& r=a; std2::vector<unsigned> b(static_cast<std2::vector<unsigned>&&>(a)); return r.get(0u); }', False),
        ('vector_borrow_mutation', 'unsigned f() { std2::vector<unsigned> a; const auto& r=a; a.push_back(2u); return r.get(0u); }', False),
    ]:
        run(name, 'export module client; import safety; '+body, ok,
            flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('safe_callable', 'export module callback; import safety; unsigned target(unsigned n) { return n; } unsigned f() { std2::callable<target> fn; return fn(2u); }', True,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('unsafe_callable', 'export module callback; import safety; unsafe_fn unsigned target(unsigned n) { return n; } unsigned f() { std2::callable<target> fn; return fn(2u); }', False,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('safe_dynamic_callback', 'export module callback; import safety; unsigned target(unsigned n) { return n; } unsigned f() { std2::function<unsigned(unsigned)> fn(std2::callable<target>{}); auto copy=fn; return copy(2u); }', True,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('unsafe_dynamic_callback', 'export module callback; import safety; unsafe_fn unsigned target(unsigned n) { return n; } unsigned f() { std2::function<unsigned(unsigned)> fn(std2::callable<target>{}); return fn(2u); }', False,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('unsafe_address', unit('unsafe_fn unsigned raw(unsigned n) { return n; } void f() { auto pointer=&raw; }'), True)
    run('separate_api', 'export module separate; export unsigned id(unsigned);', True,
        flags=['--precompile', '-o', str(tmp/'separate.pcm')])
    run('separate_impl', 'module separate; unsigned id(unsigned n) { return n; }', True,
        flags=['-fprebuilt-module-path='+str(tmp), '-c', '-o', str(tmp/'separate_impl.o')])
    run('separate_impl_bad', 'module separate; unsigned id(unsigned n) { int* p=nullptr; return *p; }', False,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    run('separate_client', 'export module consume; import separate; unsigned f() { return id(1u); }', True,
        flags=['-fprebuilt-module-path='+str(tmp), '-fsyntax-only'])
    obj = tmp/'provider.o'
    subprocess.run([clang, '-std=c++20', '-c', str(tmp/'provider.pcm'), '-o', str(obj)], check=True)
    main = tmp/'main.cpp'
    main.write_text('import provider; int main() { return id(4u) == 4u ? 0 : 1; }')
    exe = tmp/'program'
    subprocess.run([clang, '-std=c++20', '-fprebuilt-module-path='+str(tmp), str(main), str(obj), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print(f'{count} compilation cases and module object/link/runtime test passed')
