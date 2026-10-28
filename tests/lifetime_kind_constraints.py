#!/usr/bin/env python3
"""Static region and carried-type lifetime contracts, including indirect calls."""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT=pathlib.Path(__file__).resolve().parent.parent
clang=pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'llvm-build/bin/clang'
API='''export module kinds;
export const unsigned permanent=31u;
export const unsigned^/L make_permanent/(where L: static)() safe {return ^const permanent;}
export void retain/(where L: static)(const unsigned^/L value) safe {}
export const unsigned^/L identity/(where L: static)(const unsigned^/L value) safe {return value;}
export using Callback=void __attribute__((safe_function)) /(where L: static)(const unsigned^/L);
static_assert(__is_same(decltype(&retain),Callback*));
using Renamed=void __attribute__((safe_function)) /(where region: static)(const unsigned^/region);
static_assert(__is_same(Callback,Renamed));
export template<class T+> struct Holder {T value;};
export using Loan=Holder<const unsigned^>;
export template<class T+> unsigned accept/(where T: static)(T value) safe {return 17u;}
export template<class T+> unsigned forward/(where T: static)(T value) safe {return accept(rel value);}
export template<class ...Ts+> unsigned pack/(where Ts...: static)(Ts... values) safe {return sizeof...(Ts);}
export struct Receiver {
 unsigned hold/(where L: static)(const unsigned^/L value) const safe {return *value;}
};
export struct Gate {
 template<class T+> Gate/(where T: static)(T value) safe {}
};
export unsigned coexisting() safe {
 auto stable=^const permanent;
 Loan value{^const permanent};
 return *identity(stable)+forward(rel value)+*stable;
}
export unsigned run() safe {
 retain(^const permanent);
 auto callback=&retain; callback(^const permanent);
 unsigned a,d;
 {
  auto stable=^const permanent;
  Gate guard(stable);
  Receiver receiver{};
  if(receiver.hold(stable)!=31u) return 0u;
  a=*identity(stable);
  d=pack(1u,stable);
 }
 unsigned local=1u;
 unsigned b=accept(local);
 Loan value{^const permanent};
 unsigned c=forward(rel value);
 return a+b+c+d;
}
'''
NEGATIVES=(
 ('void caller() safe {unsigned local=1u;retain(^const local);}', 'static lifetime contract'),
 ('void caller() unsafe {unsigned local=1u;retain(^const local);}', 'static lifetime contract'),
 ('void caller() safe {unsigned local=1u;unsafe {retain(^const local);}}', 'static lifetime contract'),
 ('void caller() safe {unsigned local=1u;Callback* f=&retain;f(^const local);}', 'static lifetime contract'),
 ('void caller() unsafe {unsigned local=1u;auto f=&retain;f(^const local);}', 'static lifetime contract'),
 ('void caller() safe {unsigned local=1u;accept(^const local);}', 'static lifetime contract'),
 ('void caller() unsafe {unsigned local=1u;accept(^const local);}', 'static lifetime contract'),
 ('void caller() safe {unsigned local=1u;Loan x{^const local};forward(rel x);}', 'static lifetime contract'),
 ('void caller() safe {unsigned local=1u;pack(^const permanent,1u,^const local);}', 'static lifetime contract'),
 ('void caller() unsafe {unsigned local=1u;pack(1u,^const local,2u);}', 'static lifetime contract'),
 ('void caller() safe {unsigned local=1u;Gate g(^const local);}', 'static lifetime contract'),
 ('void caller() unsafe {unsigned local=1u;Gate g(^const local);}', 'static lifetime contract'),
 ('void caller() safe {unsigned local=1u;Receiver r{};r.hold(^const local);}', 'static lifetime contract'),
 ('void caller() unsafe {unsigned local=1u;Receiver r{};r.hold(^const local);}', 'static lifetime contract'),
 ('void caller() safe {using Shared=const unsigned^;unsigned local=1u;auto f=&pack<Shared,unsigned>;f(^const local,1u);}', 'static lifetime contract'),
 ('template<class T+> void local_storage/(where T: static)(T value) safe {retain(^const value);} void caller() safe {local_storage(1u);}', 'static lifetime contract'),
 ('using Handle=const unsigned^;void retain_handle/(where L: static)(const Handle^/L value) safe {} template<class T+> void slot/(where T: static)(T value) safe {retain_handle(^const value);} void caller() safe {slot(^const permanent);}', 'static lifetime contract'),
 ('void caller() safe {Loan value{^const permanent};const Loan^ stored=^const value;forward(rel value);if(*stored->value==0u) {}}', 'storage borrow'),
 ('void caller() safe {extern Loan unknown;accept(cpy unknown);}', 'static lifetime contract'),
 ('void caller() unsafe {extern Loan unknown;static unsigned initialized_bad=accept(cpy unknown);}', 'static lifetime contract'),
 ('struct Base {virtual void f/(where L: static)(const unsigned^/L value) safe {}};struct Derived:Base {void f/(L)(const unsigned^/L value) safe override {}};', 'static lifetime constraints'),
 ('struct Base {virtual void f/(L)(const unsigned^/L value) unsafe {}};struct Derived:Base {void f/(where L: static)(const unsigned^/L value) unsafe override {}};', 'static lifetime constraints'),
 ('void caller() unsafe {thread_local const unsigned value=1u;retain(^const value);}', 'static lifetime contract'),
 ('void caller(const unsigned^ value) safe {retain(value);}', 'static lifetime contract'),
 ('void caller() safe {using Loose=void __attribute__((safe_function))(const unsigned^);Loose* f=&retain;}', 'error:'),
 ('void caller() unsafe {using Loose=void(const unsigned^);auto f=reinterpret_cast<Loose*>(&retain);}', 'cannot erase static lifetime contracts'),
 ('void caller() unsafe {void* erased=(void*)&retain;}', 'cannot erase static lifetime contracts'),
 ('void source(const unsigned^) unsafe;void caller() unsafe {auto invented=reinterpret_cast<Callback*>(&source);}', 'static lifetime contracts'),
 ('unsigned make() unsafe {unsigned local=1u;return accept(^const local);} unsigned result=make();', 'static lifetime contract'),
)
UNMODELED=(
 ('template<class T> struct Holder {T value;}; template<class T+> void f/(where T: static)(T direct, Holder<T> projected) safe {}', 'static kind type projection'),
 ('template<class T+> void f/(where T: static)(T direct, const T^ projected) safe {}', 'static kind type projection'),
 ('template<class T+> struct Outer {void f/(where T: static)(T value) safe {}};', 'static kind type projection'),
 ('template<class T+> void f/(where T: static)() safe {}', 'static kind type projection'),
 ('template<class T> struct Holder {T value;}; template<class T+> void f/(where T: static)(Holder<T> value) safe {}', 'static kind type projection'),
 ('template<class ...Ts+> void f/(where Ts: static)(Ts... value) safe {}', 'pack constraint'),
 ('void f/(where L: M)(const unsigned^/L value) safe {}', 'not yet modeled at call sites'),
 ('void f/(where unknown: static)(unsigned value) safe {}', 'unbound lifetime'),
)
with tempfile.TemporaryDirectory(prefix='lifetime-kind-') as directory:
    tmp=pathlib.Path(directory)
    policy=tmp/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'kinds':'safe','consumer':'safe','unsafe_client':'unsafe'}}))
    flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values',
           '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22',
           '-fmodule-safety-policy='+str(policy),'-fprebuilt-module-path='+str(tmp)]
    source=tmp/'kinds.cppm'
    def check(args, ok=True, diagnostic=None):
        result=subprocess.run([str(clang)]+args,capture_output=True,text=True,timeout=120)
        assert (result.returncode==0)==ok,result.stderr+'\n'+source.read_text()
        assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr,result.stderr
        if diagnostic: assert diagnostic in result.stderr,result.stderr
        return result
    for optimization in ('-O0','-O2'):
        for sanitized in (False,True):
            options=flags+[optimization]
            if sanitized: options+=['-fsanitize=address,undefined','-fno-sanitize-recover=all']
            source.write_text(API)
            pcm=tmp/'kinds.pcm';obj=tmp/'kinds.o';binary=tmp/'kinds'
            check(options+['--precompile',str(source),'-o',str(pcm)])
            check(options+['-c',str(pcm),'-o',str(obj)])
            consumer=tmp/'consumer.cpp'
            consumer.write_text('import kinds;\nint main(){return run()==67u && coexisting()==79u ? 0 : 1;}\n')
            check(options+[str(consumer),str(obj),'-o',str(binary)])
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=60)
            assert run.returncode==0,(run.returncode,run.stdout,run.stderr)
            unsafe_options=[option for option in options
                            if option not in ('-fcircle-safety','-fcircle-borrow-values')]+['-fmodule-unsafe']
            unsafe_source=tmp/'unsafe_client.cppm'; unsafe_pcm=tmp/'unsafe_client.pcm'; unsafe_obj=tmp/'unsafe_client.o'
            unsafe_source.write_text('export module unsafe_client;import kinds;\n'
                'const unsigned initialized=accept(make_permanent());\n'
                'export unsigned good(){retain(make_permanent());return initialized+accept(1u)-17u;}')
            check(unsafe_options+['--precompile',str(unsafe_source),'-o',str(unsafe_pcm)])
            check(unsafe_options+['-c',str(unsafe_pcm),'-o',str(unsafe_obj)])
            consumer.write_text('import unsafe_client;\nint main(){return good()==17u?0:1;}')
            check(unsafe_options+[str(consumer),str(unsafe_obj),str(obj),'-o',str(binary)])
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=60)
            assert run.returncode==0,(run.returncode,run.stdout,run.stderr)
    for body,diagnostic in NEGATIVES:
        for imported in (False,True):
            target=tmp/'negative.cpp' if imported else source
            target.write_text(('import kinds;\n' if imported else API)+'\n'+body)
            # Use the options matching the final PCM for imported clients.
            check((options if imported else flags)+['-fsyntax-only',str(target)],False,diagnostic)
    unsafe_options=[option for option in options
                    if option not in ('-fcircle-safety','-fcircle-borrow-values')]+['-fmodule-unsafe']
    for body,diagnostic in (
        ('extern Loan value;void bad(){accept(value);}', 'static lifetime contract'),
        ('void bad(){auto erased=reinterpret_cast<void(*)()>(&retain);}', 'cannot erase static lifetime contracts'),
        ('extern Loan value;unsigned bad=accept(value);', 'static lifetime contract'),
    ):
        unsafe_source.write_text('export module unsafe_client;import kinds;\n'+body)
        check(unsafe_options+['-fsyntax-only',str(unsafe_source)],False,diagnostic)
    for body,diagnostic in UNMODELED:
        source.write_text('export module kinds;\n'+body)
        check(flags+['-fsyntax-only',str(source)],False,diagnostic)
    source.write_text('export module kinds;\nconst unsigned^/b shorten/(a,b where a:b)(const unsigned^/a x,const unsigned^/b y) safe {return ^const x;}')
    check([flag for flag in flags if flag!='-fcircle-borrow-values']+['-fsyntax-only',str(source)])
    source.write_text(source.read_text().replace('return ^const x;', 'return x;'))
    check(flags+['-fsyntax-only',str(source)])
print('Static region/type/pack contracts, constructors and forwarding: O0/O2 PCM ASan/UBSan; '
      '58 local/PCM and three command-unsafe refusals including unsafe callers and contract erasure/invention; eight unmodeled signatures rejected explicitly')
