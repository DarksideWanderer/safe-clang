#!/usr/bin/env python3
"""Differential default-mode evidence against an independent Clang 22.1.2.

No safety flags, feature macros or upstream inputs are altered. This finite
suite is regression evidence, not a claim of complete Clang compatibility.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = {
    'choice_annotation_identity': ('cpp', '-std=c++20', '#include <cstdio>\nunsigned drops=0;\nstruct Counted { ~Counted(){ ++drops; } };\nunion Storage {\n  [[clang::annotate("safecpp.native.choice.alternative:0")]] Counted some;\n  Storage():some(){}\n  ~Storage(){ some.~Counted(); }\n};\nstruct Ordinary {\n  [[clang::annotate("safecpp.native.choice.tag")]] unsigned tag=0;\n  [[clang::annotate("safecpp.native.choice.payload")]] Storage data;\n  using Some [[clang::annotate("safecpp.native.choice.alternative:0")]] = Counted;\n};\nint main(){ {Ordinary value;} std::printf("%u\\n", drops); }\n'),
    'c11': ('c', '-std=c11', '''#include <stdio.h>
struct S { char x; long y; };
_Static_assert(sizeof(struct S)==16,"layout");
int main(void){printf("%zu %d\\n",_Alignof(struct S),_Generic(1,int:7,default:0));}
'''),
    'cxx20': ('cpp', '-std=c++20', '''#include <cstdio>
#include <vector>
#include <type_traits>
#include <stdexcept>
template<class T> requires std::is_integral_v<T> constexpr T twice(T x){return x+x;}
constexpr int choose(int){return 3;} constexpr int choose(double){return 4;}
static_assert(twice(4)==8 && choose(1)==3 && choose(1.0)==4);
struct S{char x;long y;}; static_assert(sizeof(S)==16 && alignof(S)==8);
int drops=0;struct Guard{~Guard(){++drops;}};
extern "C" int callback(int (*f)(int),int x){return f(x);}
int main(){try{Guard g;throw std::runtime_error("x");}catch(const std::exception&){}
std::vector<int> v{1,2,3};std::printf("%d %d %zu\\n",drops,callback([](int x){return twice(x);},v[2]),sizeof(S));}
'''),
    'abi': ('cpp', '-std=c++20', '''struct Small {int x;double y;};
struct Base{virtual int f(int)=0;virtual ~Base()=default;};
Small pass(Small x){return x;} template<class T>T id(T x){return x;}
template int id<int>(int); extern "C" int c_entry(int x){return x+1;}
int call(Base* p){return p->f(3);}
'''),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clang', type=pathlib.Path, default=ROOT/'llvm-build/bin/clang')
    p.add_argument('--reference', type=pathlib.Path, default=ROOT/'build/clang-pristine/bin/clang')
    p.add_argument('--output', type=pathlib.Path, default=ROOT/'build/clang-compatibility.json')
    a = p.parse_args()
    report = {'baseline':'Clang 22.1.2', 'extension_flags':[], 'fully_compatible':False,
              'scope':'Finite default-mode differential regression suite', 'compilers':{}, 'cases':[]}
    compilers = [a.clang.resolve(), a.reference.resolve()]
    for compiler in compilers:
        version = subprocess.check_output([str(compiler),'--version'],text=True)
        if 'version 22.1.2' not in version:
            p.error('both compilers must be Clang 22.1.2')
        report['compilers'][str(compiler)] = {'version':version,'sha256':digest(compiler)}
    if compilers[0] == compilers[1]:
        p.error('reference must be an independent compiler')
    with tempfile.TemporaryDirectory(prefix='clang-differential-') as directory:
        tmp = pathlib.Path(directory)
        # Homebrew's driver configuration supplies a sysroot implicitly.
        # Use the same explicit SDK for both drivers, and omit producer branding.
        sdk = subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
        common = ['-isysroot',sdk,'-fno-ident']
        report['common_flags'] = common
        def run(command):
            r = subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=90)
            return {'command':list(map(str,command)),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
        for name,(suffix,standard,source) in CASES.items():
            src=tmp/(name+'.'+suffix); src.write_text(source)
            for opt in ('-O0','-O2'):
                entry={'name':name,'optimization':opt,'source':source,'results':[]}
                for i,compiler in enumerate(compilers):
                    output=tmp/(name+str(i))
                    flags=common+[standard,opt,'--driver-mode=g++' if suffix=='cpp' else '--driver-mode=gcc']
                    if name=='abi':
                        result=run([compiler]+flags+['-S','-emit-llvm',src,'-o',output])
                        if result['returncode']==0:
                            # ModuleID is an input path; all semantic IR remains compared.
                            result['ir']='\n'.join(line for line in output.read_text().splitlines() if not line.startswith('; ModuleID'))
                    else:
                        result=run([compiler]+flags+[src,'-o',output])
                        if result['returncode']==0: result['execution']=run([output])
                    entry['results'].append(result)
                left,right=entry['results']
                entry['passed']=left['returncode']==right['returncode']==0
                if name=='abi': entry['passed'] &= left.get('ir')==right.get('ir')
                else:
                    entry['passed'] &= left.get('execution',{}).get('returncode')==right.get('execution',{}).get('returncode')==0
                    entry['passed'] &= left.get('execution',{}).get('stdout')==right.get('execution',{}).get('stdout')
                report['cases'].append(entry)
        # Nontrivial by-value parameters and exception cleanup must agree when
        # callers and callees are compiled by different default-mode compilers.
        header=tmp/'owner.hpp'
        header.write_text('''extern int drops;
struct Owner {int value; explicit Owner(int v):value(v){}
Owner(const Owner& x):value(x.value){} Owner(Owner&& x):value(x.value){x.value=0;}
~Owner(){++drops;}};
void consume(Owner,bool); Owner pass(Owner);
''')
        provider=tmp/'provider.cpp';provider.write_text('#include "owner.hpp"\nvoid consume(Owner x,bool fail){if(fail)throw 1;} Owner pass(Owner x){return x;}')
        caller=tmp/'caller.cpp';caller.write_text('''#include "owner.hpp"
#include <cstdio>
int drops=0;
int main(){{Owner x(1);consume(x,false);if(drops!=1)return 1;
try{consume(Owner(2),true);}catch(int){} if(drops!=2)return 2;
Owner y=pass(Owner(3));if(drops!=3 || y.value!=3)return 3;}
std::printf("%d\\n",drops);return drops!=5;}
''')
        for opt in ('-O0','-O2'):
            for i,compiler in enumerate(compilers):
                flags=common+['--driver-mode=g++','-std=c++20',opt]
                obj=tmp/'provider.o';binary=tmp/'mixed'
                steps=[run([compiler]+flags+['-c',provider,'-o',obj])]
                if steps[-1]['returncode']==0:
                    steps.append(run([compilers[1-i]]+flags+[caller,obj,'-o',binary]))
                if steps[-1]['returncode']==0:steps.append(run([binary]))
                report['cases'].append({'name':'mixed_nontrivial_abi','optimization':opt,
                    'provider_compiler':str(compiler),'caller_compiler':str(compilers[1-i]),
                    'header':header.read_text(),'provider':provider.read_text(),'caller':caller.read_text(),
                    'results':steps,'passed':len(steps)==3 and all(s['returncode']==0 for s in steps)
                        and steps[-1]['stdout']=='5\n'})
        entry={'name':'modules','results':[]}
        for i,compiler in enumerate(compilers):
            mod=tmp/'baseline.cppm'; mod.write_text('export module baseline; export constexpr int answer(){return 42;}')
            pcm=tmp/('baseline'+str(i)+'.pcm'); obj=tmp/('baseline'+str(i)+'.o')
            main=tmp/'main.cpp';main.write_text('import baseline; static_assert(answer()==42); int main(){return answer()!=42;}')
            flags=common+['--driver-mode=g++','-std=c++20']
            steps=[run([compiler]+flags+['--precompile',mod,'-o',pcm])]
            if steps[-1]['returncode']==0: steps.append(run([compiler]+flags+['-c',pcm,'-o',obj]))
            if steps[-1]['returncode']==0: steps.append(run([compiler]+flags+['-fmodule-file=baseline='+str(pcm),main,obj,'-o',tmp/('module'+str(i))]))
            if steps[-1]['returncode']==0: steps.append(run([tmp/('module'+str(i))]))
            entry['results'].append(steps)
        entry['passed']=all(len(s)==4 and all(r['returncode']==0 for r in s) for s in entry['results'])
        report['cases'].append(entry)
    report['passed']=all(e['passed'] for e in report['cases'])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(f"{sum(e['passed'] for e in report['cases'])}/{len(report['cases'])} differential cases passed: {a.output}")
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
