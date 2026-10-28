#!/usr/bin/env python3
"""Run selected untouched LLVM 22.1.2 Clang lit inputs in default mode.

The independent suite uses upstream RUN lines and diagnostic assertions. Its
small explicit selection is not the complete upstream regression suite.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT=pathlib.Path(__file__).resolve().parent.parent
TESTS=['SemaCXX/constexpr-default-arg.cpp','SemaCXX/exception-spec.cpp',
       'SemaCXX/overload-call.cpp','SemaCXX/constexpr-array-init.cpp']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clang',type=pathlib.Path,default=ROOT/'llvm-build/bin/clang')
    p.add_argument('--output',type=pathlib.Path,default=ROOT/'build/clang-upstream-lit.json')
    a=p.parse_args()
    clang=a.clang.resolve()
    upstream=ROOT/'llvm-project-22.1.2.src'
    report={'baseline':'LLVM/Clang 22.1.2','scope':'selected upstream RUN lines',
            'compiler_sha256':hashlib.sha256(clang.read_bytes()).hexdigest(),
            'extension_flags':[],'inputs':{}}
    with tempfile.TemporaryDirectory(prefix='upstream-clang-lit-') as directory:
        tmp=pathlib.Path(directory)
        for name in TESTS:
            src=upstream/'clang/test'/name
            report['inputs'][name]=hashlib.sha256(src.read_bytes()).hexdigest()
            (tmp/src.name).symlink_to(src)
        triple=subprocess.check_output([str(clang),'-dumpmachine'],text=True).strip()
        cfg='''import lit.formats
config.name='Clang 22.1.2 selected default-mode regression'
config.test_format=lit.formats.ShTest(True)
config.suffixes=['.cpp']
config.test_source_root=__ROOT__
config.test_exec_root=__ROOT__
config.substitutions += [('%clang_cc1',__CLANG__+' -cc1'),('%clang',__CLANG__),('%itanium_abi_triple',__TRIPLE__)]
'''.replace('__ROOT__',repr(str(tmp))).replace('__CLANG__',repr(str(clang))).replace('__TRIPLE__',repr(triple))
        (tmp/'lit.cfg.py').write_text(cfg)
        command=[sys.executable,str(upstream/'llvm/utils/lit/lit.py'),'-v','--output',str(tmp/'results.json'),str(tmp)]
        r=subprocess.run(command,capture_output=True,text=True,timeout=180)
        report.update(command=command,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr)
        if (tmp/'results.json').exists():report['lit_results']=json.loads((tmp/'results.json').read_text())
    report['passed']=report['returncode']==0
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(report['stdout']);print(report['stderr'],file=sys.stderr)
    return report['returncode']


if __name__=='__main__':raise SystemExit(main())
