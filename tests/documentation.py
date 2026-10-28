#!/usr/bin/env python3
"""Compile complete native module examples and check retired API documentation."""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
count = 0
with tempfile.TemporaryDirectory(prefix='safety-docs-') as directory:
    tmp = pathlib.Path(directory)
    for name in ['README.md', 'docs/LANGUAGE.md']:
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
documents = [p for p in root.rglob('*.md')
             if not any(part in {'.git', 'build', 'downloads', 'llvm-build',
                                 'llvm-project-22.1.2.src', '.toolchains'}
                        for part in p.relative_to(root).parts)]
for path in documents:
    text = path.read_text()
    assert not re.search(r'\bonto\b', text), str(path)
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme or not parsed.path:
            continue
        destination = path.parent/urllib.parse.unquote(parsed.path)
        assert destination.exists(), f'{path.relative_to(root)}: broken link {target}'
assert not re.search(r'\bonto\s*\(', (root/'runtime/conversions.cppm').read_text())
assert '协程和 union 仍不受支持' not in (root/'docs/SAFETY.md').read_text()
print(f'{count} complete documented native modules compile; {len(documents)} documents have valid local links; retired APIs absent')
