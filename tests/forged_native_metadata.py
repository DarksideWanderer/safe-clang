#!/usr/bin/env python3
"""Source annotations cannot claim compiler-generated safety privileges."""
import json
import pathlib
import subprocess
import sys
import tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
clang=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='forged-native-') as directory:
    tmp=pathlib.Path(directory)
    policy=tmp/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{'forged':'safe'}}))
    source=tmp/'forged.cppm'
    cases=[
        '[[clang::annotate("safecpp.native.choice.constructor")]] unsigned f(unsigned* p){return *p;}',
        '[[clang::annotate("safecpp.native.choice.destructor")]] unsigned f(unsigned* p){return *p;}',
        'struct [[clang::annotate("safecpp.native.choice.storage")]] S { unsigned* p; };',
        'struct [[clang::annotate("safecpp.thread.send")]] S { unsigned* p; };',
        '[[clang::annotate("safecpp.native.consumes.receiver")]] void f(unsigned* p) {}',
        'template<class T> [[clang::annotate("safecpp.native.choice.constructor")]] T f(T* p){return *p;}',
        '#define CLAIM [[clang::annotate("safecpp.native.choice.constructor")]]\nCLAIM unsigned f(unsigned* p){return *p;}',
    ]
    for body in cases:
        source.write_text('export module forged;\n'+body)
        r=subprocess.run([str(clang),'-std=c++20','-fmodule-safe','-fmodule-safety-policy='+str(policy),'-fsyntax-only',str(source)],capture_output=True,text=True)
        assert r.returncode and 'compiler-owned safety metadata cannot be written in source' in r.stderr,r.stderr
        assert 'PLEASE submit' not in r.stderr,r.stderr
        # The same string is an ordinary annotation in default Clang mode.
        r=subprocess.run([str(clang),'-std=c++20','-fsyntax-only',str(source)],capture_output=True,text=True)
        assert r.returncode==0,r.stderr
    # Compiler-generated markers must still work, including after instantiation.
    source.write_text('export module forged;\nchoice C { default none, some(unsigned) };\nunsigned f(C c) { return match(c)->unsigned { .none=>0u; .some(_)=>1u; }; }')
    r=subprocess.run([str(clang),'-std=c++20','-fcircle-safety','-fmodule-safety-policy='+str(policy),'-fsyntax-only',str(source)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
print('7 forged metadata refusals, 7 default-mode annotation accepts, generated choice positive passed')
