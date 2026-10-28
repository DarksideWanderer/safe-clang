#!/usr/bin/env python3
"""Executable checks for first-class borrow storage and affine transfer."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='circle-borrow-values-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'borrow_values': 'safe'}}))
    flags = ['-std=c++20', '-fcircle-safety', '-fcircle-borrow-values',
             '-fmodule-safety-policy='+str(policy),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    source = tmp/'borrow_values.cppm'

    def check(arguments, ok=True):
        result = subprocess.run([str(clang)]+arguments, text=True, capture_output=True)
        if (result.returncode == 0) != ok:
            raise AssertionError(result.stderr+'\n'+source.read_text())
        if 'PLEASE submit' in result.stderr or 'frontend command failed' in result.stderr:
            raise AssertionError(result.stderr)
        return result

    body = '''export module borrow_values;
export const unsigned^/a identity/(a)(const unsigned^/a value) safe { return value; }
export unsigned^/a transfer/(a)(unsigned^/a value) safe { return rel value; }
export template<class T> T implicit_transfer(T value) safe { return value; }
export template<class T> const T^ inferred(const T^ value) safe { return value; }
export using Identity = const unsigned^/a __attribute__((safe_function)) /(a)(const unsigned^/a);
static_assert(__is_same(decltype(&identity), Identity*));
static_assert(__is_same(decltype(&inferred<unsigned>), Identity*));
template<class T> struct Kind { static constexpr unsigned value=0u; };
template<class T> struct Kind<T*> { static constexpr unsigned value=1u; };
template<class T> struct Kind<T^> { static constexpr unsigned value=2u; };
static_assert(Kind<const unsigned^>::value==2u);
static_assert(Kind<const unsigned*>::value==1u);
export namespace cells {
struct Cell {
 unsigned value;
 unsigned get(const self^) safe { return self->value; }
};
template<class T> struct GenericCell {
 T value;
 T get(const self^) safe { return self->value; }
};
const unsigned^/a project/(a)(const Cell^/a loan) safe { return ^const loan->value; }
unsigned load(const Cell^ loan) safe { return loan->value; }
}
template<class T> unsigned qualified_read(const T^ value) safe {return *value;}
export unsigned run() safe {
  unsigned deduction_value=29u;
  if (qualified_read(29u)!=29u || qualified_read(deduction_value)!=29u || qualified_read(^deduction_value)!=29u || qualified_read(^const deduction_value)!=29u) return 0u;
  cells::Cell cell{17u};
  const cells::Cell^ cell_loan=^const cell;
  auto field_loan=cells::project(cell_loan);
  auto member=&cells::Cell::get;
  if (*field_loan!=17u || load(cell_loan)!=17u || member(cell_loan)!=17u)
    return 0u;
  cells::GenericCell<unsigned> generic{19u};
  auto generic_member=&cells::GenericCell<unsigned>::get;
  if (generic_member(^const generic)!=19u) return 0u;
  unsigned first=3u, second=5u;
  const unsigned^ loan=^const first;
  auto copied=loan;
  auto returned=inferred(identity(copied));
  static_assert(__is_same(decltype(copied),const unsigned^));
  static_assert(!__is_same(const unsigned^,const unsigned&));
  static_assert(!__is_same(const unsigned^,const unsigned*));
  static_assert(sizeof(const unsigned^)==sizeof(void*));
  const unsigned^ values[2]={^const first,^const second};
  const unsigned^ rebound=^const first;
  rebound=^const second;
  if (*rebound!=5u) return 0u;
  unsigned a=1u,b=2u;
  unsigned^ handle=^a;
  unsigned^ incoming=^b;
  handle=rel incoming;
  *handle=6u;
  a=4u;
  if (*handle!=6u || a!=4u) return 0u;
  unsigned sum=*returned + *values[0] + *values[1];
  unsigned target=7u;
  unsigned^ unique=^target;
  auto moved=rel unique;
  auto transferred=implicit_transfer<unsigned^>(transfer(rel moved));
  static_assert(__is_same(decltype(transferred),unsigned^));
  *transferred=11u;
  return sum + *transferred;
}
'''
    for optimization in ('-O0','-O2'):
        source.write_text(body)
        checked = flags+[optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        pcm=tmp/'borrow_values.pcm'
        check(checked+['--precompile',str(source),'-o',str(pcm)])
        obj=tmp/'borrow_values.o'
        check(checked+['-c',str(pcm),'-o',str(obj)])
        main=tmp/'main.cpp'
        main.write_text('import borrow_values;int main(){return run()==22u?0:1;}')
        executable=tmp/'run'
        check(['--driver-mode=g++','-std=c++20',optimization,
               '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22',
               '-fsanitize=address,undefined','-fno-sanitize-recover=all',
               '-fprebuilt-module-path='+str(tmp),str(main),str(obj),'-o',str(executable)])
        subprocess.run([str(executable)],check=True,timeout=30)
    negatives = [
      'template<class T>const T^ view(const T^ p)safe{return p;}void f()safe{auto q=view(17u);unsigned result=*q;}',
      'void mutate(unsigned^ p)safe{*p=2u;}void f()safe{mutate(17u);}',
      'template<class T>const T^ view(const T^ p)safe{return p;}void f()safe{unsigned n=1u;auto q=view(^n);n=2u;unsigned result=*q;}',
      'template<class T>void mutate(T^ p)safe{*p=2u;}void f()safe{const unsigned n=1u;mutate<unsigned>(^const n);}',
      'template<class T>T bad(T p)safe{unsigned local=1u;return ^local;}void f()safe{unsigned n=1u;auto p=bad<unsigned^>(^n);*p=2u;}',
      'template<class T>T forward(T p)safe{return p;}void f()safe{unsigned n=1u;unsigned^ p=^n;auto q=forward<unsigned^>(rel p);*p=2u;*q=3u;}',
      'void f()safe{unsigned n=1u;unsigned^ x=^n;auto y=x;}',
      'void f()safe{unsigned n=1u;unsigned^ x=^n;auto y=rel x;*x=2u;}',
      'void f()safe{unsigned n=1u;const unsigned^ x=^const n;n=2u;unsigned y=*x;}',
      'void f()safe{const unsigned^ x;}',
      'void f()safe{const unsigned^ x{};}',
      'void f()safe{unsigned n=1u;const unsigned^ x[2]={^const n};}',
      'void f()safe{const unsigned^ x=nullptr;}',
      'void f()safe{unsigned n=1u;const unsigned^ x=^const n;const unsigned* p=x;}',
      'void f()safe{unsigned n=1u;const unsigned^ x[1]={^const n};n=2u;unsigned y=*x[0];}',
      'void f()safe{unsigned n=1u;unsigned^ x[1]={^n};unsigned^ y=^n;*x[0]=2u;*y=3u;}',
      'const unsigned^/a f/(a)(const unsigned^/a p) safe {unsigned n=1u;return ^const n;}',
      'const unsigned^/b f/(a,b)(const unsigned^/a p,const unsigned^/b q) safe {return p;}',
      'unsigned^/a f/(a)(unsigned^/a p) safe {return rel p;} void g()safe{unsigned n=1u;unsigned^ p=^n;auto q=f(p);*q=2u;}',
      'const unsigned^/a f/(a)(const unsigned^/a p) safe {return p;} void g()safe{unsigned n=1u;auto p=f(^const n);n=2u;unsigned x=*p;}',
      'void f()safe{unsigned a=1u,b=2u;const unsigned^ p=^const a;p=^const b;b=3u;unsigned x=*p;}',
      'void f()safe{unsigned a=1u,b=2u;unsigned^ p=^a;unsigned^ q=^b;p=^b;*p=3u;*q=4u;}',
      'void f()safe{unsigned a=1u,b=2u;unsigned^ p=^a;auto q=rel p;p=^b;*p=3u;*q=4u;}',
      'template<class T>const T^ bad(const T^ p)safe{T local{};return ^const local;}void f()safe{unsigned n=1u;auto p=bad(^const n);unsigned x=*p;}',
      'constexpr unsigned index(){return __builtin_is_constant_evaluated()?0u:9u;}void f()safe{unsigned n=1u;const unsigned^ a[1]={^const n};unsigned x=*a[index()];}',
      'struct C{unsigned value;};void f(const C^ p)safe{p->value=2u;}',
      'struct C{unsigned value;};const unsigned^/a project/(a)(const C^/a p)safe{return ^const p->value;}void f()safe{C c{1u};auto p=project(^const c);c.value=2u;unsigned x=*p;}',
      'struct C{unsigned value;};void f()safe{C c{1u};C^ p=^c;const unsigned^ q=^const p->value;p->value=2u;unsigned x=*q;}',
      'struct Index{unsigned value;constexpr Index():value(__builtin_is_constant_evaluated()?0u:9u){}};void f()safe{unsigned n=1u;const unsigned^ a[1]={^const n};const Index i;unsigned x=*a[i.value];}',
      'void f()safe{unsigned n=1u;const unsigned^ a[1]={^const n};{unsigned inner=2u;a[0]=^const inner;}unsigned x=*a[0];}',
      'unsigned read(unsigned^ p)safe{return *p;}void f()safe{unsigned n;unsigned result=read(^n);}',
      'void f()safe{unsigned n;auto p=^n;}',
    ]
    for negative in negatives:
        source.write_text('export module borrow_values;\n'+negative)
        check(flags+['-fsyntax-only',str(source)],False)
print('First-class borrow identity/storage, shared copy, affine transfer, arrays, function/template lifetimes, class arrows/ADL, rebinding and 32 refusals passed at O0/O2 under ASan/UBSan; constant borrow-array bounds panics are executed by native_panic_checks.py')
