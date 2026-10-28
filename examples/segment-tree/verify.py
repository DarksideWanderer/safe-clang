#!/usr/bin/env python3
import hashlib,json,os,pathlib,subprocess
root=pathlib.Path(__file__).resolve().parents[2]
source=root/'examples/segment-tree/main.cpp'
out=root/'build/segment-tree';out.mkdir(exist_ok=True)
clang=root/'llvm-build/bin/clang'
flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(source.parent/'policy.json')]
env=dict(os.environ,ASAN_OPTIONS='detect_stack_use_after_return=1')
runs=[]
for opt in ('-O0','-O2'):
 for sanitized in (False,True):
  exe=out/(opt[1:]+('-san' if sanitized else ''))
  command=[str(clang)]+flags+[opt]+(['-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22','-fsanitize=address,undefined','-fno-sanitize-recover=all'] if sanitized else [])+[str(source),'-o',str(exe)]
  subprocess.run(command,check=True)
  result=subprocess.run([str(exe)],env=env,capture_output=True,text=True)
  assert result.returncode==0,(result.returncode,result.stderr)
  runs.append({'command':command,'exit':result.returncode})
# Keep safety refusals distinct from the algorithm's differential checks.
negative=[('int main() safe {unsigned long long x=0ull;auto a=^x;auto b=^x;*a=1ull;*b=2ull;}', 'borrow'),
          ('int main() safe {unsigned long long x=0ull;const unsigned long long^ view=^const x;x=1ull;return *view==1ull?0:1;}', 'borrow')]
for i,(body,needle) in enumerate(negative):
 p=out/f'negative-{i}.cpp';p.write_text(body)
 result=subprocess.run([str(clang)]+flags+['-fsyntax-only',str(p)],capture_output=True,text=True)
 assert result.returncode!=0 and needle in result.stderr and 'PLEASE submit' not in result.stderr,result.stderr
 (out/f'negative-{i}.log').write_text(result.stderr)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(out/'evidence.json').write_text(json.dumps({'source_sha256':sha(source),'driver_sha256':sha(clang),'dylib_sha256':sha(root/'llvm-build/lib/libclang-cpp.dylib'),'runs':runs,'differential_operations_per_run':32000,'safety_refusals':len(negative)},indent=2)+'\n')
print('PASS: O0/O2, plain and ASan/UBSan; 32000 differential operations per run; 2 borrow refusals.')
