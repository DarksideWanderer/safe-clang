#!/usr/bin/env python3
"""Captured callable regions retain per-value provenance across CFG and PCM."""
import os
import pathlib
import subprocess
import tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
API='''
const unsigned permanent=17u;
const unsigned^/static stable/(b)(const unsigned^/b) safe {return ^const permanent;}
void generic/(b)(const unsigned^/b) safe {}
struct Reader/(a){const unsigned^/a (*value)/(b)(const unsigned^/b) safe;};
struct Consumer/(a){void (*value)(const unsigned^/a) safe;};
struct ReaderPair/(a,b){const unsigned^/a (*value)(const unsigned^/b) safe;};
const unsigned^/a invoke/(a)(const unsigned^/a input,
 const unsigned^/a callback/(b)(const unsigned^/b) safe) safe {return callback(input);}
void consume/(a)(const unsigned^/a input,void callback(const unsigned^/a) safe) safe {callback(input);}
auto relay/(a)(const unsigned^/a input,const unsigned^/a callback/(b)(const unsigned^/b) safe)
 safe -> const unsigned^/a (*)/(c)(const unsigned^/c) safe {return callback;}
const unsigned^/a read/(a)(Reader/a input,const unsigned^/a value) safe {return input.value(value);}
Reader/a relay_reader/(a)(Reader/a input) safe {return rel input;}
void call_stored/(a)(Consumer/a input,const unsigned^/a value) safe {input.value(value);}
ReaderPair/a/b relay_pair/(a,b)(ReaderPair/a/b input) safe {return rel input;}
ReaderPair/a/b make_pair/(a,b)(const unsigned^/a first,const unsigned^/b second,const unsigned^/a callback(const unsigned^/b) safe) safe {return {callback};}
const unsigned^/a read_pair/(a,b)(ReaderPair/a/b input,const unsigned^/b value) safe {return input.value(value);}
const unsigned^/a immediate_pair/(a,b)(ReaderPair/a/b input,const unsigned^/b value) safe {return relay_pair(rel input).value(value);}
'''
PROGRAM='''int main() safe {
 unsigned value=3u;
 consume(^const value,&generic);
 if(*invoke(^const value,&stable)!=17u)return 1;
 auto f=relay(^const value,&stable);auto g=f;
 if(*g(^const value)!=17u)return 2;
 Reader reader{&stable};auto other=relay_reader(rel reader);
 if(*read(rel other,^const value)!=17u)return 3;
 Consumer consumer{&generic};call_stored(rel consumer,^const value);
 ReaderPair pair{&stable};auto pair_copy=relay_pair(rel pair);
 if(*read_pair(rel pair_copy,^const value)!=17u)return 4;
 ReaderPair immediate{&stable};
 if(*immediate_pair(rel immediate,^const value)!=17u)return 5;
 auto built=make_pair(^const value,^const value,&stable);
 if(*read_pair(rel built,^const value)!=17u)return 6;
 auto factory=&make_pair;auto indirect=factory(^const value,^const value,&stable);
 if(*read_pair(rel indirect,^const value)!=17u)return 7;
 return 0;
}'''
CASES=[
 ('''void good/(a)(const unsigned^/a input,void callback(const unsigned^/a) safe) safe {callback(input);}''',True),
 ('''void good/(a)(const unsigned^/a input,void callback(const unsigned^/a) safe) safe {auto f=callback;f(input);}''',True),
 ('''void good/(a)(const unsigned^/a input,void callback(const unsigned^/a) safe,bool condition) safe {auto f=callback;if(condition)f=callback;else f=callback;f(input);}''',True),
 ('''void good/(a)(Consumer/a input,const unsigned^/a value) safe {auto copy=input;copy.value(value);}''',True),
 ('''const unsigned^/a good/(a,b)(ReaderPair/a/b input,const unsigned^/b value) safe {auto copy=relay_pair(rel input);return copy.value(value);}''',True),
]
CASES += [
 ("void good/(a)(Consumer/a input,Consumer/a other,const unsigned^/a value) safe {unsafe {input=other;}input.value(value);}",True),
 ("void good/(a)(Consumer/a input,void callback(const unsigned^/a) safe,const unsigned^/a value) safe {input.value=callback;input.value(value);}",True),
]
for effect in ('safe','unsafe'):
 CASES += [
 (f'''void bad/(a)(const unsigned^/a input,void callback(const unsigned^/a) safe) {effect} {{unsigned shorter=1u;callback(^const shorter);}}''',False),
 (f'''void bad/(a)(Consumer/a input) {effect} {{unsigned shorter=1u;input.value(^const shorter);}}''',False),
 (f'''void bad/(a)(Consumer/a input) {effect} {{auto copy=input;unsigned shorter=1u;copy.value(^const shorter);}}''',False),
 (f'''auto bad/(a,b)(const unsigned^/a first,const unsigned^/b second,const unsigned^/b callback/(c)(const unsigned^/c) safe) {effect} -> const unsigned^/a (*)/(d)(const unsigned^/d) safe {{return callback;}}''',False),
 (f'''Reader/a bad/(a,b)(Reader/b input,const unsigned^/a value) {effect} {{return rel input;}}''',False),
 (f'''const unsigned^/b bad/(a,b)(ReaderPair/a/b input,const unsigned^/b value) {effect} {{return relay_pair(rel input).value(value);}}''',False),
 (f'''const unsigned^/a bad/(a,b)(ReaderPair/a/b input,const unsigned^/a value) {effect} {{return relay_pair(rel input).value(value);}}''',False),
 (f'''ReaderPair/b/a bad/(a,b)(ReaderPair/a/b input) {effect} {{return rel input;}}''',False),
 (f'''ReaderPair/b/a bad/(a,b)(const unsigned^/a first,const unsigned^/b second,const unsigned^/a callback(const unsigned^/b) safe) {effect} {{return {{callback}};}}''',False),
 ]
