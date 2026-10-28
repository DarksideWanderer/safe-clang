#!/usr/bin/env python3
"""Inventory pinned upstream documentation and compile original library examples.

Successful syntax checks are compatibility evidence, never a memory-safety proof.
No upstream source is rewritten and no Circle feature/version macro is spoofed.
"""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import platform
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PINNED = {'circle': 'b81c37d2bb227cdf6aa58a90dd00f12f62c8d3bc',
          'safe-cpp': '889685274438ca20344d4d9cb472e4392c4e35a9',
          'mdspan': '774a1f0c401144d88fdf4d655a70b777b879f4b4'}


def compiler_crashed(returncode, diagnostics):
    return returncode < 0 or bool(re.search(
        r'PLEASE submit a bug report|Stack dump:|clang frontend command failed|'
        r'LLVM ERROR:|Assertion .* failed|Segmentation fault', diagnostics))


def syntax_status(returncode, diagnostics):
    if compiler_crashed(returncode, diagnostics):
        return 'compiler_crashed'
    return 'syntax_accepted' if returncode == 0 else 'compile_failed_current_mode'


def classify_negative(path, returncode, diagnostics, oracle=None):
    """Credit a reviewed rule, never an arbitrary nonzero compiler exit."""
    result = {'status': 'rejected_unattributed', 'expected_rule_verified': False}
    if compiler_crashed(returncode, diagnostics):
        result['status'] = 'compiler_crashed'
        return result
    if returncode == 0:
        result['status'] = 'accepted_unexpectedly'
        return result
    if not oracle or not oracle.get('upstream_enabled', True):
        return result
    if oracle.get('oracle_status') != 'reviewed_native_diagnostic':
        return result
    # Matching a later error would hide a parse failure or unrelated library
    # rejection earlier in this translation unit. Inspect the first one only.
    first = re.search(r'^(.+?):(\d+):(\d+): (?:fatal )?error: (.+)$',
                      diagnostics, re.MULTILINE)
    if (not first or pathlib.Path(first[1]).resolve() != pathlib.Path(path).resolve() or
            int(first[2]) != oracle['first_error_line'] or
            not re.search(oracle['diagnostic_regex'], first[4])):
        return result
    note = oracle.get('required_note_regex')
    if note and not re.search(note, diagnostics):
        return result
    result.update(status='rejected_for_expected_rule', expected_rule_verified=True,
                  matched_error={'path': first[1], 'line': int(first[2]), 'message': first[4]})
    return result


def load_negative_oracles(reference):
    path = ROOT/'compatibility/safe-cpp-negatives.json'
    data = json.loads(path.read_text())
    if data['reference_revision'] != PINNED['safe-cpp']:
        raise SystemExit('negative oracle revision does not match the fixed reference')
    result = {}
    for case in data['cases']:
        source = reference/case['path']
        if hashlib.sha256(source.read_bytes()).hexdigest() != case['sha256']:
            raise SystemExit('negative oracle source changed: '+case['path'])
        if case['path'] in result:
            raise SystemExit('duplicate negative oracle: '+case['path'])
        result[case['path']] = case
    actual = {p.relative_to(reference).as_posix()
              for p in (reference/'libsafecxx/test/compile-fail').rglob('*.cxx')
              if p.parent.name != 'panic' and p.name != 'abort_handler.cxx'}
    if set(result) != actual:
        raise SystemExit('negative oracle inventory differs from the fixed reference')
    return result


