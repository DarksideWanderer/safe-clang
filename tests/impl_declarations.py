#!/usr/bin/env python3
"""Native impl target/contract declaration bindings; dispatch remains incomplete."""
import json
import pathlib
import subprocess
import tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
clang=ROOT/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='circle-impl-') as directory:
    d=pathlib.Path(directory)
    policy=d/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'impl_decl':'safe','impl_client':'safe'}}))
    flags=['-std=c++20','-O0','-fcircle-safety','-fmodule-safety-policy='+str(policy)]
    source=d/'impl_decl.cppm';pcm=d/'impl_decl.pcm'
    source.write_text('''export module impl_decl;
export interface Contract {typename item_type;};
export struct Value {};
interface Other {};
impl Value : Other {};
impl Value : Contract {
  using item_type=unsigned;
  static_assert(__is_same(Self,Value));
  static_assert(__is_same(__circle_interface,Contract));
};
template<class T> impl T : Contract {
  using item_type=T;
  static_assert(__is_same(Self,T));
};
''')
    for args in [ ['--precompile',str(source),'-o',str(pcm)],
                  ['-c',str(pcm),'-o',str(d/'impl_decl.o')] ]:
        r=subprocess.run([str(clang),*flags,*args],capture_output=True,text=True)
        assert r.returncode==0,r.stderr
    client=d/'impl_client.cppm'
    client.write_text('export module impl_client; import impl_decl; static_assert(!__is_same(Contract::Self,Value));')
    r=subprocess.run([str(clang),*flags,'-fprebuilt-module-path='+str(d),'--precompile',str(client),'-o',str(d/'client.pcm')],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    client.write_text('export module impl_client; import impl_decl; impl Value : Contract {using item_type=unsigned;};')
    r=subprocess.run([str(clang),*flags,'-fprebuilt-module-path='+str(d),'-fsyntax-only',str(client)],capture_output=True,text=True)
    assert r.returncode and 'redefines an existing target/interface implementation' in r.stderr,r.stderr
    # A correctly substituted signature must pass the new contract comparison,
    # while execution remains explicitly unavailable until native selection.
    source.write_text('export module impl_decl; interface C {typename item; item f(self^) safe;}; struct V {}; impl V : C {using item=unsigned; unsigned f(self^) safe override;};')
    r=subprocess.run([str(clang),*flags,'-fsyntax-only',str(source)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    assert 'no method matching' not in r.stderr,r.stderr
    assert 'missing associated type' not in r.stderr,r.stderr
    for body,expected in [
        ('interface C {}; impl unsigned:C {}; impl unsigned:C {};','redefines an existing target/interface implementation'),
        ('interface C {}; using U=unsigned; impl unsigned:C {}; impl U:C {};','redefines an existing target/interface implementation'),
        ('interface C {unsigned f(self^) noexcept safe;}; struct V {}; impl V : C {unsigned f(self^) safe;};','no method matching the substituted contract'),
        ('interface C {unsigned f(self^) safe;}; struct V {}; impl V : C {unsigned f(self^) unsafe;};','no method matching the substituted contract'),
        ('struct Value {}; impl Value : Value {};','requires a native interface contract'),
        ('interface C {typename item;}; impl unsigned : C {};',"missing associated type"),
        ('interface C {typename item; item f(self^) safe;}; struct V {}; impl V : C {using item=unsigned; unsigned f(const self^) safe;};','no method matching the substituted contract'),
        ('interface C {typename item; item f(self^) safe;}; struct V {}; impl V : C {using item=unsigned; bool f(self^) safe;};','no method matching the substituted contract'),
        ('interface C {}; impl unsigned : C { unsigned field; };','cannot declare object storage fields'),
        ('interface C {}; struct Value {}; impl Value : C { unsigned f(self^) safe {return 1u;} };','method contract binding is not yet implemented'),
    ]:
        source.write_text('export module impl_decl;\n'+body)
        r=subprocess.run([str(clang),*flags,'-fsyntax-only',str(source)],capture_output=True,text=True)
        assert r.returncode and expected in r.stderr,(body,r.stderr)
        assert 'PLEASE submit' not in r.stderr,r.stderr
print('O0 native impl Self/contract declaration bindings and template parsing survive PCM; invalid contracts/storage and unimplemented method binding rejected; selection/dispatch remain incomplete')
