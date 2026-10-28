#!/usr/bin/env python3
"""Substitute native tuple types and expand tracked whole-tuple expression packs."""
import json,os,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''export module dependent_tuples;
export template<class T> (T,T) make(T value) safe {return (value,value);}
export unsigned total() safe {return 23u;}
export unsigned total(unsigned a,unsigned long b) safe {return a+static_cast<unsigned>(b);}
export template<class... Args> unsigned dispatch(Args... args) safe {
 (Args...) values{args...};return total(rel values.[:] ...);
}
export template<class T> struct Owner {T* unsafe value=nullptr;~Owner() safe {unsafe {delete value;}}};
export template<class F,class... Args> void layout(F f,Args... args) safe {
 unsafe {Owner<(F,(Args...))> value;}
}
export unsigned run() safe {
 auto a=make<unsigned>(7u);auto b=make<unsigned long>(11ul);
 if(a.0!=7u || a.1!=7u || b.0!=11ul || b.1!=11ul)return 1u;
 if(dispatch(7u,11ul)!=18u || dispatch()!=23u)return 2u;
 layout(5u,7u,11ul);return 0u;
}
'''
with tempfile.TemporaryDirectory(prefix='circle-dependent-tuples-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'dependent_tuples':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def check(args):
  r=subprocess.run([str(CLANG)]+args,capture_output=True,text=True,timeout=120)
  assert r.returncode==0,r.stderr
  assert 'PLEASE submit' not in r.stderr,r.stderr
 local=API.replace('export module dependent_tuples;','').replace('export ','')
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+san;m=d/'dependent_tuples.cppm';pcm=d/'dependent_tuples.pcm';obj=d/'dependent_tuples.o';p=d/'client.cpp';exe=d/'run'
   m.write_text(API);check(options+['--precompile',str(m),'-o',str(pcm)]);check(options+['-c',str(pcm),'-o',str(obj)])
   for imported in (False,True):
    prefix='import dependent_tuples;' if imported else local
    imports=['-fmodule-file=dependent_tuples='+str(pcm)] if imported else []
    p.write_text(prefix+'int main() safe {(unsigned,unsigned) same=make<unsigned>(7u);if(same.0!=7u || same.1!=7u)return 2;auto value=make<unsigned long long>(29ull);layout(1u,3ull);return run()==0u && value.0==29ull && value.1==29ull?0:1;}')
    check(options+imports+[str(p)]+([str(obj)] if imported else [])+['-o',str(exe)])
    r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30);assert r.returncode==0,r.stderr+str(r.returncode)
    p.write_text(prefix+'template<class T> unsigned splat(T input) safe {return total(make<T>(input).[:] ...);}int main() safe {return splat(7u)==14u?0:1;}')
    check(options+imports+[str(p)]+([str(obj)] if imported else [])+['-o',str(exe)])
    r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30);assert r.returncode==0,r.stderr+str(r.returncode)
print('Dependent tuple type and nested type-pack substitution, tracked tuple expression-pack and empty expansion, fresh PCM instantiations: local/PCM O0/O2 plain ASan/UBSan, 8 runs; dependent tuple temporary splats execute')
