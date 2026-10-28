#!/usr/bin/env python3
"""Native safety selection comes from compiler options, not feature directives."""
import json,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='circle-command-mode-') as name:
 d=pathlib.Path(name);policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{}}))
 clang=ROOT/'llvm-build/bin/clang';p=d/'main.cpp';h=d/'library.h'
 safe=[str(clang),'-std=c++20','-fmodule-safe','-fmodule-safety-policy='+str(policy),'-fsyntax-only',str(p)]
 def check(source,okay,diagnostic=''):
  p.write_text(source);r=subprocess.run(safe,capture_output=True,text=True)
  assert (r.returncode==0)==okay,r.stderr
  if diagnostic: assert diagnostic in r.stderr,r.stderr
  assert 'PLEASE submit' not in r.stderr,r.stderr
 # A bare external declaration cannot acquire a checked contract from the
 # caller's command mode, including through an inferred function pointer.
 check('unsigned external();unsigned caller() safe {return external();}',False,'module-safety:')
 check('unsigned external(unsigned) safe;unsigned external();unsigned caller() safe {return external();}',False,'module-safety:')
 check('unsigned external();unsigned caller() safe {auto p=&external;return p();}',False,'module-safety:')
 check('unsigned external();using Checked=unsigned __attribute__((safe_function))();Checked* p=&external;',False,'error:')
 check('unsigned external();unsigned caller() safe {unsafe {return external();}}',True)
 check('unsigned external() safe;unsigned caller() safe {return external();}',True)
 check('unsigned external() safe;unsigned external() safe {return 7u;}unsigned caller(){return external();}',True)
 h.write_text('inline unsigned value(unsigned x) {return x;}')
 check('#include "library.h"\nunsigned f(unsigned x) {return value(x);}',True)
 check('#feature on safety\n#include "library.h"\nunsigned f(unsigned x) {return value(x);}',True)
 check('unsigned f(unsigned* p) {return *p;}',False,'module-safety:')
 h.write_text('inline unsigned value(unsigned* p) {return *p;}')
 check('#include "library.h"\nunsigned f(unsigned x) {return x;}',False,'module-safety:')
 h.write_text('inline unsigned value(unsigned* p) {unsafe {return *p;}}')
 check('#include "library.h"\nunsigned f(unsigned* p) {return value(p);}',True)
 # Run an ordinary command-selected safe TU at O0 without any directive.
 h.write_text('inline unsigned value(unsigned x) {return x;}')
 p.write_text('#include "library.h"\nint main() {return value(7u)==7u ? 0 : 1;}')
 binary=d/'program'
 r=subprocess.run([arg for arg in safe if arg!='-fsyntax-only']+['-O0','-o',str(binary)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 assert subprocess.run([str(binary)]).returncode==0
 # Preserve the ordinary function ABI across separately compiled checked
 # and legacy translation units; the wrapper's external effect remains safe.
 provider=d/'provider.cpp';legacy=d/'legacy.cpp';legacy_object=d/'legacy.o'
 provider.write_text('unsigned external() safe {return 7u;}')
 legacy.write_text('unsigned legacy(unsigned* p) {return *p;}')
 p.write_text('unsigned external() safe;unsigned legacy(unsigned*);unsigned wrapper(unsigned x) safe {unsafe {return legacy(&x);}}int main() safe {return external()==7u && wrapper(11u)==11u ? 0 : 1;}')
 for optimization in ('-O0','-O2'):
  for sanitized in (False,True):
   runtime=[optimization]
   if sanitized: runtime+=['-fsanitize=address,undefined','-fno-sanitize-recover=all','-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
   r=subprocess.run([str(clang),'--driver-mode=g++','-std=c++20']+runtime+['-c',str(legacy),'-o',str(legacy_object)],capture_output=True,text=True)
   assert r.returncode==0,r.stderr
   r=subprocess.run([arg for arg in safe if arg!='-fsyntax-only']+['--driver-mode=g++']+runtime+[str(provider),str(legacy_object),'-o',str(binary)],capture_output=True,text=True)
   assert r.returncode==0,r.stderr
   assert subprocess.run([str(binary)]).returncode==0
 p.write_text('unsigned f(unsigned* p) {return *p;}')
 for standard in ('c++17','c++20','c++23'):
  r=subprocess.run([str(clang),'-std='+standard,'-fmodule-unsafe','-fmodule-safety-policy='+str(policy),'-fsyntax-only',str(p)],capture_output=True,text=True)
  assert r.returncode==0,r.stderr
 r=subprocess.run([str(clang),'-x','c','-std=c17','-fmodule-unsafe','-fmodule-safety-policy='+str(policy),'-fsyntax-only',str(p)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 # The mode is selected by the compile directive alone, with no project policy
 # and no feature directive: every function defined in the checked unit is safe
 # by default, under either spelling of the directive.
 bare=[str(clang),'-std=c++20','-fcircle-safety','-fsyntax-only',str(p)]
 def check_bare(source,okay,diagnostic=''):
  p.write_text(source);r=subprocess.run(bare,capture_output=True,text=True)
  assert (r.returncode==0)==okay,r.stderr
  if diagnostic: assert diagnostic in r.stderr,r.stderr
 check_bare('unsigned f(unsigned x) {return x;}',True)
 check_bare('unsigned f(unsigned* p) {return *p;}',False,'module-safety:')
 check_bare('unsigned f(unsigned* p) {unsafe {return *p;}}',True)
 check_bare('#feature on safety\nunsigned f(unsigned* p) {return *p;}',False,'module-safety:')
 check_bare('export module single;\nunsigned f(unsigned* p) {return *p;}',False,'module-safety:')
 check_bare('export module single;\nexport unsigned answer() {return 7u;}',True)
 p.write_text('export module single;\nunsigned f(unsigned* p) {return *p;}')
 r=subprocess.run([str(clang),'-std=c++20','-fmodule-unsafe','-fsyntax-only',str(p)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 # One module, compiled and linked with the directive on the command line.
 mod=d/'single.cppm';entry=d/'single_main.cpp'
 mod.write_text('export module single;\nexport unsigned answer() {return 7u;}')
 entry.write_text('import single;\nint main() {return answer()==7u ? 0 : 1;}')
 pcm=d/'single.pcm';obj=d/'single.o'
 r=subprocess.run([str(clang),'--driver-mode=g++','-std=c++20','-fcircle-safety','--precompile',str(mod),'-o',str(pcm)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 r=subprocess.run([str(clang),'--driver-mode=g++','-std=c++20','-fcircle-safety','-c',str(pcm),'-o',str(obj)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 r=subprocess.run([str(clang),'--driver-mode=g++','-std=c++20','-fcircle-safety','-fmodule-file=single='+str(pcm),str(entry),str(obj),'-O0','-o',str(binary)],capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 assert subprocess.run([str(binary)]).returncode==0
print('Command-only ordinary TU safety, checked header bodies, external direct/indirect contracts, O0/O2 ASan/UBSan linked wrappers and legacy C++17/20/23 modes passed; directive-only selection checks a single unit or module with no policy, and the retained safety directive is unnecessary')
