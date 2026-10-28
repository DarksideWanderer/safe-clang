#!/usr/bin/env python3
"""Native borrow identity, AST operations, inference and checked PCM use."""
import json
import pathlib
import re
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / 'llvm-build/bin/clang'
driver = [str(clang), '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
with tempfile.TemporaryDirectory(prefix='native-caret-') as directory:
    tmp = pathlib.Path(directory)
    source = tmp / 'caret.cppm'
    policy = tmp / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'caret': 'safe', 'consumer': 'safe'}}))
    runtime_flags = ['-O2', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    flags = ['-std=c++20'] + runtime_flags + ['-fmodule-safe', '-fmodule-safety-policy=' + str(policy),
             '-fprebuilt-module-path=' + str(tmp)]

    def invoke(arguments, success=True, needle=''):
        result = subprocess.run(driver + arguments, capture_output=True, text=True)
        assert (result.returncode == 0) == success, result.stderr + source.read_text()
        assert needle in result.stderr, result.stderr
        assert 'PLEASE submit' not in result.stderr, result.stderr

    source.write_text('''export module caret;
export using Shared = const unsigned^;
export using Unique = unsigned^;
export struct View { const unsigned^ value; };
static_assert(!__is_same(unsigned^, unsigned&));
static_assert(!__is_same(const unsigned^, const unsigned&));
static_assert(!__is_same(unsigned^, const unsigned^));
static_assert(__is_same(Unique, unsigned^));
static_assert(__is_same(Unique&, Unique));
static_assert(!__is_same(Unique&, unsigned&));
static_assert(!__is_same(unsigned(unsigned^), unsigned(unsigned&)));
template<class T> struct Identity { using type = T; };
template<class T> concept Loan = __is_reference(T);
static_assert(__is_same(Identity<unsigned^>::type, unsigned^));
static_assert(!__is_same(Identity<unsigned^>::type, unsigned&));
export unsigned select(unsigned^ value) { return 1u; }
export unsigned select(unsigned& value) { return 2u; }
export __attribute__((annotate("safecpp.borrow.from:value")))
const unsigned^ lend(const unsigned^ value) { return ^const value; }
export template<class T> T read(const T^ value) { return value; }
export template<class T> T shared(const T^ value) { const T^ r = ^const value; return r; }
export unsigned run() {
  static constexpr unsigned constant_owner = 3u;
  constexpr const unsigned^ constant_loan = ^const constant_owner;
  static_assert(constant_loan == 3u);
  static_assert(__is_same(decltype(constant_loan), const unsigned^));
  unsigned x=1u;
  { unsigned y=2u;auto a=^x;auto b=^y;
    static_assert(__is_same(decltype(true?a:b),unsigned^));
    static_assert(__is_same(decltype((0u,a)),unsigned^));
    static_assert(__is_same(decltype(a=1u),unsigned^));
    static_assert(__is_same(decltype(++a),unsigned^));
  }
  { struct Pair{unsigned a=1u,b=2u;};struct Parts{unsigned^ a;unsigned^ b;};
    Pair owner;Parts parts{^owner.a,^owner.b};parts.a=3u;
    if(parts.b!=2u)return 5u;
  }
  { unsigned^ r=^x; r=7u; }
  { View view{^const x}; if(view.value!=7u)return 4u; }
  { Loan auto constrained=^x;
    static_assert(__is_same(decltype(constrained), unsigned^));
  }
  { auto^ inferred=^const x; if(inferred!=7u)return 1u; }
  { auto inferred=^x;
    static_assert(__is_same(decltype(inferred), unsigned^));
    static_assert(__is_same(decltype((inferred)), unsigned^));
    static_assert(__is_same(decltype(^x), unsigned^));
    static_assert(__is_same(decltype(^const x), const unsigned^));
    if(select(inferred)!=1u)return 2u;
  }
  if(select(x)!=2u || select(^x)!=1u)return 3u;
  static_assert(__is_same(decltype(lend(^const x)), const unsigned^));
  const unsigned^ r=^const x;
  return read(r) ^ shared(x);
}
''')
    invoke(flags + ['--precompile', str(source), '-o', str(tmp / 'caret.pcm')])
    dumped = subprocess.run(driver + flags + ['-fsyntax-only', '-Xclang',
                             '-ast-dump', str(source)], capture_output=True, text=True, check=True)
    assert re.search(r"UnaryOperator[^\n]*'\^'", dumped.stdout), dumped.stdout
    assert re.search(r"UnaryOperator[^\n]*'\^const'", dumped.stdout), dumped.stdout
    assert 'CXXStaticCastExpr' not in dumped.stdout
    invoke(['-std=c++20'] + runtime_flags + ['-c', str(tmp / 'caret.pcm'), '-o', str(tmp / 'caret.o')])
    consumer = tmp / 'consumer.cppm'
    consumer.write_text('''export module consumer; import caret;
static_assert(__is_same(Shared, const unsigned^));
static_assert(!__is_same(Shared, const unsigned&));
static_assert(__is_same(Unique, unsigned^));
static_assert(!__is_same(Unique, unsigned&));
export unsigned check(){unsigned x=3u; {auto r=^x;if(select(r)!=1u)return 0u;}
  static_assert(__is_same(decltype(lend(^const x)), const unsigned^));
  Shared r=lend(^const x); return read(r);}
''')
    invoke(flags + ['--precompile', str(consumer), '-o', str(tmp / 'consumer.pcm')])
    invoke(['-std=c++20'] + runtime_flags + ['-fprebuilt-module-path=' + str(tmp), '-c', str(tmp / 'consumer.pcm'), '-o', str(tmp / 'consumer.o')])
    main = tmp / 'main.cpp'
    main.write_text('import caret; import consumer; int main(){return run()!=0u || check()!=3u;}')
    binary = tmp / 'run'
    invoke(['-std=c++20'] + runtime_flags + ['-fprebuilt-module-path=' + str(tmp), str(main),
            str(tmp / 'caret.o'), str(tmp / 'consumer.o'), '-o', str(binary)])
    subprocess.run([str(binary)], check=True)
    cases = [
        ('unsigned f(){unsigned x=1u;const unsigned^ r=^const x;x=2u;return r;}', 'borrow'),
        ('unsigned f(){unsigned x=1u;unsigned^ a=^x;unsigned^ b=^x;a=2u;return b;}', 'borrow'),
        ('const unsigned^ f(){unsigned x=1u;return ^const x;}', 'borrow'),
        ('void f(){const unsigned^ r=^const 1u;}', 'lvalue owner'),
        ('void f(){unsigned x=1u;unsigned^ r=^const x;}', 'const'),
        ('void f(){unsigned x=1u;const unsigned^ r=^const x;r=2u;}', 'const'),
        ('void f(){unsigned x=1u;auto^ r=^const x;r=2u;}', 'const'),
        ('template<class T> void bad(T^ x){T^ r=^const x;} void f(){unsigned x=1u;bad(x);}', 'const'),
        ('unsigned f(unsigned^ x){return x;} using Legacy=unsigned(unsigned&); Legacy* p=&f;', 'type mismatch at 1st parameter'),
        ('void f(){unsigned x=1u;auto r=^const x;x=2u;unsigned y=r;}', 'borrow'),
        ('void f(){unsigned x=1u;auto r=^const x;r=2u;}', 'const'),
        ('template<class T> void bad(T^ x){auto r=^const x;r=2u;} void f(){unsigned x=1u;bad(x);}', 'const'),
        ('void f(){unsigned x=1u;unsigned^ a=^x;unsigned& b=x;a=2u;unsigned y=b;}', 'borrow'),
        ('struct View{const unsigned^ value;};unsigned f(){unsigned x=1u;View v{^const x};x=2u;return v.value;}', 'borrow'),
        ('template<class T> concept Owned=!__is_reference(T);void f(){unsigned x=1u;Owned auto r=^x;}', "does not satisfy 'Owned'"),
        ('struct S{unsigned x:3;};void f(){S s{};auto r=^s.x;}', 'addressable'),
        ('unsigned f(unsigned x){return x;}unsigned f(){return 1u;}void g(){auto r=^f;}', 'resolved owner'),
        ('struct View{const unsigned^ value;};__attribute__((annotate("safecpp.borrow.from:value"))) const View^ f(bool c,const View^ value){View local=value;return c?^const local:^const value;}', 'lifetime'),
        ('struct X{unsigned take() && {return 1u;}};unsigned f(){X x;X^ r=^x;return static_cast<X&&>(r).take();}', 'through a borrow'),
        ('struct X{unsigned take() && {return 1u;}};unsigned f(){X x;return static_cast<X&&>(^x).take();}', 'through a borrow'),
    ]
    for body, needle in cases:
        source.write_text('export module caret;' + body)
        invoke(flags + ['-fsyntax-only', str(source)], False, needle)
    source.write_text('export module caret; void f(){unsigned x=1u;unsigned^ r=^x;}')
    invoke(['-std=c++20', '-fsyntax-only', str(source)], False)
    # Domain preference must not make an ordinary implicit object argument
    # worse than a nonmember reference parameter. That broke LLVM's ostream
    # and string overloads even when checked mode was disabled.
    legacy = tmp/'ordinary_overloads.cpp'
    overloads = '''struct Text{Text(const char*){}};
struct Output{unsigned operator<<(const char*){return 1u;}};
unsigned operator<<(Output&,const Text&){return 2u;}
'''
    legacy.write_text(overloads+'int main(){Output out;return (out<<"test")==1u?0:1;}')
    ordinary = tmp/'ordinary'
    invoke(['-std=c++20', str(legacy), '-o', str(ordinary)])
    subprocess.run([str(ordinary)], check=True)
    legacy.write_text('struct X{unsigned n=7u;unsigned take() && {return n;}};int main(){X x;static_cast<X&&>(x).take();return x.n==7u?0:1;}')
    invoke(['-std=c++20', str(legacy), '-o', str(ordinary)])
    subprocess.run([str(ordinary)], check=True)
    source.write_text('export module caret;'+overloads+'unsigned f(){Output out;return out<<"test";}')
    invoke(flags+['-fsyntax-only', str(source)])
print('Native borrow identity, operations, auto/decltype/concepts, overloads, templates, fields, XOR, PCM execution and 21 refusals passed')
