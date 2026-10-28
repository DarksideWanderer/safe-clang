#!/usr/bin/env python3
"""Acquire pinned local validation inputs; none are part of the source release.

Existing git checkouts must already be clean and at the pinned commit. Existing
archives and restored draft sources are verified, never silently overwritten.
Use --offline to verify/restore already downloaded inputs without networking.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
GIT_REFERENCES = {
    'safe-cpp': ('https://github.com/cppalliance/safe-cpp.git',
                 '889685274438ca20344d4d9cb472e4392c4e35a9', 'safe-cpp-reference'),
    'circle': ('https://github.com/seanbaxter/circle.git',
               'b81c37d2bb227cdf6aa58a90dd00f12f62c8d3bc', 'circle-reference'),
    'mdspan': ('https://github.com/seanbaxter/mdspan.git',
               '774a1f0c401144d88fdf4d655a70b777b879f4b4', 'circle-mdspan-reference'),
}
LLVM_SHA256 = '62f2f13ff25b1bb28ea507888e858212d19aafb65e8e72b4a65ee0629ec4ae0c'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def archive(name, url, expected, offline):
    target = ROOT/'downloads'/name
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        if offline:
            raise RuntimeError('missing local archive: '+name)
        with tempfile.TemporaryDirectory(dir=target.parent) as directory:
            temporary = pathlib.Path(directory)/name
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            if digest(temporary) != expected:
                raise RuntimeError('download fingerprint mismatch: '+name)
            temporary.replace(target)
    if digest(target) != expected:
        raise RuntimeError('local archive fingerprint mismatch: '+name)
    return target


def git_reference(name, offline):
    url, revision, folder = GIT_REFERENCES[name]
    target = ROOT/'downloads'/folder
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        if offline:
            raise RuntimeError('missing local checkout: '+folder)
        # Fetch in a temporary sibling; failed acquisitions leave no partial
        # checkout at the expected path. Do not touch an existing checkout.
        with tempfile.TemporaryDirectory(dir=target.parent) as directory:
            temporary = pathlib.Path(directory)/'checkout'
            subprocess.run(['git', 'init', str(temporary)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(['git', '-C', str(temporary), 'remote', 'add', 'origin', url], check=True)
            subprocess.run(['git', '-C', str(temporary), 'fetch', '--depth=1', 'origin', revision], check=True)
            subprocess.run(['git', '-C', str(temporary), 'checkout', '--detach', revision], check=True)
            temporary.rename(target)
    current = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(target), 'status', '--porcelain',
                                     '--untracked-files=all'], text=True)
    if current != revision or dirty:
        raise RuntimeError('expected a clean pinned checkout: '+folder)
    print(name+': verified '+revision)


def draft_reference(offline):
    manifest = json.loads((ROOT/'standards/n4861/manifest.json').read_text())
    source = archive('cplusplus-n4861.tar.gz',
                     'https://codeload.github.com/cplusplus/draft/tar.gz/refs/tags/n4861',
                     manifest['archive_sha256'], offline)
    validated = {}
    with tarfile.open(source) as bundle:
        for name, expected in manifest['sources'].items():
            relative = pathlib.PurePosixPath(name)
            if (relative.is_absolute() or '..' in relative.parts or
                    relative.parts[:3] != ('standards', 'n4861', 'source') or
                    len(relative.parts) != 4 or relative.suffix != '.tex'):
                raise RuntimeError('invalid draft source path: '+name)
            member = bundle.getmember('draft-n4861/source/'+relative.name)
            if not member.isfile():
                raise RuntimeError('draft member is not a regular file: '+name)
            data = bundle.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError('draft source fingerprint mismatch: '+name)
            destination = ROOT/name
            if any(parent.is_symlink() for parent in destination.parents if parent != ROOT.parent):
                raise RuntimeError('refusing symlinked draft source directories: '+name)
            if destination.is_symlink() or (destination.exists() and destination.read_bytes() != data):
                raise RuntimeError('refusing to overwrite changed draft source: '+name)
            validated[destination] = data
    for destination, data in validated.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(data)
    print('n4861: verified/restored '+str(len(validated))+' local sources (not redistributed)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('references', nargs='+', choices=[*GIT_REFERENCES, 'n4861', 'llvm'])
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    try:
        for name in dict.fromkeys(args.references):
            if name in GIT_REFERENCES:
                git_reference(name, args.offline)
            elif name == 'n4861':
                draft_reference(args.offline)
            else:
                path = archive('llvm-project-22.1.2.src.tar.xz',
                    'https://github.com/llvm/llvm-project/releases/download/llvmorg-22.1.2/'
                    'llvm-project-22.1.2.src.tar.xz', LLVM_SHA256, args.offline)
                print('llvm: verified archive '+str(path)+'; extract it before building')
    except (OSError, RuntimeError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