CASES.append(('unsigned bad/(a)(const unsigned^/a input,const unsigned^/a callback/(b)(const unsigned^/b) safe) safe {const unsigned^ saved;{unsigned local=1u;saved=relay(^const local,callback)(^const local);}return *saved;}',False))
flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
count=0
with tempfile.TemporaryDirectory(prefix='captured-values-') as directory:
 d=pathlib.Path(directory);module=d/'api.cppm';pcm=d/'api.pcm';obj=d/'api.o';source=d/'client.cpp';binary=d/'client'
 module.write_text('export module captured;export {\n'+API+'}\n')
 def compile(args,okay=True):
  global count
  r=subprocess.run([str(CLANG)]+flags+args,capture_output=True,text=True,timeout=120)
  assert (r.returncode==0)==okay,(source.read_text()[-1000:] if source.exists() else '')+'\n'+r.stderr
  assert 'PLEASE submit' not in r.stderr,r.stderr
  if not okay:assert 'error:' in r.stderr,r.stderr
  count+=1
 compile(['--precompile',str(module),'-o',str(pcm)])
 for imported in (False,True):
  for body,okay in CASES:
   source.write_text(('import captured;\n' if imported else API)+body)
   compile((['-fmodule-file=captured='+str(pcm)] if imported else [])+['-fsyntax-only',str(source)],okay)
 for opt in ('-O0','-O2'):
  for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=[opt]+san
   compile(options+['--precompile',str(module),'-o',str(pcm)])
   compile(options+['-c',str(pcm),'-o',str(obj)])
   for imported in (False,True):
    source.write_text(('import captured;\n' if imported else API)+PROGRAM)
    compile(options+(['-fmodule-file=captured='+str(pcm)] if imported else [])+[str(source)]+([str(obj)] if imported else [])+['-o',str(binary)])
    r=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr+str(r.returncode)
print(f'Captured callable values: {count} compilations; direct/indirect calls, callback results, class fields, copying, rebinding, CFG joins, safe/unsafe refusals and 8 O0/O2 plain ASan/UBSan executions passed')
