#!/usr/bin/env python3
"""Run existing plugin regressions against the native frontend without loading a plugin."""
import os
import pathlib
import sys
import json
import re

driver = os.environ.get('MODULE_SAFETY_CLANG', str(pathlib.Path(__file__).resolve().parent.parent/'llvm-build/bin/clang'))
args = sys.argv[1:]
out = ['--driver-mode=g++', '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
i = 0
while i < len(args):
    if args[i] == '-Xclang' and i+3 < len(args) and args[i+2] == '-Xclang':
        option, value = args[i+1], args[i+3]
        if option in ('-load', '-add-plugin'):
            i += 4
            continue
        if option == '-plugin-arg-module-safety':
            if value.startswith('policy='):
                out.append('-fmodule-safety-policy='+value[7:])
                i += 4
                continue
            if value not in ('safe', 'unsafe'):
                sys.stderr.write('module-safety: select exactly one mode: safe or unsafe\n')
                sys.exit(1)
            out.append('-fmodule-'+value)
            i += 4
            continue
    out.append(args[i])
    i += 1
mode = next((a[len('-fmodule-'):] for a in out if a in ('-fmodule-safe', '-fmodule-unsafe')), None)
if mode and not any(a.startswith('-fmodule-safety-policy=') for a in out):
    # Each regression directory is an independent project. The normal build
    # driver supplies its immutable manifest policy instead of this test helper.
    sources = [pathlib.Path(a) for a in out if a.endswith(('.cpp', '.cppm')) and pathlib.Path(a).is_file()]
    if sources:
        source = sources[-1]
        output = pathlib.Path(out[out.index('-o')+1]).resolve().parent if '-o' in out else source.resolve().parent
        policy = output/'.native-module-modes.json'
        modules = json.loads(policy.read_text())['modules'] if policy.exists() else {}
        match = re.search(r'\bmodule\s+([\w.]+)(?::[\w.]+)?\s*;', source.read_text())
        if match: modules[match.group(1)] = mode
        policy.write_text(json.dumps({'version': 1, 'modules': modules}))
        out.append('-fmodule-safety-policy='+str(policy))
os.execv(driver, [driver]+out)
