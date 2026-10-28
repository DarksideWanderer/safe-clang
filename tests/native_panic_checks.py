#!/usr/bin/env python3
"""Native integer division/remainder and array bounds checks precede UB."""
import json
import pathlib
import subprocess
import tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
clang=ROOT/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='circle-panic-') as directory:
    d=pathlib.Path(directory)
    policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'panic_checks':'safe'}}))
    source=d/'panic_checks.cppm';source.write_text('''export module panic_checks;
export int quotient(int x,int y) safe { return x/y; }
export int remainder(int x,int y) safe { return x%y; }
export unsigned unsigned_quotient(unsigned x,unsigned y) safe { return x/y; }
export int add(int x,int y) safe { return x+y; }
export int subtract(int x,int y) safe { return x-y; }
export int multiply(int x,int y) safe { return x*y; }
export int add_assign(int x,int y) safe { x+=y; return x; }
export int subtract_assign(int x,int y) safe { x-=y; return x; }
export int multiply_assign(int x,int y) safe { x*=y; return x; }
constexpr int folded_value() safe { unsafe { return __builtin_is_constant_evaluated()?1:2147483647; } }
static_assert(folded_value()==1);
export int folded_add() safe { return folded_value()+1; }
export int folded_multiply() safe { return folded_value()*2; }
export int read_array(int index) safe { int a[4]={1,2,3,4}; return a[index]; }
export int write_array(int index) safe { int a[4]={}; a[index]=7; return a[0]; }
export unsigned read_borrow_high() safe { unsigned n=1u; const unsigned^ a[1]={^const n}; return *a[1]; }
export unsigned read_borrow_low() safe { unsigned n=1u; const unsigned^ a[1]={^const n}; return *a[-1]; }
export bool address_array(int index) safe { int a[4]={}; unsafe { return &a[index]==&a[0]+4; } }
''')
    main=d/'main.cpp';main.write_text('''#include <cstdlib>
#include <csignal>
#include <climits>
import panic_checks;
void panic(int){std::_Exit(77);}
int main(int argc,char**argv){std::signal(SIGABRT,panic);int c=std::atoi(argv[1]);
switch(c){
case 0:return quotient(20,4)==5 && remainder(20,3)==2 && unsigned_quotient(20,4)==5 && read_array(3)==4 && write_array(0)==7 && address_array(4) && add(20,4)==24 && subtract(20,4)==16 && multiply(20,4)==80 && add_assign(20,4)==24 && subtract_assign(20,4)==16 && multiply_assign(20,4)==80 ?0:1;
case 1:return quotient(20,0);
case 2:return remainder(20,0);
case 3:return quotient(INT_MIN,-1);
case 4:return remainder(INT_MIN,-1);
case 5:return unsigned_quotient(20,0);
case 6:return read_array(4);
case 7:return read_array(-1);
case 8:return write_array(4);
case 9:return address_array(5);
case 10:return read_borrow_high();
case 11:return read_borrow_low();
case 12:return add(INT_MAX,1);
case 13:return add(INT_MIN,-1);
case 14:return subtract(INT_MIN,1);
case 15:return subtract(INT_MAX,-1);
case 16:return multiply(INT_MAX,2);
case 17:return multiply(INT_MIN,-1);
case 18:return add_assign(INT_MAX,1);
case 19:return subtract_assign(INT_MIN,1);
case 20:return multiply_assign(INT_MIN,-1);
case 21:return folded_add();
case 22:return folded_multiply();
}return 2;}
''')
    for opt in ('-O0','-O2'):
        for sanitizers in ([],['-fsanitize=address,undefined']):
            pcm=d/'panic_checks.pcm';obj=d/'panic_checks.o';binary=d/'run'
            flags=['-std=c++20',opt,'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']+sanitizers
            checked=flags+['-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy)]
            for command in ([str(clang),*checked,'--precompile',str(source),'-o',str(pcm)],
                            [str(clang),*checked,'-c',str(pcm),'-o',str(obj)],
                            [str(clang),'--driver-mode=g++',*flags,'-fprebuilt-module-path='+str(d),str(main),str(obj),'-o',str(binary)]):
                r=subprocess.run(command,capture_output=True,text=True);assert r.returncode==0,r.stderr
            for case in range(23):
                r=subprocess.run([str(binary),str(case)],capture_output=True,text=True)
                expected=0 if case==0 else 77
                assert r.returncode==expected,(opt,sanitizers,case,r.returncode,r.stderr)
                assert 'runtime error:' not in r.stderr and 'ERROR: AddressSanitizer' not in r.stderr,r.stderr
    plain=d/'plain.cpp'
    prefix='#feature on safety\nunsigned danger() unsafe {return 1u;}\n'
    cases=[
        ('unsigned caller() safe {return danger();}',False),
        ('unsigned caller() safe {unsafe {return danger();}}',True),
        ('unsigned caller() safe {unsafe {auto f=[](){return danger();};return f();}}',False),
        ('unsigned inner() safe {return 1u;} unsigned caller() unsafe {return inner();}',True),
    ]
    for body,accepted in cases:
        plain.write_text(prefix+body)
        r=subprocess.run([str(clang),'-std=c++20','-fcircle-safety',
                          '-fmodule-safety-policy='+str(policy),'-fsyntax-only',str(plain)],capture_output=True,text=True)
        assert (r.returncode==0)==accepted,(body,r.returncode,r.stderr)
        if not accepted:assert "call to unsafe or unclassified function 'danger'" in r.stderr,r.stderr
print('Signed add/subtract/multiply and compound assignment overflow, constexpr/runtime distinction, integer division/remainder zero/overflow, scalar and borrow-array bounds panic before UB; 22 panic cases and valid operations pass across PCM at O0/O2 with and without ASan/UBSan')
