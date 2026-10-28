#!/usr/bin/env python3
"""Build an independent unmodified Clang from the retained official archive.

Existing source contents must match the archive; never overwrite modifications.
The backend LLVM shared library is the separately recorded installed 22.1.2.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import tarfile

ROOT=pathlib.Path(__file__).resolve().parent.parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=pathlib.Path,default=ROOT/'build/pristine-source/llvm-project-22.1.2.src')
    p.add_argument('--build',type=pathlib.Path,default=ROOT/'build/clang-pristine')
    p.add_argument('--llvm',type=pathlib.Path,default=pathlib.Path('/opt/homebrew/opt/llvm'))
    p.add_argument('--jobs',type=int,default=2)
    a=p.parse_args();source=a.source.resolve();build=a.build.resolve()
    if source.name!='llvm-project-22.1.2.src':
        p.error('source directory name must match the official archive root')
    archive=ROOT/'downloads/llvm-project-22.1.2.src.tar.xz'
    version=subprocess.check_output([str(a.llvm/'bin/clang'),'--version'],text=True)
    if 'version 22.1.2' not in version:p.error('installed LLVM must be 22.1.2')
    if not source.exists():
        source.parent.mkdir(parents=True,exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(source.parent,filter='data')
        if not source.exists():p.error('source path must use the archive root directory name')
    verified={}
    with tarfile.open(archive) as tar:
        for member in tar:
            if not member.isfile():continue
            relative=pathlib.PurePosixPath(member.name)
            if relative.parts[0]!='llvm-project-22.1.2.src' or '..' in relative.parts:
                raise SystemExit('unexpected archive path')
            name=pathlib.Path(*relative.parts[1:]);target=source/name
            expected=hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
                raise SystemExit('pristine source changed; preserved without overwriting: '+str(target))
            verified[str(name)]=expected
    sdk=subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
    configure=['cmake','-S',str(source/'clang'),'-B',str(build),'-G','Ninja',
        '-DCMAKE_BUILD_TYPE=Release','-DLLVM_DIR='+str(a.llvm/'lib/cmake/llvm'),
        '-DCMAKE_CXX_FLAGS_RELEASE=-O1 -DNDEBUG','-DCMAKE_C_FLAGS_RELEASE=-O1 -DNDEBUG',
        '-DLLVM_LINK_LLVM_DYLIB=ON','-DCLANG_LINK_CLANG_DYLIB=ON',
        '-DCLANG_INCLUDE_TESTS=OFF','-DLLVM_INCLUDE_TESTS=OFF','-DLLVM_ENABLE_ASSERTIONS=ON',
        '-DCMAKE_C_COMPILER='+str(a.llvm/'bin/clang'),'-DCMAKE_CXX_COMPILER='+str(a.llvm/'bin/clang++'),
        '-DCLANG_DEFAULT_CXX_STDLIB=libc++','-DDEFAULT_SYSROOT='+sdk]
    subprocess.run(configure,check=True)
    command=['cmake','--build',str(build),'--target','clang','-j',str(a.jobs)]
    subprocess.run(command,check=True)
    def digest(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    identity={'baseline':'official unmodified Clang 22.1.2','source_form':'release archive',
        'archive_sha256':digest(archive),'source_sha256':hashlib.sha256(json.dumps(verified,sort_keys=True).encode()).hexdigest(),
        'source_files':verified,'configure_command':configure,'build_command':command,
        'compiler_sha256':digest(build/'bin/clang'),
        'clang_library_sha256':digest(build/'lib/libclang-cpp.dylib'),
        'llvm_library_sha256':digest(a.llvm/'lib/libLLVM.dylib'),
        'scope':'unmodified Clang sources; installed Homebrew LLVM backend remains in trusted chain'}
    (build/'reference-identity.json').write_text(json.dumps(identity,indent=2)+'\n')
    print(build/'reference-identity.json')


if __name__=='__main__':main()