def reference_identity(path, baseline):
    revision = subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
    status = subprocess.check_output(['git','-C',str(path),'status','--porcelain'],text=True)
    if revision != PINNED[baseline] or status:
        raise SystemExit(f'{baseline}: expected clean pinned source {PINNED[baseline]}')
    files = {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(path.rglob('*')) if p.is_file() and '.git' not in p.parts}
    return {'revision':revision,'files':files,
            'source_sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}


def runtime_probe(path, syntax_command, include_flags, output_dir, support_sources=(),
                  extra_flags=()):
    """Compile/link/run untouched official positives with their own assertions."""
    results=[]
    for optimization in ('-O0','-O2'):
        with tempfile.TemporaryDirectory(prefix='official-runtime-',dir=output_dir) as directory:
            binary=pathlib.Path(directory)/'example'
            command=[arg for arg in syntax_command if arg!='-fsyntax-only']
            support=[]
            objects=[]
            for index, source in enumerate(support_sources):
                obj=pathlib.Path(directory)/f'support-{index}.o'
                # Upstream's abort handler is ordinary C++, with no safety
                # directive. Compile it in its own default-mode translation unit.
                helper_command=[syntax_command[0],'--driver-mode=g++','-std=c++20',
                                optimization,'-c',str(source),'-o',str(obj)]
                built=subprocess.run(helper_command,capture_output=True,text=True,timeout=120)
                support.append({'command':helper_command,'returncode':built.returncode,
                                'diagnostics':built.stderr,'extension_flags':[]})
                if built.returncode==0: objects.append(str(obj))
            command+=include_flags+list(extra_flags)+[optimization,'-pthread',str(path)]+objects+['-o',str(binary)]
            entry={'optimization':optimization,'command':command,'support_units':support}
            if any(unit['returncode'] for unit in support):
                entry['status']='support_build_failed'
                results.append(entry)
                continue
            try:
                built=subprocess.run(command,capture_output=True,text=True,timeout=120)
                entry.update(returncode=built.returncode,diagnostics=built.stderr,
                             status='compiler_crashed' if compiler_crashed(built.returncode,built.stderr)
                                    else 'build_failed')
                if built.returncode==0:
                    entry['binary_sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
                    # An official probe may print arbitrary bytes. Decode
                    # defensively: the exit status is the assertion oracle,
                    # not string validity.
                    executed=subprocess.run([str(binary)],capture_output=True,timeout=60)
                    entry['execution']={'returncode':executed.returncode,
                                        'stdout':executed.stdout.decode('utf-8','replace'),
                                        'stderr':executed.stderr.decode('utf-8','replace')}
                    entry['status']='executed_successfully' if executed.returncode==0 else 'runtime_failed'
                    entry['assertion_scope']='official in-program assertions and exit code; external output oracle not established'
            except subprocess.TimeoutExpired:
                entry['status']='timeout'
            results.append(entry)
    return results


def positive_runtime_succeeded(probes):
    if not probes:
        return False
    for probe in probes:
        runs = probe.get('runtime', [])
        if (probe.get('returncode') != 0 or len(runs) != 2 or
                {run.get('optimization') for run in runs} != {'-O0', '-O2'} or
                any(run.get('status') != 'executed_successfully' or
                    run.get('execution', {}).get('returncode') != 0 for run in runs)):
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=pathlib.Path,
                        default=ROOT / 'downloads/circle-reference')
    parser.add_argument('--clang', type=pathlib.Path,
                        default=ROOT / 'llvm-build/bin/clang')
    parser.add_argument('--safe-reference', type=pathlib.Path,
                        default=ROOT / 'downloads/safe-cpp-reference')
    parser.add_argument('--mdspan-reference', type=pathlib.Path,
                        default=ROOT / 'downloads/circle-mdspan-reference')
    parser.add_argument('--output', type=pathlib.Path,
                        default=ROOT / 'build/circle-compatibility.json')
    parser.add_argument('--require-full', action='store_true',
                        help='fail unless full compatibility is established; currently never established')
    args = parser.parse_args()
    def implementation_identity():
        paths=[pathlib.Path(__file__).resolve(),args.clang.resolve()]
        library=ROOT/'llvm-build/lib/libclang-cpp.dylib'
        if library.exists():paths.append(library.resolve())
        for folder in ('src','frontend','runtime','include'):
            paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file())
        paths.extend((ROOT/'compatibility').glob('*.json'))
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
    inputs_before=implementation_identity()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    policy = args.output.with_suffix('.policy.json').resolve()
    policy.write_text(json.dumps({'version': 1, 'modules': {}}) + '\n')
    syntax_command = [str(args.clang.resolve()), '--driver-mode=g++', '-std=c++20',
                      '-fcircle-safety', '-fcircle-borrow-values', '-fmodule-safety-policy=' + str(policy),
                      '-Werror=unknown-attributes', '-fsyntax-only', '-ferror-limit=8']
    reference = args.reference.resolve()
    circle_identity = reference_identity(reference, 'circle')
    revision = circle_identity['revision']
    documents = []
    for path in sorted(reference.rglob('*.md')):
        if '.git' in path.parts:
            continue
        contents = path.read_bytes()
        headings = []
        fence = None
        for number, line in enumerate(contents.decode('utf-8', errors='replace').splitlines(), 1):
            marker = re.match(r'^\s*(`{3,}|~{3,})', line)
            if marker:
                if fence is None:
                    fence = marker[1][0]
                elif marker[1][0] == fence:
                    fence = None
                continue
            if fence is not None:
                continue
            match = re.match(r'^(#{1,6})\s+(.+)', line)
            if match:
                headings.append({'line': number, 'level': len(match[1]),
                                 'title': match[2], 'status': 'unassessed'})
        relative = path.relative_to(reference).as_posix()
        documents.append({'path': relative, 'sha256': hashlib.sha256(contents).hexdigest(),
                          'source': f'https://github.com/seanbaxter/circle/blob/{revision}/{relative}',
                          'headings': headings})
    probes = []
    for path in sorted((reference / 'stdlib').glob('*.cxx')):
        command = syntax_command + [str(path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            probes.append({'path': path.relative_to(reference).as_posix(),
                           'command': command, 'returncode': result.returncode,
                           'status': syntax_status(result.returncode,result.stderr),
                           'diagnostics': result.stderr})
            if result.returncode==0 and re.search(r'\bmain\s*\(',path.read_text()):
                probes[-1]['runtime']=runtime_probe(path,syntax_command,[],args.output.parent)
        except subprocess.TimeoutExpired:
            probes.append({'path': path.relative_to(reference).as_posix(), 'status': 'timeout'})
    report = {'upstream': 'https://github.com/seanbaxter/circle', 'revision': revision,
              'implementation_inputs':inputs_before,
              'baseline': 'Circle', 'reference_identity':circle_identity,
              'platform':platform.platform(),
              'compiler_sha256':hashlib.sha256(args.clang.resolve().read_bytes()).hexdigest(),
              'patch_sha256':hashlib.sha256((ROOT/'frontend/clang-22.1.2.patch').read_bytes()).hexdigest(),
              'reference_binary_status':'not_available; no differential result claimed',
              'mode_audit':{'dialect_flags':syntax_command[3:6],
                            'status':'partial; per-feature upstream requirements remain unassessed'},
              'compiler': subprocess.check_output([str(args.clang.resolve()), '--version'], text=True),
              'documents': documents, 'library_probes': probes,
              'fully_compatible': False,
              'scope': 'Markdown inventory, original syntax probes and accepted executable assertions; no full semantic equivalence claimed.'}
    headers = [reference / 'tuple/tuple.hxx', reference / 'variant/variant.hxx',
               reference / 'new-circle/tuple/tuple.hxx']
    mdspan = args.mdspan_reference.resolve()
    if mdspan.exists():
        report['mdspan_reference'] = {
            'baseline':'mdspan Circle branch',
            'reference_identity':reference_identity(mdspan, 'mdspan'),
            'upstream': 'https://github.com/seanbaxter/mdspan', 'branch': 'circle',
            'revision': subprocess.check_output(
                ['git', '-C', str(mdspan), 'rev-parse', 'HEAD'], text=True).strip()}
        headers.append(mdspan / 'circle/experimental/mdspan.hpp')
    report['original_header_probes'] = []
    for path in headers:
        command = syntax_command + ['-x', 'c++', str(path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            report['original_header_probes'].append({
                'path': str(path), 'command': command, 'returncode': result.returncode,
                'status': syntax_status(result.returncode,result.stderr),
                'diagnostics': result.stderr})
        except subprocess.TimeoutExpired:
            report['original_header_probes'].append({'path': str(path), 'status': 'timeout'})
    safe_reference = args.safe_reference.resolve()
    if safe_reference.exists():
        library = safe_reference / 'libsafecxx'
        safe_revision = subprocess.check_output(
            ['git', '-C', str(safe_reference), 'rev-parse', 'HEAD'], text=True).strip()
        safe_probes = []
        for path in sorted((library / 'test').glob('*.cxx')):
            command = syntax_command + ['-I' + str(library / 'single-header'), str(path)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=60)
                safe_probes.append({'path': path.relative_to(safe_reference).as_posix(),
                                    'command': command, 'returncode': result.returncode,
                                    'status': syntax_status(result.returncode,result.stderr),
                                    'diagnostics': result.stderr})
                if result.returncode==0:
                    # SAFE_CXX_BUILD_TESTING enables this definition on the
                    # upstream core target; string_view_test catches panics.
                    safe_probes[-1]['runtime']=runtime_probe(path,syntax_command,
                        ['-I'+str(library/'single-header')],args.output.parent,
                        extra_flags=['-DLIBSAFECXX_PANIC_THROWS'])
            except subprocess.TimeoutExpired:
                safe_probes.append({'path': path.relative_to(safe_reference).as_posix(),
                                    'status': 'timeout'})
        report['safe_library'] = {
            'baseline':'Safe C++',
            'reference_identity':reference_identity(safe_reference, 'safe-cpp'),
            'upstream': 'https://github.com/cppalliance/safe-cpp',
            'revision': safe_revision, 'positive_probes': safe_probes,
            'negative_sources': [p.relative_to(safe_reference).as_posix()
                                 for p in sorted((library / 'test/compile-fail').rglob('*.cxx'))],
            'negative_status': 'blocked_until_positive_library_compiles',
            'runtime_configuration': {
                'upstream_option': 'SAFE_CXX_BUILD_TESTING=ON',
                'compile_definitions': ['LIBSAFECXX_PANIC_THROWS'],
                'specification_location': str(library/'CMakeLists.txt')+':85'},
            'runtime_status': 'official_assertions_passed' if positive_runtime_succeeded(safe_probes)
                else 'official_assertions_incomplete_or_failed'}
        # Execute every official language-failure input even while the positive
        # library fails. A rejection is recorded, never credited as the expected
        # safety rule while unrelated library parse failures mask that rule.
        negatives=[]
        oracles=load_negative_oracles(safe_reference)
        definitions={}
        cmake_tests=library/'test/CMakeLists.txt'
        for line_number,line in enumerate(cmake_tests.read_text().splitlines(),1):
            rule=re.match(r'^safe_cxx_compile_fail_test\((\S+)\s+"([^"]+)"\)',line)
            if rule:
                definitions[rule[1]]={'expected_diagnostic_pattern':rule[2],
                    'specification_location':str(cmake_tests)+':'+str(line_number)}
        for path in sorted((library/'test/compile-fail').rglob('*.cxx')):
            if 'panic' in path.relative_to(library/'test/compile-fail').parts or path.name=='abort_handler.cxx':
                continue  # upstream CMake defines these as executable panic tests
            command=syntax_command+['-I'+str(library/'single-header'),str(path)]
            try:
                result=subprocess.run(command,capture_output=True,text=True,timeout=60)
                relative=path.relative_to(safe_reference).as_posix()
                oracle=oracles[relative]
                negatives.append({'path':relative,
                                  'command':command,'returncode':result.returncode,
                                  'diagnostics':result.stderr,
                                  'native_oracle':oracle,
                                  **classify_negative(path,result.returncode,result.stderr,oracle)})
                negatives[-1].update(definitions.get(path.stem,{
                    'expected_diagnostic_pattern':None,
                    'specification_location':str(cmake_tests),
                    'criterion':'upstream CMake WILL_FAIL language test; exact diagnostic rule not specified'}))
            except subprocess.TimeoutExpired:
                negatives.append({'path':str(path),'status':'timeout','expected_rule_verified':False})
        report['safe_library']['negative_probes']=negatives
        report['safe_library']['negative_summary']={
            'inputs':len(negatives),
            'expected_rule_verified':sum(p.get('expected_rule_verified',False) for p in negatives),
            'compiler_crashes':sum(p['status']=='compiler_crashed' for p in negatives),
            'accepted_unexpectedly':sum(p['status']=='accepted_unexpectedly' for p in negatives),
            'unattributed':sum(p['status']=='rejected_unattributed' for p in negatives)}
        report['safe_library']['negative_status']='executed; per-input native rule attribution and open gaps recorded'
        panic_probes=[]
        for path in sorted((library/'test/compile-fail/panic').rglob('*.cxx')):
            for entry in runtime_probe(path,syntax_command,
                    ['-I'+str(library/'single-header')],args.output.parent,
                    support_sources=[library/'test/compile-fail/abort_handler.cxx']):
                entry['path']=path.relative_to(safe_reference).as_posix()
                entry['upstream_expected_behavior']='nonzero execution exit with upstream abort handler'
                # A compile/link failure never verifies a runtime panic rule.
                entry['expected_rule_verified']=entry.get('execution',{}).get('returncode')==1
                if 'execution' in entry:
                    entry['status']='expected_panic_observed' if entry['expected_rule_verified'] else 'expected_panic_missing'
                entry['criterion']='untouched panic source executes SIGABRT handler, which exits 1; normal main exit is 0'
                panic_probes.append(entry)
        report['safe_library']['panic_negative_probes']=panic_probes
        print(f'{sum(p["status"] == "syntax_accepted" for p in safe_probes)}/{len(safe_probes)} '
              'original Safe C++ positive tests syntax-accepted')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report['implementation_inputs_stable']=implementation_identity()==inputs_before
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'{len(documents)} documents, {sum(len(d["headings"]) for d in documents)} headings; '
          f'{sum(p["status"] == "syntax_accepted" for p in probes)}/{len(probes)} library examples accepted')
    print(args.output)
    if not report['implementation_inputs_stable']:
        raise SystemExit('Implementation changed during probes; evidence invalidated')
    if args.require_full:
        raise SystemExit('Full Circle/Safe C++ compatibility is not established; mandatory gate failed')


if __name__ == '__main__':
    main()
