#!/usr/bin/env python3
"""Exercise the actual adapter concepts independently of pending Circle syntax."""
import json
import pathlib
import subprocess
import sys
import tempfile
root=pathlib.Path(__file__).resolve().parent.parent
clang=pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'llvm-build/bin/clang'
header=(root/'include/std2/std2.h').read_text()
a=header.index('template<class I> struct iterator_traits;')
b=header.index('////////////////////////////////////////////////////////////////////////////////\n// slice.h',a)
concepts=header[a:b]
with tempfile.TemporaryDirectory(prefix='std2-concepts-') as directory:
    tmp=pathlib.Path(directory)
    policy=tmp/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'adapter':'safe'}}))
    source=tmp/'adapter.cppm'
    source.write_text('''module;
#include <concepts>
export module adapter;
namespace std2 {
template<class T> struct optional { T value; };
'''+concepts+'''
struct Good { unsigned value; };
struct Bad { unsigned value; };
struct Range { unsigned value; };
template<> struct iterator_traits<Good> {
 using item_type=unsigned;
 static optional<unsigned> next(Good& value) safe { return {value.value}; }
};
template<> struct iterator_traits<Bad> {
 using item_type=unsigned;
 static unsigned next(Bad& value) safe { return value.value; }
};
template<> struct make_iter_traits<Range> {
 using iter_type=Good; using iter_mut_type=Good; using into_iter_type=Good;
 static Good iter(const Range& r) safe { return {r.value}; }
 static Good iter_mut(Range& r) safe { return {r.value}; }
 static Good into_iter(Range r) safe { return {r.value}; }
};
static_assert(iterator<Good>);
static_assert(!iterator<Bad>);
static_assert(make_iter<Range>);
static_assert(!make_iter<Bad>);
}
''')
    flags=['-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy)]
    def check(args,ok=True):
        r=subprocess.run([str(clang)]+args,text=True,capture_output=True)
        if (r.returncode==0)!=ok or 'PLEASE submit' in r.stderr:
            raise AssertionError(r.stderr)
    pcm=tmp/'adapter.pcm'
    check(flags+['--precompile',str(source),'-o',str(pcm)])
    check(flags+['-c',str(pcm),'-o',str(tmp/'adapter.o')])
    source.write_text('''export module adapter;
struct A { unsigned x; };
template<class T> concept CopyRef = requires(T& value) { rel value; };
static_assert(!CopyRef<A>);
''')
    check(flags+['-fsyntax-only',str(source)])
    source.write_text(source.read_text()+'''A global;
void f() safe { auto x=rel global; }
''')
    check(flags+['-fsyntax-only',str(source)],False)
print('Adapter associated types, consuming/mutable/shared operations and rejected wrong results passed; evaluated global relocation remains rejected')
