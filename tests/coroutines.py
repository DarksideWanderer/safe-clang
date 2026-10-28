#!/usr/bin/env python3
"""Owned scalar coroutine frames, suspension loans and cancellation."""
import pathlib,subprocess,sys,tempfile
clang,plugin,root=sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safecpp-coroutines-') as directory:
    tmp=pathlib.Path(directory)
    flags=['-std=c++20','-O2','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fprebuilt-module-path='+str(tmp),'-I'+root+'/include']
    checked=[clang]+flags+['-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe']
    source=tmp/'coroutine_checks.cppm'
    def compile(args,ok=True,needle=''):
        r=subprocess.run(args,text=True,capture_output=True)
        assert (r.returncode==0)==ok and needle in r.stderr,r.stderr+'\n'+(source.read_text()if source.exists()else str(args))
        assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr,r.stderr
    for name,file in [('safety','safety.cppm'),('safety_coroutines','coroutines.cppm')]:
        compile(checked+['--precompile',root+'/runtime/'+file,'-o',str(tmp/(name+'.pcm'))])
    prefix='''module;
#include "module_safety.h"
#include <coroutine>
export module coroutine_checks;import safety;import safety_coroutines;
'''
    source.write_text(prefix+'''std2::generator<unsigned> sequence(unsigned count){
      std2::vector<unsigned> storage;storage.push_back(42u);
      unsigned x=storage.get(0u);const unsigned&r=x;
      for(unsigned i=0u;i<count;++i){co_yield i;}
      co_yield r;co_return;
    }
    std2::generator<unsigned> awaited(){co_await std2::suspend{};co_yield 9u;co_return;}
    export unsigned run(){
      auto values=sequence(3u);
      for(unsigned n=0u;n<3u;++n){if(!values.next() || values.value()!=n)return 1u;}
      auto moved=std2::move(values);
      if(!moved.next() || moved.value()!=42u)return 2u;
      if(moved.next() || moved.next())return 3u;
      {auto cancelled=sequence(100u);if(!cancelled.next())return 4u;}
      auto suspended=awaited();if(!suspended.next() || suspended.value()!=9u || suspended.next())return 5u;
      return 0u;
    }''')
    compile(checked+['--precompile',str(source),'-o',str(tmp/'coroutine_checks.pcm')])
    objects=[]
    for name in ['safety','safety_coroutines','coroutine_checks']:
        obj=tmp/(name+'.o');objects.append(str(obj));compile([clang]+flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)])
    main=tmp/'main.cpp';main.write_text('import coroutine_checks;int main(){return int(run());}')
    binary=tmp/'run';compile([clang]+flags+[str(main)]+objects+['-o',str(binary)]);subprocess.run([str(binary)],check=True,timeout=30)
    for body,needle in [
      ('std2::generator<unsigned> sequence(){co_yield 1u;co_return;}void f(){auto first=sequence();auto second=std2::move(first);first.next();}', 'moved'),
      ('std2::generator<unsigned> f(){co_await std::suspend_always{};co_return;}', 'audited suspension'),
      ('std2::generator<unsigned> f(const unsigned&x){co_yield x;co_return;}','borrowed parameters'),
      ('struct Borrow{const unsigned&ref;};std2::generator<unsigned> f(Borrow b){co_yield b.ref;co_return;}','borrowed parameters'),
      ('struct Owner{unsigned value=1u;std2::generator<unsigned> f(){co_yield value;co_return;}};', 'this or a closure'),
      ('std2::generator<unsigned> f(){unsigned n;co_yield n;co_return;}','not initialized'),
      ('std2::generator<unsigned> f(){unsigned n=1u;const unsigned&r=n;co_yield r;n=2u;co_yield r;co_return;}','borrow'),
      ('struct SAFETY_SEND_TYPE Bad{std2::generator<unsigned> value;};','Send'),
    ]:
        source.write_text(prefix+body);compile(checked+['-fsyntax-only',str(source)],False,needle)
print('Owned coroutine frame suspension, local loans, move/cancellation and 8 refusals passed under ASan/UBSan')
