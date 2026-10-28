#!/usr/bin/env python3
"""Run semantic join/access invariants against the actual checker C++ code."""
import pathlib
import subprocess
import sys
import tempfile

clang, plugin, root = sys.argv[1:]
root = pathlib.Path(root)
llvm = pathlib.Path('/opt/homebrew/opt/llvm')
patched_headers = root/'llvm-project-22.1.2.src'/'clang'/'include'
generated_headers = root/'llvm-build'/'include'
patched_lib = root/'llvm-build'/'lib'
arguments = [clang, '-std=c++17', '-O1']
if (patched_headers.is_dir() and generated_headers.is_dir() and
        (patched_lib/'libclang-cpp.dylib').exists()):
    # The checker now uses the patched AST APIs (phantom fields, native
    # slices), so the standalone unit test must compile against the patched
    # headers and link the patched clang-cpp library.
    arguments += ['-DMODULE_SAFETY_BUILTIN',
                  '-isystem', str(generated_headers),
                  '-isystem', str(patched_headers),
                  '-isystem', str(llvm/'include')]
    link_dirs = [str(patched_lib), str(llvm/'lib')]
else:
    arguments += ['-isystem', str(llvm/'include')]
    link_dirs = [str(llvm/'lib')]
arguments.append(str(root/'tests/borrow_domain.cpp'))
for directory in link_dirs:
    arguments += ['-L'+directory, '-Wl,-rpath,'+directory]
arguments += ['-lclang-cpp', '-lLLVM', '-o']
with tempfile.TemporaryDirectory(prefix='safety-borrow-domain-') as directory:
    executable = pathlib.Path(directory)/'borrow_domain'
    subprocess.run(arguments + [str(executable)], check=True, timeout=120)
    subprocess.run([str(executable)], check=True, timeout=30)
