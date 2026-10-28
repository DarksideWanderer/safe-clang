#!/usr/bin/env python3
"""An unsafe named module retains pristine Clang syntax and CodeGen."""
import json
import pathlib
import subprocess
import tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
native=ROOT/'llvm-build/bin/clang'
pristine=ROOT/'build/clang-pristine/bin/clang'
with tempfile.TemporaryDirectory(prefix='unsafe-legacy-') as directory:
    d=pathlib.Path(directory);policy=d/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'legacy_mode':'unsafe'}}))
    source=d/'legacy_mode.cppm'
    source.write_text('''export module legacy_mode;
export struct choice { unsigned value; };
export unsigned safe(unsigned unsafe) { return unsafe ^ 3u; }
export unsigned rel(unsigned cpp) { unsigned mut=cpp; return mut+1u; }
export int divide(int x,int y) {return x/y;}
export int remainder(int x,int y) {return x%y;}
export int read(int index) {int array[4]={1,2,3,4};return array[index];}
export struct Owner { int value; Owner(int v):value(v){} Owner(const Owner&)=default; ~Owner(){} };
export Owner pass(Owner value){return value;}
''')
    sdk=subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
    ir=[]
    for i,compiler in enumerate([native,pristine]):
        output=d/f'{i}.ll'
        flags=['-std=c++20','-O0','-fno-ident','-isysroot',sdk,'-S','-emit-llvm']
        if i==0:flags+=['-fmodule-unsafe','-fmodule-safety-policy='+str(policy)]
        r=subprocess.run([str(compiler),*flags,str(source),'-o',str(output)],capture_output=True,text=True)
        assert r.returncode==0,r.stderr
        ir.append('\n'.join(line for line in output.read_text().splitlines() if not line.startswith('; ModuleID')))
    assert ir[0]==ir[1],'unsafe module differs from pristine Clang IR/ABI'
    assert '@abort' not in ir[0],'legacy arithmetic acquired Circle panic checks'
    for body in ['export unsigned f() safe {return 1u;}', 'choice C { some(unsigned) };']:
        source.write_text('export module legacy_mode;\n'+body)
        r=subprocess.run([str(native),'-std=c++20','-fmodule-unsafe','-fmodule-safety-policy='+str(policy),'-fsyntax-only',str(source)],capture_output=True,text=True)
        assert r.returncode!=0,'Circle-only syntax accepted by legacy unsafe module'
print('Unsafe module O0 syntax, scalar arithmetic/arrays and nontrivial by-value ABI match pristine Clang; Circle safe/choice declarations rejected')
