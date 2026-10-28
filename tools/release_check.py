#!/usr/bin/env python3
"""Build and validate the supported macOS arm64 release candidate.

Produces an evidence report, not a certificate of whole-language soundness.
All gates are mandatory, including native Clang, sanitizers and Z3.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile
from build_artifacts import digest

root = pathlib.Path(__file__).resolve().parent.parent


def verify_binaries(expected):
    for name, sha in expected.items():
        path=pathlib.Path(name)
        if not path.is_file() or digest(path)!=sha:
            raise RuntimeError('binary changed during release validation: '+name)

def sources():
    files = [root/'CMakeLists.txt', root/'.clang-format']
    files += list(root.glob('*.md'))
    for folder in ['src','include','runtime','tests','tools','frontend','proofs','standards','compatibility','docs']:
        files += [p for p in (root/folder).rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    return {str(p.relative_to(root)): digest(p) for p in sorted(files)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llvm-root',type=pathlib.Path,default=pathlib.Path('/opt/homebrew/opt/llvm'))
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--clang-reference',type=pathlib.Path,
                        default=root/'build/clang-pristine/bin/clang',
                        help='independent Clang built from the untouched official 22.1.2 archive')
    parser.add_argument('--report',type=pathlib.Path,default=root/'build/release-report.json')
    args=parser.parse_args()
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        parser.error('release validation currently supports macOS arm64 only')
    solver=shutil.which('z3')
    if not solver: parser.error('Z3 is required; the proof gate cannot be skipped')
    compiler=args.llvm_root/'bin/clang++'
    version=subprocess.check_output([str(compiler),'--version'],text=True)
    if 'version 22.1.2' not in version: parser.error('LLVM/Clang 22.1.2 is required')
    (root/'build').mkdir(exist_ok=True)
    lock = (root/'build/.release-check.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('another release validation is already running')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    logs=pathlib.Path(tempfile.mkdtemp(prefix='release-',dir=args.report.parent))
    before=sources()
    report={'status':'running','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'platform':platform.platform(),'compiler':version,'sources':before,'gates':[],
            'scope':'Supported safe C++ subset; see docs/VALIDATION.md and docs/SAFETY.md'}
    report['full_compatibility_status']='not_established'
    report['subset_status']='not_validated'
    frozen_binaries={}
    def save():
        temporary=args.report.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
        temporary.replace(args.report)
    def gate(name,command):
        verify_binaries(frozen_binaries)
        log=logs/(name+'.log')
        print(name,flush=True)
        entry={'name':name,'command':[str(a) for a in command],'log':str(log)}
        report['gates'].append(entry);save()
        with log.open('w') as stream:
            result=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT)
        entry['exit_code']=result.returncode;entry['log_sha256']=digest(log);save()
        verify_binaries(frozen_binaries)
        if result.returncode: raise RuntimeError(f'{name} failed; see {log}')
    save()
    try:
        gate('configure',['cmake','-S',root,'-B',root/'build',
             '-DLLVM_DIR='+str(args.llvm_root/'lib/cmake/llvm'),'-DClang_DIR='+str(args.llvm_root/'lib/cmake/clang')])
        gate('plugin-build',['cmake','--build',root/'build','-j',str(args.jobs)])
        gate('native-build',[sys.executable,root/'tools/build_frontend.py','--llvm',args.llvm_root,'--jobs',str(args.jobs)])
        binaries=[root/'build/ModuleSafety.so',root/'llvm-build/bin/clang-22',
                  root/'llvm-build/lib/libclang-cpp.dylib',args.llvm_root/'lib/libLLVM.dylib',
                  args.clang_reference,root/'.toolchains/lean-4.24.0-darwin_aarch64/bin/lean']
        frozen_binaries.update({str(p.resolve()):digest(p) for p in binaries})
        report['binaries']=dict(frozen_binaries);save()
        gate('plugin-tests',['ctest','--test-dir',root/'build','--output-on-failure'])
        gate('clang-default-compatibility',[sys.executable,root/'tools/clang_compatibility.py',
             '--reference',args.clang_reference,'--output',logs/'clang-compatibility.json'])
        gate('clang-upstream-lit',[sys.executable,root/'tools/clang_upstream_lit.py',
             '--output',logs/'clang-upstream-lit.json'])
        gate('official-compatibility-evidence',[sys.executable,root/'tools/circle_compatibility.py',
             '--output',logs/'circle-compatibility.json'])
        gate('native-tests',[sys.executable,root/'tools/test_frontend.py'])
        gate('proofs',[sys.executable,root/'tests/prove_conversions.py',solver])
        gate('lean-kernel',[sys.executable,root/'tools/check_lean.py'])
        gate('ub-inventory',[sys.executable,root/'tools/ub_inventory.py','--check'])
        gate('union-proofs',[sys.executable,root/'tests/prove_union_model.py',solver])
        gate('patch-reproduction',[sys.executable,root/'tests/verify_frontend_patch.py'])
        gate('example-build',[sys.executable,root/'tools/build_modules.py',root/'examples/native-modules.json',
             '--clang',root/'llvm-build/bin/clang','--native','--output',root/'native-module-build'])
        generation = (root/'native-module-build').resolve()
        gate('example-integrity',[sys.executable,root/'tools/verify_build.py',generation])
        gate('example-link',[root/'llvm-build/bin/clang++','-std=c++20','-O2','-fprebuilt-module-path='+str(generation),
             root/'examples/main.cpp',generation/'native_example.o',generation/'safety.o',
             '-o',generation/'example'])
        gate('example-run',[generation/'example'])
        if sources()!=before: raise RuntimeError('source changed during validation; rerun all gates')
        verify_binaries(frozen_binaries)
        report['source_fingerprint']=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
        report['subset_status']='validated_candidate'
        save()
        # Inventory success is not official language compatibility. Keep this
        # independent mandatory gate, and preserve the subset result on failure.
        gate('official-full-compatibility',[sys.executable,root/'tools/circle_compatibility.py',
             '--output',logs/'circle-full-compatibility.json','--require-full'])
        report['status']='fully_compatible_candidate'
        report['full_compatibility_status']='validated'
    except BaseException as error:
        report['status']='failed';report['error']=str(error)
        report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        save();raise
    report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print(f'All mandatory gates passed: {args.report}',flush=True)

if __name__=='__main__':
    main()
