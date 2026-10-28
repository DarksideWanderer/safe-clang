#!/usr/bin/env python3
"""Export a reviewed source allowlist without the development Git history.

Creates a NEW directory and a content-hash manifest. Never overwrites an export,
edits the index, copies .git, commits, configures a remote, or pushes. Unknown
files fail closed until explicitly classified. This is a publication hygiene
check, not a legal opinion or an exhaustive secret/provenance scanner.
"""
import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
FOLDERS = {'src', 'frontend', 'include', 'runtime', 'tests', 'tools', 'proofs',
           'compatibility', 'examples', 'docs', 'LICENSES'}
ROOT_FILES = {'.gitignore', '.gitattributes', '.clang-format', 'CMakeLists.txt', 'LICENSE'}
PRIVATE_FILES = {'COMPILER-COMPATIBILITY-PROMPT.md', 'docs/PUBLICATION-REVIEW.md',
                 'SOURCE-MANIFEST.json'}
ALLOWED_SUFFIXES = {'.py', '.cpp', '.cppm', '.h', '.json', '.md', '.patch', '.smt2',
                    '.lean', '.txt'}
# Only report locations/categories; never print a credential's value.
SECRET_PATTERNS = {
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'),
    'github_token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'aws_key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'openai_token': re.compile(rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}\b'),
}


def classification(name):
    path = pathlib.PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('unsafe path: '+name)
    if (name in PRIVATE_FILES or name.startswith(('standards/n4861/source/',
            'downloads/', 'build/', 'llvm-build/', 'llvm-project-22.1.2.src/',
            '.toolchains/', '.debugtmp/', 'scratch_', 'module-build/', 'native-module-build/')) or
            '__pycache__' in path.parts):
        return 'excluded'
    if name in ROOT_FILES or (len(path.parts) == 1 and path.suffix == '.md'):
        return 'source'
    if name == 'standards/n4861/manifest.json':
        return 'source'
    if path.parts[0] in FOLDERS and (path.suffix in ALLOWED_SUFFIXES or path.name == 'LICENSE'):
        return 'source'
    raise ValueError('unclassified publication input: '+name)


def candidates(root):
    result = subprocess.check_output(['git', '-C', str(root), 'ls-files',
        '--cached', '--others', '--exclude-standard', '-z'])
    return sorted(set(name for name in result.decode().split('\0') if name))


def source_files(root):
    selected, excluded, issues = {}, [], []
    for name in candidates(root):
        if classification(name) == 'excluded':
            excluded.append(name)
            continue
        path = root/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('not a regular in-tree source: '+name)
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('oversized source input requires review: '+name)
        raw = path.read_bytes()
        if b'\0' in raw:
            raise ValueError('binary input requires review: '+name)
        for category, pattern in SECRET_PATTERNS.items():
            if pattern.search(raw):
                issues.append(name+' ('+category+')')
        selected[name] = hashlib.sha256(raw).hexdigest()
    if issues:
        raise ValueError('possible credentials; review before exporting: '+', '.join(issues))
    required = {'LICENSE', 'LICENSING.md', 'THIRD_PARTY_NOTICES.md',
                'LICENSES/LLVM.txt', 'LICENSES/BSL-1.0.txt',
                'LICENSES/Apache-2.0-with-LLVM-exception.txt',
                'include/LICENSE', 'runtime/LICENSE', 'examples/LICENSE',
                'include/std2/LICENSE', 'docs/PUBLISHING.md'}
    if not required <= selected.keys():
        raise ValueError('missing publication files: '+', '.join(sorted(required-selected.keys())))
    manifest = json.loads((root/'frontend/source-hashes.json').read_text())
    if selected.get('frontend/clang-22.1.2.patch') != manifest['patch_sha256']:
        raise ValueError('frontend patch fingerprint mismatch')
    return selected, excluded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path,
                        help='new output directory; without this option only checks the input list')
    args = parser.parse_args()
    try:
        files, excluded = source_files(ROOT)
        if args.output:
            target = args.output.absolute()
            if target.exists() or target.is_symlink():
                raise ValueError('output already exists; choose a new directory: '+str(target))
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.source-export-', dir=target.parent) as directory:
                temporary = pathlib.Path(directory)/'source'
                temporary.mkdir()
                for name, expected in files.items():
                    destination = temporary/name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT/name, destination)
                    if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                        raise ValueError('source changed while exporting: '+name)
                report = {'schema_version': 1, 'scope': 'source snapshot; no development history',
                          'files': files, 'excluded_input_count': len(excluded),
                          'legal_clearance': 'not_certified',
                          'secret_scan': 'limited known credential patterns; not exhaustive'}
                (temporary/'SOURCE-MANIFEST.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
                # Recheck the source set, including newly created untracked inputs.
                if source_files(ROOT) != (files, excluded):
                    raise ValueError('source set changed while exporting; retry')
                temporary.rename(target)
            print('Exported '+str(len(files))+' files to '+str(target))
        else:
            print('Checked '+str(len(files))+' selected source files; '+str(len(excluded))+' private inputs excluded')
        print('No Git history, index, remote or push was changed.')
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
