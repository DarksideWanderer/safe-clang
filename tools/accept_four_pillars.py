#!/usr/bin/env python3
"""Build and accept the four Circle-compatible compiler workstreams together.

Run from any directory. Logs and an evidence manifest are retained even on
failure; a passed report requires an unchanged source/binary snapshot.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from circle_compatibility import reference_identity

ROOT = pathlib.Path(__file__).resolve().parents[1]
REFERENCES = {
    'safe-cpp': ('downloads/safe-cpp-reference', 'proposal/draft.md'),
    'circle': ('downloads/circle-reference', 'new-circle/README.md'),
}
MATRIX = {
    'region_relations': ['region_relation_entries.py', 'higher_ranked_relations.py',
        'aggregate_reborrow_parents.py'],
    'higher_order_relations': ['higher_ranked_relation_algebra.py',
        'higher_ranked_pack_substitution.py', 'outer_region_captures.py',
        'class_parameter_variance.py', 'captured_callable_values.py'],
    'generic_projections': ['generic_region_projection.py', 'multi_region_class_values.py',
        'nested_class_values.py'],
    'runtime_semantics': ['runtime_semantics.py', 'legacy_value_abi.py',
        'array_slice_conversions.py',
        'relocation_operators.py', 'native_parameters.py', 'native_self.py',
        'choice_match.py', 'choice_patterns.py', 'choice_borrow_patterns.py', 'tuple_call.py', 'tuple_dependent.py', 'tuple_lifetimes.py', 'slice_rebuild_regions.py'],
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot():
    paths = [ROOT/'frontend/clang-22.1.2.patch', ROOT/'frontend/source-hashes.json',
        ROOT/'llvm-build/bin/clang', ROOT/'llvm-build/lib/libclang-cpp.dylib',
        ROOT/'build/ModuleSafety.so', ROOT/'CMakeLists.txt']
    paths.extend((ROOT/'compatibility').glob('*.json'))
    # The independent C++ ABI oracle and the LLVM shared runtime are inputs to
    # this host's executions, not merely dependencies to identify afterwards.
    paths.extend([pathlib.Path('/opt/homebrew/opt/llvm/bin/clang++'),
                  pathlib.Path('/opt/homebrew/opt/llvm/lib/libLLVM.dylib')])
    paths.extend(ROOT/directory/document for directory, document in REFERENCES.values())
    for directory, pattern in [('src', '*'), ('tests', '*'), ('tools', '*.py')]:
        paths.extend(p for p in (ROOT/directory).glob(pattern) if p.is_file())
    manifest = json.loads((ROOT/'frontend/source-hashes.json').read_text())
    paths.extend(ROOT/'llvm-project-22.1.2.src'/name for name in manifest['files'])
    return {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p.resolve()): digest(p)
            for p in sorted(set(paths))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--skip-build', action='store_true', help='accept already-built binaries')
    parser.add_argument('--output', type=pathlib.Path, default=ROOT/'build/four-pillars')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'Circle-compatible four-workstream acceptance on the host target',
        'independent_circle_binary_comparison': False, 'gates': {}, 'matrix': MATRIX}
    report_path = output/'acceptance.json'

    def save():
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')

    def run(name, command):
        print(name+': running', flush=True)
        log = output/(name+'.log')
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        report['gates'][name] = {'passed': result.returncode == 0, 'returncode': result.returncode,
            'command': command, 'log': str(log), 'log_sha256': digest(log)}
        save()
        if result.returncode:
            raise RuntimeError(name+' failed; see '+str(log))
        print(name+': passed', flush=True)
        return log.read_text(errors='replace')

    save()
    try:
        report['references'] = {}
        for name, (directory, document) in REFERENCES.items():
            identity = reference_identity(ROOT/directory, name)
            report['references'][name] = {'revision': identity['revision'],
                'source_sha256': identity['source_sha256'],
                'reviewed_document': str(pathlib.Path(directory)/document),
                'document_sha256': digest(ROOT/directory/document)}
        save()
        if not args.skip_build:
            run('native-build', [sys.executable, 'tools/build_frontend.py', '--jobs', str(args.jobs)])
            run('plugin-build', ['cmake', '--build', 'build', '-j', str(args.jobs)])
        before = snapshot()
        report['sha256'] = before
        registered = set(re.findall(r"tests/([^']+\.py)", (ROOT/'tools/test_frontend.py').read_text()))
        for group, scripts in MATRIX.items():
            for name in scripts:
                if not (ROOT/'tests'/name).is_file() or name not in registered:
                    raise RuntimeError('missing matrix regression: '+name)
        frontend = run('frontend', [sys.executable, 'tools/test_frontend.py', '--jobs', str(args.jobs)])
        match = re.search(r'(\d+) frontend regressions passed', frontend)
        if not match:
            raise RuntimeError('frontend gate did not report its completed task count')
        report['gates']['frontend']['total'] = int(match[1])
        official = re.search(r'(\d+) official positive configurations passed across (\d+) files', frontend)
        if not official:
            raise RuntimeError('official positive evidence missing from frontend gate')
        report['official_positive'] = {'configurations': int(official[1]), 'files': int(official[2]), 'passed': True}
        ctest = run('ctest', ['ctest', '--test-dir', 'build', '--output-on-failure', '-j', str(args.jobs)])
        match = re.search(r'100% tests passed, 0 tests failed out of (\d+)', ctest)
        if not match:
            raise RuntimeError('CTest gate did not report all tests passing')
        report['gates']['ctest']['total'] = int(match[1])
        run('clang-differential', [sys.executable, 'tools/clang_compatibility.py',
            '--output', str(output/'clang-compatibility.json')])
        diff = json.loads((output/'clang-compatibility.json').read_text())
        if not diff['passed']:
            raise RuntimeError('default-mode differential failed')
        report['gates']['clang-differential']['total'] = len(diff['cases'])
        run('patch-replay', [sys.executable, 'tests/verify_frontend_patch.py'])
        run('diff-check', ['git', 'diff', '--check', '--', '.', ':!frontend/clang-22.1.2.patch'])
        after = snapshot()
        drift = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
        report['snapshot_unchanged'] = not drift
        if drift:
            report['drift'] = drift
            raise RuntimeError('source or binary changed during acceptance')
        report['status'] = 'passed'
    except (OSError, RuntimeError, SystemExit) as error:
        report['status'] = 'failed'
        report['error'] = str(error)
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
    print(str(report_path), flush=True)
    if report['status'] != 'passed':
        raise SystemExit(report.get('error', 'acceptance failed'))


if __name__ == '__main__':
    main()
