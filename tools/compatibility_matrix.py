#!/usr/bin/env python3
"""Validate the pinned feature catalog and bind it to current execution evidence.

A documentation index, a test filename and an old passing report are never
feature acceptance. Unreviewed coverage and unavailable differentials remain gaps.
"""
import argparse
import copy
import hashlib
import json
import pathlib
import re
from circle_compatibility import PINNED, reference_identity

ROOT=pathlib.Path(__file__).resolve().parents[1]
CATALOG=ROOT/'compatibility/circle-features.json'


def digest(path):
    with pathlib.Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def registered_regressions():
    return {pathlib.Path(name).name for name in re.findall(
        r"'([^']+\.py)'",(ROOT/'tools/test_frontend.py').read_text())}


def validate_catalog(catalog):
    references={'circle':ROOT/'downloads/circle-reference','safe-cpp':ROOT/'downloads/safe-cpp-reference'}
    identifiers=set()
    for item in catalog['features']:
        if item['id'] in identifiers:
            raise ValueError('duplicate feature: '+item['id'])
        identifiers.add(item['id'])
        for name in ('name','expected_behavior','implementation_status','gaps','independent_comparison'):
            if not item.get(name):raise ValueError('missing feature '+name+': '+item['id'])
        ref=item['reference']
        if ref['revision'] != PINNED[ref['baseline']]:
            raise ValueError('feature reference revision differs: '+item['id'])
        lines=(references[ref['baseline']]/ref['path']).read_text().splitlines()
        if not 1<=ref['line']<=len(lines):raise ValueError('bad reference line: '+item['id'])
        for entry in item['implementation']:
            source=ROOT/entry['path']
            lines=source.read_text().splitlines()
            if entry['symbol'] not in lines[entry['line']-1]:
                raise ValueError('stale implementation anchor: '+item['id'])
        for test in item['local_regressions']:
            if not (ROOT/test).is_file():raise ValueError('missing regression: '+test)
        for key in ('positive_cases','negative_cases'):
            if key not in item:raise ValueError('missing '+key+': '+item['id'])
    documents={entry['path']:entry for entry in catalog['documents']}
    actual={p.relative_to(references['circle']).as_posix() for p in references['circle'].rglob('*.md')}
    if set(documents)!=actual:raise ValueError('document coverage differs from fixed upstream')
    for name,entry in documents.items():
        if digest(references['circle']/name)!=entry['sha256']:
            raise ValueError('document changed: '+name)
    flags=set(re.findall(r'^## `\[([^]]+)\]`',
        (references['circle']/'new-circle/README.md').read_text(),re.MULTILINE))
    declared={entry['id'].removeprefix('circle.directive.') for entry in catalog['features']
              if entry['category']=='feature_directive'}
    if declared!=flags:raise ValueError('New Circle feature/research directives are not fully inventoried')
    return {'features':len(identifiers),'new_circle_directives':len(flags),'documents':len(documents),
            'documents_needing_review':[entry['path'] for entry in documents.values()
                 if entry['review_status']=='needs_semantic_coverage_review'],
            'features_missing_negative_oracles':[item['id'] for item in catalog['features'] if not item['negative_cases']]}


def current_acceptance(path):
    evidence=json.loads(pathlib.Path(path).read_text())
    if evidence.get('status')!='passed' or not evidence.get('snapshot_unchanged'):
        raise ValueError('acceptance did not pass with an unchanged snapshot')
    if not evidence.get('sha256'):raise ValueError('acceptance has no source/binary identities')
    required={'tools/compatibility_matrix.py','compatibility/circle-features.json',
              'compatibility/safe-cpp-negatives.json','tools/test_frontend.py',
              'llvm-build/bin/clang','llvm-build/lib/libclang-cpp.dylib',
              'build/ModuleSafety.so','frontend/clang-22.1.2.patch','frontend/source-hashes.json'}
    if not required.issubset(evidence['sha256']):
        raise ValueError('acceptance does not bind the current feature catalog and oracles')
    for name,expected in evidence['sha256'].items():
        source=ROOT/name
        if not source.is_file() or digest(source)!=expected:
            raise ValueError('acceptance is stale: '+name)
    registered=registered_regressions()
    gate=evidence.get('gates',{}).get('frontend',{})
    if not gate.get('passed'):raise ValueError('acceptance has no passed frontend gate')
    mandatory={'frontend','ctest','clang-differential','patch-replay','diff-check'}
    if not mandatory.issubset(evidence['gates']) or any(
            not evidence['gates'][name].get('passed') for name in mandatory):
        raise ValueError('acceptance has missing or failed mandatory gates')
    manifest=json.loads((ROOT/'frontend/source-hashes.json').read_text())
    if any('llvm-project-22.1.2.src/'+name not in evidence['sha256'] for name in manifest['files']):
        raise ValueError('acceptance does not bind the expanded compiler sources')
    for entry in evidence['gates'].values():
        if not entry.get('log_sha256') or digest(entry['log'])!=entry['log_sha256']:
            raise ValueError('acceptance log identity is missing or changed')
    return evidence,registered


