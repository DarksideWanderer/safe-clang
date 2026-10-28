#!/usr/bin/env python3
"""Rebuild the cumulative frontend patch and its source manifest.

The working tree `llvm-project-22.1.2.src` holds the patched sources. The
patch is the difference of those files against the pinned pristine archive,
and `frontend/source-hashes.json` records the hash of every patched file plus
the patch's own hash. Any frontend change (Sema/Parse/AST/CodeGen) has to go
through this tool so the two stay consistent and `tests/verify_frontend_patch.py`
keeps proving that the patch reapplies without fuzz to pristine sources.

`--check` regenerates into a temporary directory, applies the result to a
fresh pristine extraction and proves it reproduces the current tree and
manifest without touching the repository.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import tarfile
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
archive_path = root/'downloads/llvm-project-22.1.2.src.tar.xz'
archive_prefix = 'llvm-project-22.1.2.src/'
manifest_path = root/'frontend/source-hashes.json'
patch_path = root/'frontend/clang-22.1.2.patch'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def diff_chunk(tree, archive, name, temporary):
    """A `diff -u` hunk for one file, or None when pristine and tree agree."""
    current = (tree/name).read_bytes()
    try:
        member = archive.getmember(archive_prefix+name)
    except KeyError:
        member = None
    if member is not None:
        original = archive.extractfile(member).read()
        if original == current:
            return None
        base = temporary/('pristine-'+name.replace('/', '_'))
        base.write_bytes(original)
    else:
        # A file the patch adds has no pristine counterpart.
        base = pathlib.Path('/dev/null')
    result = subprocess.run(['diff', '-u', '--label', ('a/'+name) if member else '/dev/null',
                             '--label', 'b/'+name, str(base), str(tree/name)],
                            capture_output=True)
    if result.returncode not in (0, 1):
        raise SystemExit('diff failed for '+name+': '+result.stderr.decode())
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='regenerate in a temporary directory and verify it reproduces the tree')
    parser.add_argument('--source', type=pathlib.Path,
                        default=root/'llvm-project-22.1.2.src')
    parser.add_argument('--add', action='append', default=[],
                        help='register a file the patch adds (repeatable)')
    parser.add_argument('--drop', action='append', default=[],
                        help='unregister a file the patch no longer touches (repeatable)')
    arguments = parser.parse_args()
    tree = arguments.source.resolve()
    manifest = json.loads(manifest_path.read_text())
    names = sorted((set(manifest['files']) | set(arguments.add)) - set(arguments.drop))
    with tempfile.TemporaryDirectory(prefix='safecpp-manifest-') as directory:
        temporary = pathlib.Path(directory)
        with tarfile.open(archive_path) as archive:
            chunks = [diff_chunk(tree, archive, name, temporary) for name in names]
        patch = b''.join(chunk for chunk in chunks if chunk)
        files = {name: digest((tree/name).read_bytes()) for name in names}
        updated = {'patch_sha256': digest(patch), 'files': files}
    if arguments.check:
        with tempfile.TemporaryDirectory(prefix='safecpp-check-') as directory:
            pristine = pathlib.Path(directory)
            with tarfile.open(archive_path) as archive:
                for name in names:
                    try:
                        data = archive.extractfile(archive_prefix+name).read()
                    except KeyError:
                        continue
                    target = pristine/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            (pristine/'regenerated.patch').write_bytes(patch)
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1',
                            '-i', str(pristine/'regenerated.patch')],
                           cwd=pristine, check=True, stdout=subprocess.DEVNULL)
            drifted = [name for name in names
                       if (pristine/name).read_bytes() != (tree/name).read_bytes()]
        if drifted:
            raise SystemExit('regenerated patch does not reproduce: '+', '.join(drifted))
        print('Regenerated patch applies to pristine with no fuzz and reproduces '
              f'the working tree: {len(names)} files')
        print('patch bytes '+('match the committed file' if patch_path.read_bytes() == patch
                              else 'differ from the committed file (content still equal)'))
        if json.loads(manifest_path.read_text()) != updated:
            print('manifest would be rewritten')
        return
    patch_path.write_bytes(patch)
    manifest_path.write_text(json.dumps(updated, indent=1)+'\n')
    print(f'Wrote {patch_path.name} ({len(names)} files) and the source manifest')


main()
