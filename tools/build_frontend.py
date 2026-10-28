#!/usr/bin/env python3
"""Apply the pinned Clang patch, copy the checker, and build the native driver."""
import argparse
import hashlib
import json
import pathlib
import shutil
import re
import platform
import subprocess

root = pathlib.Path(__file__).resolve().parent.parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=pathlib.Path, default=root/'llvm-project-22.1.2.src')
p.add_argument('--build', type=pathlib.Path, default=root/'llvm-build')
p.add_argument('--llvm', type=pathlib.Path, default=pathlib.Path('/opt/homebrew/opt/llvm'))
p.add_argument('--jobs', type=int, default=4)
a = p.parse_args()
source, build = a.source.resolve(), a.build.resolve()
if not (source/'clang/lib/Parse/ParseStmt.cpp').is_file():
    raise SystemExit('Expected the llvm-project-22.1.2 source archive')
version = (source/'cmake/Modules/LLVMVersion.cmake').read_text()
if any(not re.search(r'set\(LLVM_VERSION_'+key+' '+value+r'\)', version) for key, value in [('MAJOR','22'),('MINOR','1'),('PATCH','2')]):
    raise SystemExit('This frontend patch requires exactly LLVM 22.1.2')
patch = root/'frontend/clang-22.1.2.patch'
manifest = json.loads((root/'frontend/source-hashes.json').read_text())
if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['patch_sha256']:
    raise SystemExit('Frontend patch/hash manifest mismatch; regenerate and verify the source manifest')
parser = source/'clang/include/clang/Parse/Parser.h'
if 'ParseUnsafeStatement' not in parser.read_text():
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(root/'frontend/clang-22.1.2.patch')], cwd=source, check=True)
mismatches = [name for name, digest in manifest['files'].items()
              if not (source/name).is_file() or hashlib.sha256((source/name).read_bytes()).hexdigest() != digest]
if mismatches:
    raise SystemExit('Patched source is outdated or modified: '+', '.join(mismatches)+
                     '. Use a fresh LLVM 22.1.2 source tree with this patch.')
for name in ('ModuleSafety.cpp', 'FlowAnalysis.cpp', 'FlowAnalysis.h', 'SafetyContracts.h', 'SafetyTraversal.h'):
    shutil.copy2(root/'src'/name, source/'clang/lib/Frontend'/name)
shutil.copy2(root/'frontend/ModuleSafety.h', source/'clang/include/clang/Frontend/ModuleSafety.h')
platform_options = []
if platform.system() == 'Darwin':
    sdk = subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip()
    platform_options = ['-DDEFAULT_SYSROOT='+sdk, '-DCLANG_DEFAULT_CXX_STDLIB=libc++']
subprocess.run(['cmake', '-S', str(source/'clang'), '-B', str(build), '-G', 'Ninja',
    '-DCMAKE_BUILD_TYPE=Release', '-DLLVM_DIR='+str(a.llvm/'lib/cmake/llvm'),
    '-DMODULE_SAFETY_FRONTEND_HASH='+manifest['patch_sha256'],
    '-DCMAKE_CXX_FLAGS_RELEASE=-O1 -DNDEBUG', '-DCMAKE_C_FLAGS_RELEASE=-O1 -DNDEBUG',
    '-DLLVM_LINK_LLVM_DYLIB=ON', '-DCLANG_LINK_CLANG_DYLIB=ON',
    '-DCLANG_INCLUDE_TESTS=OFF', '-DLLVM_INCLUDE_TESTS=OFF',
    '-DLLVM_ENABLE_ASSERTIONS=ON', '-DCMAKE_C_COMPILER='+str(a.llvm/'bin/clang'),
    '-DCMAKE_CXX_COMPILER='+str(a.llvm/'bin/clang++')]+platform_options, check=True)
subprocess.run(['cmake', '--build', str(build), '--target', 'clang', '-j', str(a.jobs)], check=True)
