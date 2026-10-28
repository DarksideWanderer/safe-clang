#!/usr/bin/env python3
"""Native quantified function regions, outlives closure, identity and PCM."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='native-lifetimes-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'lifetimes':'safe','consumer':'safe'}}))
    flags = ['-std=c++20','-fcircle-safety','-fmodule-safety-policy='+str(policy),'-fprebuilt-module-path='+str(tmp)]
    source = tmp/'lifetimes.cppm'
    def check(args, ok=True, needle=''):
        result = subprocess.run([str(clang),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']+args,text=True,capture_output=True)
        if (result.returncode == 0) != ok or needle not in result.stderr:
            raise AssertionError(result.stderr+'\n'+source.read_text())
        if 'PLEASE submit' in result.stderr or 'frontend command failed' in result.stderr:
            raise AssertionError(result.stderr)
        return result
    api = '''#feature on safety
export module lifetimes;
export template<class T> const T^/a identity/(a)(const T^/a value) safe {return ^const value;}
export const unsigned^/b shorten/(a,b where a:b)(const unsigned^/a long_value,const unsigned^/b short_value,bool first){if(first)return ^const long_value;return ^const short_value;}
export const unsigned^/c transitive/(a,b,c where a:b,b:c)(const unsigned^/a long_value,const unsigned^/c short_value){return identity(long_value);}
export const unsigned^/a permanent/(a)(){static const unsigned value=7u;return ^const value;}
export unsigned^/a mut_identity/(a)(unsigned^/a value){return ^value;}
export using MutableCallback=unsigned^/a __attribute__((safe_function)) /(a)(unsigned^/a);
export MutableCallback* mut_callback(){return &mut_identity;}
export using Callback=const unsigned^/a __attribute__((safe_function)) /(a)(const unsigned^/a);
const unsigned^ elided(const unsigned^ value) safe {return ^const value;}
static_assert(__is_same(decltype(&elided),Callback*));
using ElidedCallback=const unsigned^ __attribute__((safe_function)) (const unsigned^);
static_assert(__is_same(ElidedCallback,Callback));
export using Shorten=const unsigned^/b __attribute__((safe_function)) /(a,b where a:b)(const unsigned^/a,const unsigned^/b,bool);
using Renamed=const unsigned^/last __attribute__((safe_function)) /(last,first where first:last)(const unsigned^/first,const unsigned^/last,bool);
using Redundant=const unsigned^/b __attribute__((safe_function)) /(a,b where a:b,a:b,a:a)(const unsigned^/a,const unsigned^/b,bool);
static_assert(__is_same(Shorten,Renamed));static_assert(__is_same(Shorten,Redundant));
static_assert(__is_same(decltype(&shorten),Shorten*));
static_assert(__is_same(decltype(&identity<unsigned>),Callback*));
using Chain=const unsigned^/c __attribute__((safe_function)) /(a,b,c where a:b,b:c)(const unsigned^/a,const unsigned^/c);
using Direct=const unsigned^/b __attribute__((safe_function)) /(a,b where a:b)(const unsigned^/a,const unsigned^/b);
static_assert(__is_same(Chain,Direct));
using Cycle=const unsigned^/b __attribute__((safe_function)) /(a,b where a:b,b:a)(const unsigned^/a,const unsigned^/b);
using Shared=const unsigned^/a __attribute__((safe_function)) /(a)(const unsigned^/a,const unsigned^/a);
static_assert(__is_same(Cycle,Shared));
export Callback* lambda_callback(){return +[](const unsigned^ value)->const unsigned^{return ^const value;};}
export Callback* generic_lambda_callback(){return [](const auto^ value)->const auto^ {return ^const value;};}
export Callback* callback(){return &identity<unsigned>;}
export Shorten* selector(){return &shorten;}
'''
    negative = [
      ('void danger() unsafe {} void caller() safe {danger();}','unsafe'),
      ('#feature off safety\nunsigned f(){return 1u;}','unsupported Circle feature'),
      ('#feature on choice\nunsigned f(){return 1u;}','unsupported Circle feature'),
      ('#feature on\nunsigned f(){return 1u;}','unsupported Circle feature'),
      ('#feature on safety, choice\nunsigned f(){return 1u;}','unsupported Circle feature'),
      ('using F=const unsigned^/a /(a)(const unsigned^/a);F* f(){return [](const auto^ x)->const auto^ {unsigned local=1u;return ^const local;};}','lifetime'),
      ('unsafe_fn void danger(const unsigned^ x){} using F=const unsigned^/a /(a)(const unsigned^/a);F* f(){return [](const auto^ x)->const auto^ {danger(x);return ^const x;};}','unsafe'),

      ('using F=unsigned __attribute__((safe_function))(unsigned);F* f(){return +[](unsigned x) __attribute__((annotate("safecpp.unsafe"),safe_function)) {return x;};}','error:'),
      ('using F=unsigned __attribute__((safe_function))(unsigned);F* f(){return +[](unsigned x) __attribute__((annotate("safecpp.unsafe"))) {return x;};}','error:'),

      ('void f(){auto bad=[](const unsigned^ x)->const unsigned^{unsigned local=1u;return ^const local;};}','lifetime'),
      ('void f(){auto bad=[](const unsigned^ x,const unsigned^ y)->const unsigned^{return ^const x;};}','lifetime'),

      ('void f/(a,b where a:b)(const unsigned^/a x,const unsigned^/b y);void f/(a,b)(const unsigned^/a x,const unsigned^/b y){}','error:'),
      ('struct Base{virtual void f/(a,b where a:b)(const unsigned^/a x,const unsigned^/b y){}};struct Derived:Base{void f/(a,b)(const unsigned^/a x,const unsigned^/b y) override {}};','lifetime'),

      ('const unsigned^/missing f/(a)(const unsigned^/a x){return ^const x;}','unbound lifetime'),
      ('const unsigned^/a f/(a,a)(const unsigned^/a x){return ^const x;}','duplicate'),
      ('const unsigned^/a f/(a)(const unsigned^ x){return ^const x;}','requires a lifetime qualifier'),
      ('const unsigned^ f/(a)(const unsigned^/a x){return ^const x;}','requires a lifetime qualifier'),
      ('const unsigned^/a f/(a,b where a:missing)(const unsigned^/a x){return ^const x;}','unbound lifetime'),
      ('const unsigned^/a f/(a)(const unsigned^/a x){unsigned local=1u;return ^const local;}','lifetime'),
      ('const unsigned^/b f/(a,b)(const unsigned^/a x,const unsigned^/b y){return ^const x;}','lifetime'),
      ('const unsigned^/b f/(a,b where b:a)(const unsigned^/a x,const unsigned^/b y){return ^const x;}','lifetime'),
      ('const unsigned^/a value;','bound function signature'),
      ('__attribute__((annotate("safecpp.borrow.from:x"))) const unsigned^/a f/(a)(const unsigned^/a x){return ^const x;}','cannot mix'),
      ('using Bad=const unsigned^/a __attribute__((returns_borrow(0))) /(a)(const unsigned^/a);','cannot mix'),
      ('using Loose=const unsigned^/a /(a,b)(const unsigned^/a,const unsigned^/b);using Strict=const unsigned^/b /(a,b where a:b)(const unsigned^/a,const unsigned^/b);void f(Strict*p){Loose*q=p;}','error:'),
    ]
    for body, needle in negative:
        source.write_text('export module lifetimes;\n'+body)
        check(flags+[str(source),'-fsyntax-only'],False,needle)
    for opt in ('-O0','-O2'):
        sanitized = [opt,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        source.write_text(api)
        check(flags+sanitized+['--precompile',str(source),'-o',str(tmp/'lifetimes.pcm')])
        client = tmp/'consumer.cppm'
        client.write_text('''export module consumer;import lifetimes;
export unsigned run(){unsigned x=3u,y=5u;auto p=callback();unsigned first=p(^const x);{auto q=lambda_callback();if(q(^const y)!=5u)return 4u;auto g=generic_lambda_callback();if(g(^const x)!=3u)return 5u;}{auto m=mut_callback();auto^ r=m(^x);r=4u;}x=3u;{unsigned inner=9u;if(p(^const inner)!=9u)return 1u;}auto s=selector();{const auto^ r=s(^const x,^const y,false);if(r!=5u)return 2u;}{const auto^ r=transitive(^const x,^const y);if(r!=3u)return 3u;}return first+permanent();}
''')
        check(flags+sanitized+['--precompile',str(client),'-o',str(tmp/'consumer.pcm')])
        for body in [
            'unsigned bad(){unsigned x=1u;auto p=mut_callback();auto^ r=p(^x);unsigned copy=x;return r+copy;}',
            'unsigned bad(){unsigned x=1u;auto p=mut_callback();auto^ r=p(^x);auto^ second=r;return r+second;}',

            'unsigned bad(){unsigned x=1u,y=2u;auto p=selector();const auto^ r=p(^const x,^const y,true);y=3u;return r;}',
            'unsigned bad(){unsigned x=1u,y=2u;const auto^ r=transitive(^const x,^const y);x=3u;return r;}',
            'unsigned bad(){auto p=callback();const auto^ r=p(2u);return r;}',
            'unsigned bad(){const auto^ r=shorten(1u,2u,true);return r;}',
        ]:
            bad_client=tmp/'bad_consumer.cppm'
            bad_client.write_text('export module consumer;import lifetimes;\n'+body)
            check(flags+sanitized+[str(bad_client),'-fsyntax-only'],False)
        objects=[]
        for name in ('lifetimes','consumer'):
            obj=tmp/(name+'.o');objects.append(str(obj))
            check(['-std=c++20','-fprebuilt-module-path='+str(tmp)]+sanitized+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)])
        main=tmp/'main.cpp';main.write_text('import consumer;int main(){return run()==10u?0:1;}')
        binary=tmp/'run'
        check(['--driver-mode=g++','-std=c++20','-fprebuilt-module-path='+str(tmp)]+sanitized+[str(main)]+objects+['-o',str(binary)])
        subprocess.run([str(binary)],check=True,timeout=30)
print('Circle where binders, checked feature assertions, outlives closure/SCC/alpha identity, PCM callbacks and 37 refusals passed at O0/O2 under ASan/UBSan')
