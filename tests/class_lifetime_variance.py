"""Function-scoped class regions survive mutation, callbacks and nested projections."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'
API = '''struct View/(region) {const unsigned^/region value;};
struct Pair/(left,right) {View/left first;View/right second;};
template<class T+> struct Wrapper {T value;};
void replace/(source,stored,call where source:stored)(
 View/stored^/call target,const unsigned^/source input) safe {target->value=input;}
void replace_transitive/(source,middle,stored,call where source:middle,middle:stored)(
 View/stored^/call target,const unsigned^/source input) safe {target->value=input;}
void replace_second/(source,left,right,call where source:right)(
 Pair/left/right^/call target,const unsigned^/source input) safe {
 target->second.value=input;}
void replace_nested/(source,left,right,call where source:right)(
 Wrapper<Pair>/left/right^/call target,const unsigned^/source input) safe {
 target->value.second.value=input;}
using Setter=void __attribute__((safe_function)) /(a,b,c where a:b)(View/b^/c,const unsigned^/a);
using Tied=void __attribute__((safe_function)) /(a,c)(View/a^/c,const unsigned^/a);
using Renamed=void __attribute__((safe_function)) /(q,r)(View/q^/r,const unsigned^/q);
using Untied=void __attribute__((safe_function)) /(a,b,c)(View/b^/c,const unsigned^/a);
using NestedTied=void __attribute__((safe_function)) (Tied*);
using NestedUntied=void __attribute__((safe_function)) (Untied*);
using ReturningTied=Tied* __attribute__((safe_function)) ();
using ReturningUntied=Untied* __attribute__((safe_function)) ();
static_assert(__is_same(Tied,Renamed));
static_assert(!__is_same(Tied,Untied));
static_assert(__is_same(decltype(&replace),Setter*));
static_assert(__is_same(decltype(&replace_transitive),Setter*));
Setter* select_setter() safe {return &replace;}
const unsigned permanent=7;
unsigned read_static/(call)(const View/static^/call input) safe {return *input->value;}
unsigned read_implicit_static(const View/static^ input) safe {return *input->value;}
unsigned read_implicit_static(const View/static^ input) safe;
using ImplicitStatic=unsigned __attribute__((safe_function)) (const View/static^);
static_assert(__is_same(decltype(&read_implicit_static),ImplicitStatic*));
ImplicitStatic* select_static_reader() safe {return &read_implicit_static;}
unsigned read_static_value(View/static input) safe {return *input.value;}
using StaticValue=unsigned __attribute__((safe_function)) (View/static);
static_assert(__is_same(decltype(&read_static_value),StaticValue*));
unsigned read_default_static(View/static input=View{^const permanent}) safe {
 return *input.value;
}
struct DefaultStaticReader {
 DefaultStaticReader(View/static input=View{^const permanent}) safe {
  unsigned read=*input.value;
 }
};
struct DefaultStaticHolder/(region) {View/region input=View{^const permanent};};
struct Installer {
 Installer/(source,stored,call where source:stored)(View/stored^/call target,
 const unsigned^/source input) safe {target->value=input;}
};
struct StaticReader {
 StaticReader/(call)(const View/static^/call input) safe {unsigned read=*input->value;}
};
struct ImplicitStaticReader {
 ImplicitStaticReader(const View/static^ input) safe {unsigned read=*input->value;}
};
template<class T> struct GenericInstaller {
 GenericInstaller/(source,stored,call where source:stored)(View/stored^/call target,
 const T^/source input) safe {target->value=input;}
};
struct ThrowingInstaller {
 ThrowingInstaller/(source,stored,call where source:stored)(View/stored^/call target,
 const unsigned^/source input) safe {target->value=input;throw 1u;}
};
'''
CASES = [
    ('same_scope', True, '''int main() safe {unsigned a=1,b=2;
 View value{^const a};replace(^value,^const b);return *value.value==2?0:1;}''', ''),
    ('transitive_region', True, '''int main() safe {unsigned a=1,b=2;
 View value{^const a};Setter* f=&replace_transitive;f(^value,^const b);
 return *value.value==2?0:1;}''', ''),
    ('constructor_region', True, '''int main() safe {unsigned a=1,b=2;
 View value{^const a};Installer change(^value,^const b);
 return *value.value==2?0:1;}''', ''),
    ('constructor_static', True, '''int main() safe {View value{^const permanent};
 StaticReader read(^const value);return 0;}''', ''),
    ('constructor_implicit_static', True, '''int main() safe {View value{^const permanent};
 ImplicitStaticReader read(^const value);return 0;}''', ''),
    ('implicit_static_callback', True, '''int main() safe {View value{^const permanent};
 return select_static_reader()(^const value)==7?0:1;}''', ''),
    ('static_value_callback', True, '''int main() safe {View value{^const permanent};
 StaticValue* f=&read_static_value;return f(value)==7?0:1;}''', ''),
    ('default_static_function', True, '''int main() safe {
 return read_default_static()==7?0:1;}''', ''),
    ('default_static_constructor', True, '''int main() safe {
 DefaultStaticReader reader;return 0;}''', ''),
    ('temporary_static_function', True, '''int main() safe {
 return read_static_value(View{^const permanent})==7?0:1;}''', ''),
    ('temporary_static_constructor', True, '''int main() safe {
 DefaultStaticReader reader(View{^const permanent});return 0;}''', ''),
    ('default_static_member', True, '''int main() safe {DefaultStaticHolder/static holder{};
 return read_static_value(holder.input)==7?0:1;}''', ''),
    ('constructor_template', True, '''int main() safe {unsigned a=1,b=2;
 View value{^const a};GenericInstaller<unsigned> change(^value,^const b);
 return *value.value==2?0:1;}''', ''),
    ('constructor_exception', True, '''int main() safe {unsigned a=1,b=2;
 View value{^const a};try {ThrowingInstaller change(^value,^const b);}
 catch(unsigned) {} return *value.value==2?0:1;}''', ''),
    ('longer_source', True, '''int main() safe {unsigned a=1;
 {unsigned b=2;View value{^const b};replace(^value,^const a);
 if(*value.value!=1)return 1;}return 0;}''', ''),
    ('callback', True, '''int main() safe {unsigned a=1,b=2;
 View value{^const a};auto f=select_setter();f(^value,^const b);
 return *value.value==2?0:1;}''', ''),
    ('callback_preserving_cast', True, '''int main() safe {unsigned a=1,b=2;
 View value{^const a};auto f=select_setter();
 unsafe {auto same=reinterpret_cast<Setter*>(f);same(^value,^const b);}
 return *value.value==2?0:1;}''', ''),
    ('nested', True, '''int main() safe {unsigned a=1,b=2,c=3;
 Pair value{View{^const a},View{^const b}};replace_second(^value,^const c);
 return *value.first.value==1 && *value.second.value==3?0:1;}''', ''),
    ('generic_nested', True, '''int main() safe {unsigned a=1,b=2,c=3;
 Wrapper<Pair> value{Pair{View{^const a},View{^const b}}};
 replace_nested(^value,^const c);
 return *value.value.first.value==1 && *value.value.second.value==3?0:1;}''', ''),
    ('static_region', True, '''int main() safe {View value{^const permanent};
 return read_static(^const value)==7?0:1;}''', ''),
    ('static_local', False, '''void rejected() safe {unsigned a=1;
 View value{^const a};unsigned read=read_static(^const value);}''',
     'static class argument requires permanent lifetime regions'),
    ('constructor_static_local', False, '''void rejected() safe {unsigned a=1;
 View value{^const a};StaticReader read(^const value);}''',
     'static class argument requires permanent lifetime regions'),
    ('constructor_implicit_static_local', False, '''void rejected() safe {unsigned a=1;
 View value{^const a};ImplicitStaticReader read(^const value);}''',
     'static class argument requires permanent lifetime regions'),
    ('implicit_static_local', False, '''void rejected() safe {unsigned a=1;
 View value{^const a};unsigned read=read_implicit_static(^const value);}''',
     'static class argument requires permanent lifetime regions'),
    ('implicit_static_indirect_local', False, '''void rejected() safe {unsigned a=1;
 View value{^const a};unsigned read=select_static_reader()(^const value);}''',
     'static class argument requires permanent lifetime regions'),
    ('static_value_local', False, '''void rejected() safe {unsigned a=1;
 View value{^const a};StaticValue* f=&read_static_value;unsigned read=f(value);}''',
     'static lifetime contract requires permanent non-thread-local borrow origins'),
    ('default_static_override_local', False, '''void rejected() safe {unsigned a=1;
 unsigned read=read_default_static(View{^const a});}''',
     'static lifetime contract requires permanent non-thread-local borrow origins'),
    ('default_static_constructor_override_local', False, '''void rejected() safe {unsigned a=1;
 DefaultStaticReader reader(View{^const a});}''',
     'static lifetime contract requires permanent non-thread-local borrow origins'),
    ('default_static_member_override_local', False, '''void rejected() safe {unsigned a=1;
 DefaultStaticHolder/static holder{View{^const a}};}''',
     'static field lifetime contract requires permanent non-thread-local borrow origins'),
    ('unrelated', False, '''void rejected/(source,stored,call)(
 View/stored^/call target,const unsigned^/source input) safe {target->value=input;}''',
     'class field lifetime contract does not preserve its declared region'),
    ('shadowed', False, '''void rejected/(region,stored,call)(
 View/stored^/call target,const unsigned^/region input) safe {target->value=input;}''',
     'class field lifetime contract does not preserve its declared region'),
    ('reversed', False, '''void rejected/(source,stored,call where stored:source)(
 View/stored^/call target,const unsigned^/source input) safe {target->value=input;}''',
     'class field lifetime contract does not preserve its declared region'),
    ('reversed_transitive', False, '''void rejected/(source,middle,stored,call
 where stored:middle,middle:source)(View/stored^/call target,
 const unsigned^/source input) safe {target->value=input;}''',
     'class field lifetime contract does not preserve its declared region'),
    ('nested_wrong_region', False, '''void rejected/(source,left,right,call where source:left)(
 Pair/left/right^/call target,const unsigned^/source input) safe {
 target->second.value=input;}''',
     'class field lifetime contract does not preserve its declared region'),
    ('generic_wrong_region', False, '''void rejected/(source,left,right,call where source:left)(
 Wrapper<Pair>/left/right^/call target,const unsigned^/source input) safe {
 target->value.second.value=input;}''',
     'class field lifetime contract does not preserve its declared region'),
    ('nested_field_swap', False, '''void rejected/(left,right,call)(
 Pair/left/right^/call target) safe {target->first.value=target->second.value;}''',
     'class field lifetime contract does not preserve its declared region'),
    ('generic_field_swap', False, '''void rejected/(left,right,call)(
 Wrapper<Pair>/left/right^/call target) safe {
 target->value.first.value=target->value.second.value;}''',
     'class field lifetime contract does not preserve its declared region'),
    ('callback_erasure', False, '''void rejected(Tied* source) safe {Untied* erased=source;}''', 'error:'),
    ('callback_unsafe_erasure', False, '''void rejected(Tied* source) safe {
 unsafe {Untied* erased=reinterpret_cast<Untied*>(source);}}''',
     'cast cannot erase or invent quantified lifetime contracts'),
    ('callback_specialization', True, '''void accepted(Untied* source) unsafe {
 Tied* specialized=reinterpret_cast<Tied*>(source);}int main(){return 0;}''', ''),
    ('callback_void_erasure', False, '''void rejected(Tied* source) unsafe {
 void* erased=reinterpret_cast<void*>(source);}''',
     'cast cannot erase or invent quantified lifetime contracts'),
    ('nested_callback_contravariance', True, '''void accepted(NestedTied* source) unsafe {
 NestedUntied* converted=reinterpret_cast<NestedUntied*>(source);}int main(){return 0;}''', ''),
    ('returned_callback_erasure', False, '''void rejected(ReturningTied* source) unsafe {
 ReturningUntied* erased=reinterpret_cast<ReturningUntied*>(source);}''',
     'cast cannot erase or invent quantified lifetime contracts'),
    ('callback_reference_erasure', False, '''void rejected(Tied* source) unsafe {
 Untied& erased=reinterpret_cast<Untied&>(*source);}''',
     'cast cannot erase or invent quantified lifetime contracts'),
]
for kind, call in (
        ('direct', 'replace(^value,^const shorter)'),
        ('constructor', 'Installer change(^value,^const shorter)'),
        ('constructor_template', 'GenericInstaller<unsigned> change(^value,^const shorter)'),
        ('constructor_exception', 'try {ThrowingInstaller change(^value,^const shorter);}catch(unsigned) {}'),
        ('constructor_unsafe_block', 'unsafe {Installer change(^value,^const shorter);}'),
        ('indirect', 'select_setter()(^value,^const shorter)'),
        ('unsafe_block', 'unsafe {replace(^value,^const shorter);}')):
    CASES.append((kind + '_escape', False, '''void rejected() safe {
 unsigned longer=1;View value{^const longer};{unsigned shorter=2;''' + call + ''';}
 unsigned read=*value.value;}''', 'mutable class argument does not preserve its lifetime region'))
CASES.append(('unsafe_caller_escape', False, '''void rejected() unsafe {
 unsigned longer=1;View value{^const longer};{unsigned shorter=2;
 replace(^value,^const shorter);}unsigned read=*value.value;}''',
 'mutable class argument does not preserve its lifetime region'))
CASES.append(('constructor_unsafe_caller_escape', False, '''void rejected() unsafe {
 unsigned longer=1;View value{^const longer};{unsigned shorter=2;
 Installer change(^value,^const shorter);}unsigned read=*value.value;}''',
 'mutable class argument does not preserve its lifetime region'))

with tempfile.TemporaryDirectory(prefix='class-lifetime-variance-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp / 'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'variance_api': 'safe'}}))
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety', '-fcircle-borrow-values',
             '-Wno-everything', '-fmodule-safety-policy=' + str(policy),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22',
             '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    for opt in ('-O0', '-O2'):
        options = flags + [opt]
        module = tmp / 'api.cppm'
        module.write_text('export module variance_api;export {\n' + API + '}\n')
        pcm, obj = tmp / 'api.pcm', tmp / 'api.o'
        for arguments in (['--precompile', str(module), '-o', str(pcm)],
                          ['-c', str(pcm), '-o', str(obj)]):
            built = subprocess.run([str(CLANG), *options, *arguments],
                                   capture_output=True, text=True, timeout=120)
            assert built.returncode == 0, built.stderr
        for imported in (False, True):
            imports = ['-fmodule-file=variance_api=' + str(pcm)] if imported else []
            prefix = 'import variance_api;\n' if imported else API
            for name, valid, body, diagnostic in CASES:
                source, binary = tmp / (name + '.cpp'), tmp / name
                source.write_text('#feature on safety\n' + prefix + body)
                command = [str(CLANG), *options, *imports, str(source)]
                command += [*([str(obj)] if imported else []), '-o', str(binary)] if valid else ['-fsyntax-only']
                built = subprocess.run(command, capture_output=True, text=True, timeout=120)
                if valid:
                    assert built.returncode == 0, name + '\n' + built.stderr
                    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15,
                        env=dict(os.environ, ASAN_OPTIONS='detect_stack_use_after_return=1'))
                    assert ran.returncode == 0, name + '\n' + ran.stderr
                else:
                    assert built.returncode != 0 and diagnostic in built.stderr, name + '\n' + built.stderr
                    assert 'PLEASE submit' not in built.stderr, built.stderr
                print(opt, 'PCM' if imported else 'local', name, 'PASS', flush=True)
print('Class lifetime variance: scoped regions, mutable referent invariance, outlives, '
      'nested generic projections, callback identity, constructors and default arguments; '
      'local/PCM O0/O2 ASan/UBSan')
