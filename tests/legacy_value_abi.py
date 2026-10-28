#!/usr/bin/env python3
"""Link checked calls and explicit legacy ABI wrappers against pristine C++."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
PRISTINE = pathlib.Path(os.environ.get('MODULE_SAFETY_PRISTINE_CLANG', '/opt/homebrew/opt/llvm/bin/clang++'))
COMMON = ['--driver-mode=g++','-std=c++20','-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
HEADER = '''#pragma once
struct Legacy {
 unsigned* pointer;
 explicit Legacy(unsigned);
 Legacy(const Legacy&)=delete;
 Legacy(Legacy&&) noexcept;
 ~Legacy();
 unsigned get() const;
};
void legacy_reset();
unsigned legacy_drops();unsigned legacy_moves();unsigned legacy_releases();
void legacy_consume(Legacy);
void legacy_throw(Legacy);
unsigned legacy_drive();
extern "C" Legacy legacy_entry(Legacy);
'''
PROVIDER = '''#include "legacy.hpp"
unsigned drops=0,moves=0,releases=0;
Legacy::Legacy(unsigned value):pointer(new unsigned(value)){}
Legacy::Legacy(Legacy&& other) noexcept:pointer(other.pointer){other.pointer=nullptr;++moves;}
Legacy::~Legacy(){++drops;if(pointer){++releases;delete pointer;}}
unsigned Legacy::get()const{return *pointer;}
void legacy_reset(){drops=0;moves=0;releases=0;}
unsigned legacy_drops(){return drops;}unsigned legacy_moves(){return moves;}unsigned legacy_releases(){return releases;}
void legacy_consume(Legacy value){if(value.get()!=11u)throw 7u;}
void legacy_throw(Legacy value){if(value.get()!=11u)throw 8u;throw 9u;}
unsigned legacy_drive(){
 legacy_reset();
 {Legacy source(37u);Legacy result=legacy_entry(static_cast<Legacy&&>(source));if(result.get()!=37u)return 1u;}
 return legacy_moves()==3u && legacy_drops()==4u && legacy_releases()==1u ? 0u:2u;
}
'''
API = '''
Legacy checked_identity(Legacy unsafe value) safe {unsafe {return rel value;}}
void checked_consume(Legacy unsafe value) safe {unsafe {if(value.get()!=11u)throw 1u;}}
// A legacy-facing boundary retains the platform ABI; its owned argument is
// explicitly moved into the checked entry, whose callee owns the new value.
extern "C" unsafe_fn Legacy legacy_entry(Legacy value){return checked_identity(static_cast<Legacy&&>(value));}
unsigned run_abi() safe {unsafe {
 legacy_reset();{Legacy source(7u);Legacy result=checked_identity(rel source);if(result.get()!=7u)return 1u;}
 if(legacy_moves()!=2u || legacy_drops()!=3u || legacy_releases()!=1u)return 2u;
 legacy_reset();{Legacy source(11u);legacy_consume(rel source);}
 if(legacy_moves()!=1u || legacy_drops()!=2u || legacy_releases()!=1u)return 3u;
 legacy_reset();{Legacy source(11u);auto f=&legacy_consume;f(rel source);}
 if(legacy_moves()!=1u || legacy_drops()!=2u || legacy_releases()!=1u)return 4u;
 legacy_reset();{Legacy source(11u);checked_consume(rel source);}
 if(legacy_moves()!=1u || legacy_drops()!=2u || legacy_releases()!=1u)return 5u;
 legacy_reset();{Legacy source(11u);auto f=&checked_consume;f(rel source);}
 if(legacy_moves()!=1u || legacy_drops()!=2u || legacy_releases()!=1u)return 6u;
 legacy_reset();try {Legacy source(11u);legacy_throw(rel source);}catch(unsigned){}
 if(legacy_moves()!=1u || legacy_drops()!=2u || legacy_releases()!=1u)return 7u;
 return legacy_drive()==0u?0u:8u;
}}
'''
with tempfile.TemporaryDirectory(prefix='legacy-value-abi-') as directory:
    d=pathlib.Path(directory)
    (d/'legacy.hpp').write_text(HEADER)
    provider=d/'legacy.cpp';provider.write_text(PROVIDER)
    module,pcm,obj,source,exe,legacy=(d/n for n in ('api.cppm','api.pcm','api.o','main.cpp','run','legacy.o'))
    def compile(compiler,args):
        r=subprocess.run([str(compiler)]+COMMON+['-I'+str(d)]+args,capture_output=True,text=True,timeout=120)
        assert r.returncode==0,r.stderr
        assert 'PLEASE submit' not in r.stderr,r.stderr
    for opt in ('-O0','-O2'):
        for sanitizer in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
            options=[opt]+sanitizer
            compile(PRISTINE,options+['-c',str(provider),'-o',str(legacy)])
            native=options+['-fcircle-safety','-fcircle-borrow-values']
            module.write_text('module;\n#include "legacy.hpp"\nexport module legacy_abi;export {\n'+API+'}\n')
            compile(CLANG,native+['--precompile',str(module),'-o',str(pcm)])
            compile(CLANG,native+['-c',str(pcm),'-o',str(obj)])
            for imported in (False,True):
                source.write_text('#include "legacy.hpp"\n'+('import legacy_abi;\n' if imported else API)+
                                  'int main() safe {return static_cast<int>(run_abi());}')
                compile(CLANG,native+(['-fmodule-file=legacy_abi='+str(pcm)] if imported else [])+
                        [str(source),str(legacy)]+([str(obj)] if imported else [])+['-o',str(exe)])
                r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
                assert r.returncode==0,f'exit {r.returncode}: {r.stderr}'
    source.write_text('#include "legacy.hpp"\nvoid unchecked_drop(Legacy value) safe {unsafe {}}')
    refused=subprocess.run([str(CLANG)]+COMMON+['-I'+str(d),'-fcircle-safety','-fsyntax-only',str(source)],capture_output=True,text=True,timeout=120)
    assert refused.returncode!=0 and 'requires an explicit' in refused.stderr and 'PLEASE submit' not in refused.stderr,refused.stderr
print('Legacy by-value ABI: pristine C++ provider, explicit legacy-facing wrapper, checked/legacy direct and indirect calls, normal/EH exits and exact move/drop/resource counts; 8 local/PCM O0/O2 plain ASan/UBSan executions passed')
