#!/usr/bin/env python3
"""Exact cleanup of nontrivial elements in native tuple specializations."""
import pathlib,subprocess,tempfile,json
r=pathlib.Path(__file__).resolve().parent.parent;c=r/'llvm-build/bin/clang'
api='''export module tuple_drops;
unsigned drops=0;
export struct Count {unsigned id;Count(unsigned value) safe :id(value) {}~Count() safe {unsafe {++drops;}}};
export template<class T> (T,T) own(T a,T b) safe {return (rel a,rel b);}
export unsigned run_drops() safe {unsafe {
 drops=0;{auto value=own(Count(1u),Count(2u));if((value.0).id!=1u || (value.1).id!=2u)return 1;}if(drops!=2u)return 2;
 drops=0;{auto value=own(Count(1u),Count(2u));Count first=rel value.0;if(first.id!=1u)return 3;}if(drops!=2u)return 4;
 drops=0;try {auto value=own(Count(1u),Count(2u));throw 7u;}catch(unsigned){}return drops==2u?0u:5u;
}}
'''
with tempfile.TemporaryDirectory() as td:
 d=pathlib.Path(td);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'tuple_drops':'safe'}}));flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def check(args):
  x=subprocess.run([str(c)]+args,capture_output=True,text=True);assert x.returncode==0,x.stderr
 for opt in ['-O0','-O2']:
  for san in [[],['-fsanitize=address,undefined','-fno-sanitize-recover=all']]:
   fs=flags+[opt]+san;m=d/'a.cppm';pcm=d/'a.pcm';obj=d/'a.o';p=d/'client.cpp';exe=d/'run';m.write_text(api)
   check(fs+['--precompile',str(m),'-o',str(pcm)]);check(fs+['-c',str(pcm),'-o',str(obj)])
   for imported in [False,True]:
    p.write_text(('import tuple_drops;' if imported else api.replace('export module tuple_drops;','').replace('export ',''))+'int main() safe {return run_drops();}')
    check(fs+(['-fmodule-file=tuple_drops='+str(pcm)] if imported else [])+[str(p)]+([str(obj)] if imported else [])+['-o',str(exe)])
    x=subprocess.run([str(exe)],capture_output=True,text=True);assert x.returncode==0,str(x.returncode)+x.stderr
print('Exact nontrivial tuple drops after owning-parameter relocation, field relocation, and EH: local/PCM O0/O2 plain ASan/UBSan, 8 runs passed')
