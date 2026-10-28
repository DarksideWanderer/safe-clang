#!/usr/bin/env python3
"""Apply the cumulative patch to pinned pristine files and compare the result."""
import pathlib
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
source = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-project-22.1.2.src'
patch = root/'frontend/clang-22.1.2.patch'
manifest = json.loads((root/'frontend/source-hashes.json').read_text())
if manifest['patch_sha256'] != hashlib.sha256(patch.read_bytes()).hexdigest():
    raise AssertionError('patch/hash manifest mismatch')
lines = patch.read_text().splitlines()
paths = sorted({line.removeprefix('+++ b/').strip() for line in lines if line.startswith('+++ b/')})
created = {lines[i+1].removeprefix('+++ b/').strip() for i, line in enumerate(lines[:-1])
           if line == '--- /dev/null' and lines[i+1].startswith('+++ b/')}
if set(paths) != set(manifest['files']):
    raise AssertionError('patch paths do not match the source manifest')
with tempfile.TemporaryDirectory(prefix='safecpp-pristine-') as directory:
    pristine = pathlib.Path(directory)
    with tarfile.open(root/'downloads/llvm-project-22.1.2.src.tar.xz') as archive:
        for name in paths:
            relative = pathlib.PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts:
                raise AssertionError('invalid patch path: '+name)
            if name in created:
                continue
            member = archive.getmember('llvm-project-22.1.2.src/'+name)
            if not member.isfile(): raise AssertionError('not a regular source file: '+name)
            output = pristine/name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(archive.extractfile(member).read())
    subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(patch)], cwd=pristine, check=True, stdout=subprocess.DEVNULL)
    mismatches = [name for name in paths if (pristine/name).read_bytes() != (source/name).read_bytes()]
    if mismatches: raise AssertionError('patch/source drift: '+', '.join(mismatches))
    for name in paths:
        if hashlib.sha256((pristine/name).read_bytes()).hexdigest() != manifest['files'][name]:
            raise AssertionError('source/hash manifest mismatch: '+name)
print(f'Pristine LLVM 22.1.2: patch applies without fuzz; all {len(paths)} files match')
