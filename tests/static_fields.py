#!/usr/bin/env python3
"""Static class projection must be established on every typed write path."""
import json,os,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''module;
extern "C" void external();
export module static_fields;
export const unsigned permanent=13u;
export struct Field {
 const unsigned^/static value;
 const unsigned^/static get(const self^) safe {return self->value;}
};
export struct Bound {
 const unsigned^/static value;
 explicit Bound(const unsigned^/static input) safe :value(input) {}
 const unsigned^/static get(const self^) safe {return self->value;}
};
export template<class T> struct Generic {
 const T^/static value;
 const T^/static get(const self^) safe {return self->value;}
};
export const unsigned^/static projected(Field value) safe {return value.get();}
export struct Text {const [char;dyn]^/static data;};
export void consume(Text value) safe {unsafe {external();}}
char mutable_data[2]={'a','b'};
export const [char;dyn]^/static mutable_text() safe {unsafe {return ^*__slice_pointer(static_cast<const char*>(mutable_data),2u);}}
export unsigned run() safe {
 consume(Text{^*__slice_pointer(static_cast<const char*>("literal"),7u)});
 Field a{^const permanent};Bound b(^const permanent);Generic<unsigned> c{^const permanent};
 auto loan=projected(cpy a);
 return *loan+*b.get()+*c.get();
}
'''
NEGATIVES=(
 ('void bad() safe {unsigned local=1u;Field a{^const local};}', 'static field lifetime contract'),
 ('void bad() unsafe {unsigned local=1u;Field a{^const local};}', 'static field lifetime contract'),
 ('void bad() safe {unsigned local=1u;unsafe {Field a{^const local};}}', 'static field lifetime contract'),
 ('void bad() unsafe {thread_local const unsigned local=1u;Field a{^const local};}', 'static field lifetime contract'),
 ('void bad() safe {unsigned local=1u;Bound a(^const local);}', 'static lifetime contract'),
 ('void bad() unsafe {unsigned local=1u;Bound a(^const local);}', 'static lifetime contract'),
 ('struct Wrong {const unsigned^/static value;Wrong(const unsigned^ input) unsafe :value(input){}};', 'static field lifetime contract'),
 ('void bad() unsafe {unsigned local=1u;Generic<unsigned> a{^const local};}', 'static field lifetime contract'),
 ('void bad() unsafe {unsigned long local=1ul;Generic<unsigned long> a{^const local};}', 'static field lifetime contract'),
 ('void bad() unsafe {Field a{^const permanent};unsigned local=1u;a.value=^const local;}', 'static field lifetime contract'),
 ('Field bad() unsafe {unsigned local=1u;return Field{^const local};}', 'static field lifetime contract'),
 ('void bad() unsafe {Field a{};}', 'static field lifetime contract'),
 ('void bad() unsafe {Field a;}', 'initialized permanent borrow'),
 ('void bad() unsafe {extern void* unknown;auto forged=reinterpret_cast<Field*>(unknown);}', 'static field representation cast'),
 ('struct Raw {const unsigned^ value;}; void bad() unsafe {unsigned local=1u;Raw raw{^const local};auto forged=reinterpret_cast<Field*>(&raw);}', 'static field representation cast'),
 ('struct Child {unsigned x;Child() safe =default;Child(const Child&) unsafe =default;};struct Parent{Child value;};void bad() safe {Parent a{};Parent b=cpy a;}', 'unsafe or unclassified'),
 ('void bad() safe {consume(Text{mutable_text()});}', 'mutable global storage'),
 ('void bad() safe {consume(Text{^*__slice_pointer(static_cast<const char*>("literal"),999u)});}', 'static field lifetime contract'),
 ('const char* unsafe opaque="literal"; const [char;dyn]^/static bad() unsafe {return ^*__slice_pointer(opaque,7u);}', 'static return lifetime contract'),
 ('const [char;dyn]^/static bad() unsafe {return ^*__slice_pointer(reinterpret_cast<const char*>(static_cast<unsigned char>(reinterpret_cast<unsigned long>(static_cast<const char*>("literal")))),7u);}', 'static return lifetime contract'),
)
with tempfile.TemporaryDirectory(prefix='circle-static-fields-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json'
 policy.write_text(json.dumps({'version':1,'modules':{'static_fields':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def check(args,okay=True,diagnostic=''):
  r=subprocess.run([str(CLANG)]+args,capture_output=True,text=True,timeout=120)
  assert (r.returncode==0)==okay,r.stderr+'\n'+str(args)+'\n'+(d/'client.cpp').read_text() if (d/'client.cpp').exists() else r.stderr
  assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr,r.stderr
  if diagnostic:assert diagnostic in r.stderr,r.stderr
  return r
 local_api=API.replace('module;','').replace('export module static_fields;','').replace('export ','')
 for opt in ('-O0','-O2'):
  for sanitizer in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+sanitizer;m=d/'static_fields.cppm';pcm=d/'static_fields.pcm';obj=d/'static_fields.o';p=d/'client.cpp';binary=d/'run'
   provider=d/'provider.cpp';provider_obj=d/'provider.o';provider.write_text('extern "C" void external() {}\n')
   check(['--driver-mode=g++','-std=c++20',opt]+sanitizer+['-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-c',str(provider),'-o',str(provider_obj)])
   m.write_text(API);check(options+['--precompile',str(m),'-o',str(pcm)]);check(options+['-c',str(pcm),'-o',str(obj)])
   p.write_text('import static_fields;const unsigned long client_permanent=17ul;int main() safe {Generic<unsigned long> value{^const client_permanent};return run()==39u && *value.get()==17ul?0:1;}')
   check(options+['-fmodule-file=static_fields='+str(pcm),str(p),str(obj),str(provider_obj),'-o',str(binary)])
   x=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30);assert x.returncode==0,x.stderr+str(x.returncode)
   p.write_text(local_api+'int main() safe {return run()==39u?0:1;}')
   check(options+[str(p),str(provider_obj),'-o',str(binary)]);x=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30);assert x.returncode==0,x.stderr+str(x.returncode)
   for text,diag in NEGATIVES:
    for imported in (False,True):
     p.write_text(('import static_fields;' if imported else local_api)+text)
     check(options+(['-fmodule-file=static_fields='+str(pcm)] if imported else [])+['-fsyntax-only',str(p)],False,diag)
print('Static fields: aggregate/constructor/template projection and local owner lifetime independence, new imported template specialization, bounded literal/array origins and linked legacy provider, local/PCM O0/O2 plain ASan/UBSan; 160 typed write/constructor/return/default/cast refusals including unsafe, TLS, unsafe subobject copying, mutable global invalidation and opaque/oversized/corrupted raw slices passed')
