#!/usr/bin/env python3
"""Native interface declaration identity and deferred associated names in PCM.

This tests declaration infrastructure only; impl/dyn/runtime dispatch is absent.
"""
import json
import pathlib
import subprocess
import tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
clang=ROOT/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='circle-interface-') as directory:
    d=pathlib.Path(directory);p=d/'policy.json'
    p.write_text(json.dumps({'version':1,'modules':{'interface_decl':'safe','interface_client':'safe'}}))
    flags=['-std=c++20','-O0','-fcircle-safety','-fmodule-safety-policy='+str(p)]
    source=d/'interface_decl.cppm';pcm=d/'interface_decl.pcm'
    source.write_text('''export module interface_decl;
export interface iterator { typename item_type; item_type next(self^) safe; Self clone(const self^) safe; };
export interface other { typename item_type; };
static_assert(!__is_same(iterator::item_type,other::item_type));
static_assert(!__is_same(iterator::Self,other::Self));
static_assert(!__is_same(iterator::Self,iterator::item_type));
using Next = iterator::item_type __attribute__((safe_function)) (iterator::Self^);
static_assert(__is_same(decltype(&iterator::next),Next*));
using Self = unsigned;
static_assert(__is_same(Self,unsigned));
''')
    commands=[[str(clang),*flags,'--precompile',str(source),'-o',str(pcm)],
              [str(clang),*flags,'-c',str(pcm),'-o',str(d/'interface_decl.o')]]
    for cmd in commands:
        r=subprocess.run(cmd,capture_output=True,text=True);assert r.returncode==0,r.stderr
    client=d/'interface_client.cppm';client.write_text('''export module interface_client;
import interface_decl;
static_assert(!__is_same(iterator::item_type,other::item_type));
static_assert(!__is_same(iterator::Self,other::Self));
static_assert(!__is_same(iterator::Self,iterator::item_type));
using Next = iterator::item_type __attribute__((safe_function)) (iterator::Self^);
static_assert(__is_same(decltype(&iterator::next),Next*));
using Self = unsigned;
static_assert(__is_same(Self,unsigned));
''')
    r=subprocess.run([str(clang),*flags,'-fprebuilt-module-path='+str(d),'--precompile',str(client),'-o',str(d/'client.pcm')],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    negatives=[
      ('interface I {typename Self;};','associated type is already declared'),
      ('interface I {typename item;typename item;};','associated type is already declared'),
      ('interface I {unsigned field;};','cannot declare object storage fields'),
      ('interface I {}; I value;','cannot be instantiated as an object'),
      ('interface I {}; struct S:I {};','inheritance cannot create an ordinary object type'),
      ('interface I {}; static_assert(sizeof(I)==1);','layout queries are not yet modeled'),
      ('interface I {unsigned f(self^) safe {return 1u;}};','default method lowering is not yet implemented'),
      ('interface I {unsigned f(self^) safe;}; unsigned invoke(I^ p) safe {return p->f();}','dispatch requires native impl lowering'),
    ]
    for body,diagnostic in negatives:
        source.write_text('export module interface_decl;\n'+body)
        r=subprocess.run([str(clang),*flags,'-fsyntax-only',str(source)],capture_output=True,text=True)
        assert r.returncode and diagnostic in r.stderr,(body,r.stderr)
        assert 'PLEASE submit' not in r.stderr,r.stderr
print('O0 native interface declaration/associated-name identity preserved through two PCMs; duplicate/storage/object/default-body/dispatch limitations rejected explicitly; impl/dyn remain incomplete')
