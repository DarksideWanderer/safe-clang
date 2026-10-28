#!/usr/bin/env python3
"""Compile complete native module examples and check retired API documentation."""
import json
import pathlib
import re
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
count = 0
with tempfile.TemporaryDirectory(prefix='safety-docs-') as directory:
    tmp = pathlib.Path(directory)
    for name in ['README.md', 'CIRCLE-COMPATIBILITY.md']:
        for block in re.findall(r'```cpp\n(.*?)```', (root/name).read_text(), re.S):
            module = re.search(r'export module\s+([\w.]+)\s*;', block)
            if not module:
                continue
            source = tmp/'example.cppm'
            source.write_text(block)
            policy = tmp/'policy.json'
            policy.write_text(json.dumps({'version': 1, 'modules': {module[1]: 'safe'}}))
            result = subprocess.run([str(clang), '-std=c++20', '-fmodule-safe',
                '-fmodule-safety-policy='+str(policy), '-fsyntax-only', str(source)],
                text=True, capture_output=True)
            assert result.returncode == 0, name+'\n'+result.stderr
            count += 1
assert count == 3, count
for name in ['README.md', 'PRODUCTION.md', 'VERIFICATION.md', 'UB-AUDIT.md', 'CIRCLE-COMPATIBILITY.md']:
    assert not re.search(r'\bonto\b', (root/name).read_text()), name
assert not re.search(r'\bonto\s*\(', (root/'runtime/conversions.cppm').read_text())
assert '协程和 union 仍不受支持' not in (root/'PRODUCTION.md').read_text()
print(f'{count} complete documented native modules compile; retired conversion API and stale support claims absent')