def implementation_snapshot():
    paths=[ROOT/'llvm-build/bin/clang',ROOT/'llvm-build/lib/libclang-cpp.dylib',
           ROOT/'build/ModuleSafety.so',ROOT/'frontend/clang-22.1.2.patch',
           ROOT/'frontend/source-hashes.json',CATALOG,pathlib.Path(__file__)]
    paths.extend((ROOT/'compatibility').glob('*.json'))
    return {str(p.resolve()):digest(p) for p in paths}


def markdown(report):
    lines=['# Circle feature compatibility evidence','',
        'Inventory complete: **'+str(report['inventory_complete'])+'**. '+
        'Fully compatible: **'+str(report['fully_compatible'])+'**.','',
        'Every row is tied to pinned source. Local regression acceptance and independent reference comparison are separate fields.','',
        '| Feature | Reference | Implementation | Positive / negative cases | Current execution | Independent comparison | Gaps |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for item in report['features']:
        ref=item['reference'];repo='seanbaxter/circle' if ref['baseline']=='circle' else 'cppalliance/safe-cpp'
        reference=f"[{ref['baseline']}:{ref['line']}](https://github.com/{repo}/blob/{ref['revision']}/{ref['path']}#L{ref['line']})"
        implementations=', '.join(f"[{pathlib.Path(i['path']).name}:{i['line']}]({ROOT/i['path']}:{i['line']})" for i in item['implementation']) or 'unimplemented / unverified'
        tests=', '.join(f"[{pathlib.Path(t).name}]({ROOT/t})" for t in item['local_regressions']) or 'semantic oracles missing'
        comparison=item['independent_comparison']['status']
        cells=[item['id'],reference,implementations,tests,item['current_regression_status'],comparison,'; '.join(item['gaps'])]
        lines.append('| '+' | '.join(value.replace('|','\\|').replace('\n',' ') for value in cells)+' |')
    lines+=['','Remaining inventory work:']+['- '+text for text in report['remaining_inventory_work']]
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=pathlib.Path,default=CATALOG)
    parser.add_argument('--acceptance',type=pathlib.Path,help='passed current fixed-binary acceptance; stale evidence is rejected')
    parser.add_argument('--official-evidence',type=pathlib.Path,help='fresh original-source probe report, with implementation-input checks')
    parser.add_argument('--output',type=pathlib.Path,default=ROOT/'build/compatibility-safety-matrix.json')
    parser.add_argument('--markdown',type=pathlib.Path,help='write a reviewable feature table')
    parser.add_argument('--require-complete-inventory',action='store_true')
    args=parser.parse_args()
    catalog=json.loads(args.catalog.read_text());coverage=validate_catalog(catalog)
    catalog_sha=digest(args.catalog)
    before=implementation_snapshot()
    acceptance=None;registered=set()
    if args.acceptance:acceptance,registered=current_acceptance(args.acceptance)
    report=copy.deepcopy(catalog)
    report.update(coverage=coverage,fully_compatible=False,
                  catalog={'path':str(args.catalog.resolve()),'sha256':catalog_sha},
                  execution_evidence='current_fixed_binary' if acceptance else 'not_executed',
                  implementation_inputs=before,
                  reference_identity={name:reference_identity(ROOT/('downloads/circle-reference' if name=='circle' else 'downloads/safe-cpp-reference'),name)
                                      for name in catalog['references']})
    report['inventory_complete']=bool(catalog.get('inventory_complete') and
       not coverage['documents_needing_review'] and not coverage['features_missing_negative_oracles'])
    if acceptance:
        report['acceptance']={'path':str(args.acceptance.resolve()),'sha256':digest(args.acceptance),
                              'finished_at':acceptance['finished_at'],'gates':acceptance['gates']}
    if args.official_evidence:
        official=json.loads(args.official_evidence.read_text())
        if not official.get('implementation_inputs_stable'):raise ValueError('official evidence is unstable')
        for name,sha in official['implementation_inputs'].items():
            if not pathlib.Path(name).is_file() or digest(name)!=sha:raise ValueError('official evidence is stale: '+name)
        report['original_sources']={'path':str(args.official_evidence.resolve()),'sha256':digest(args.official_evidence),
            'safe_negative_summary':official.get('safe_library',{}).get('negative_summary'),
            'circle_examples':[{k:p[k] for k in ('path','status')} for p in official['library_probes']]}
    for item in report['features']:
        tests=item['local_regressions']
        item['current_regression_status']='not_executed'
        if acceptance and tests and all(pathlib.Path(t).name in registered and t in acceptance['sha256'] for t in tests):
            item['current_regression_status']='registered_regressions_passed; whole-feature equivalence unproven'
        if not tests:item['current_regression_status']='no_executable_semantic_oracle'
    if before!=implementation_snapshot():raise ValueError('implementation changed during matrix generation')
    if digest(args.catalog)!=catalog_sha:raise ValueError('catalog changed during matrix generation')
    if args.acceptance:current_acceptance(args.acceptance)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if args.markdown:
        args.markdown.parent.mkdir(parents=True,exist_ok=True)
        args.markdown.write_text(markdown(report))
    print(f"{coverage['features']} features; {coverage['new_circle_directives']} directives; "+
          f"{coverage['documents']} documents; inventory_complete={report['inventory_complete']}; "+
          f"execution={report['execution_evidence']}")
    if args.require_complete_inventory and not report['inventory_complete']:
        raise SystemExit('Complete semantic inventory is not yet established; see remaining_inventory_work')


if __name__=='__main__':
    main()
