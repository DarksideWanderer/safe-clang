#!/usr/bin/env python3
"""Kernel-check local models; reject unfinished proofs or extra assumptions."""
import argparse,hashlib,json,os,pathlib,re,subprocess,sys
root=pathlib.Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--lean',type=pathlib.Path,default=root/'.toolchains/lean-4.24.0-darwin_aarch64/bin/lean')
args=parser.parse_args()
if not args.lean.is_file():parser.error('Lean 4.24.0 is required; the kernel proof gate cannot be skipped')
if sys.flags.optimize:parser.error('proof validation must run without Python optimization')
version=subprocess.check_output([str(args.lean),'--version'],text=True)
if 'version 4.24.0,'not in version:parser.error('expected pinned Lean 4.24.0')
manifest=json.loads((root/'proofs/lean-toolchain.json').read_text())
for name,expected in manifest['files'].items():
 path=root/name
 if not path.is_file()or hashlib.file_digest(path.open('rb'),'sha256').hexdigest()!=expected:
  raise SystemExit('Lean toolchain integrity mismatch: '+name)
environment={k:v for k,v in os.environ.items()if not k.startswith("LEAN_")}
count=0
for source in sorted((root/'proofs').glob('*.lean')):
 text=source.read_text()
 # Strip comments before checking the proof language. Nested block comments
 # are deliberately prohibited here to keep this gate small and inspectable.
 if re.search(r'/-[^\n]*?/-',text):raise SystemExit('nested block comments not supported by proof policy')
 clean=re.sub(r'/\-.*?\-/', '',text,flags=re.S)
 clean=re.sub(r'--[^\n]*','',clean)
 if re.search(r'\b(sorry|admit|axiom|unsafe|native_decide)\b',clean):
  raise SystemExit('unfinished proof or additional trusted mechanism: '+str(source))
 dependencies=subprocess.check_output([str(args.lean),'--deps',str(source)],cwd=root,text=True,env=environment)
 for dependency in dependencies.splitlines():
  if str(pathlib.Path(dependency).resolve().relative_to(root))not in manifest['files']:
   raise SystemExit('unverified proof dependency: '+dependency)
 result=subprocess.run([str(args.lean),str(source)],cwd=root,text=True,capture_output=True,timeout=120,env=environment)
 if result.returncode or 'warning:'in result.stdout or 'sorryAx'in result.stdout:
  raise SystemExit(result.stdout+result.stderr)
 declarations=re.findall(r'^theorem\s+(\w+)',clean,re.M)
 for declaration in declarations:
  name='ModuleSafety.'+declaration
  matches=list(re.finditer(r"'"+re.escape(name)+r"' (does not depend on any axioms|depends on axioms: \[([^\]]*)\])",result.stdout))
  if len(matches)!=1:raise SystemExit('missing or ambiguous kernel assumption audit: '+name)
  match=matches[0]
  assumptions={x.strip()for x in (match.group(2)or'').split(',')if x.strip()}
  if not assumptions<={'propext'}:raise SystemExit('unapproved proof assumption: '+name+str(assumptions))
 count+=len(declarations)
 print(source.name+': '+str(len(declarations))+' kernel-checked local theorems')
print(f'{count} local theorems checked; Clang/LLVM refinement and whole-C++ soundness remain unproved')
