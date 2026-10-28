#!/usr/bin/env python3
"""Index UB wording and library preconditions in the pinned C++20 draft.

This is a review inventory, not an exhaustive semantic extraction or proof.
It includes candidate paragraphs; notes/examples and normative references
still require review. Implicit UB caused by violated requirements can be
absent even when the text does not contain the selected phrases.
"""
import argparse,hashlib,json,pathlib,re
root=pathlib.Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=pathlib.Path,default=root/'proofs/cpp20-ub-inventory.json')
parser.add_argument('--check', action='store_true', help='Verify the existing inventory without changing it')
args=parser.parse_args()
folder=root/'standards/n4861/source'
files=sorted(folder.glob('*.tex'))
if not files:parser.error('missing pinned N4861 sources')
records=[];hashes={}
manifest=json.loads((root/'standards/n4861/manifest.json').read_text())
archive_hash=hashlib.sha256((root/'downloads/cplusplus-n4861.tar.gz').read_bytes()).hexdigest()
if archive_hash!=manifest['archive_sha256']:raise SystemExit('N4861 archive fingerprint mismatch')
for path in files:
    raw=path.read_text();hashes[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    # Ignore TeX comments and index entries; keep line counts stable.
    clean=re.sub(r'(?m)(?<!\\)%[^\n]*','',raw)
    clean=re.sub(r'\\index(?:text|defn)\{[^\n]*?\}',lambda m:'\n'*m[0].count('\n'),clean)
    section=path.stem;paragraph=0
    tokens=list(re.finditer(r'\\rSec\d\[([^\]]+)\]|\\pnum\b',clean))
    for index,token in enumerate(tokens):
        if token.group(1):section=token.group(1);paragraph=0;continue
        paragraph+=1
        end=tokens[index+1].start()if index+1<len(tokens)else len(clean)
        text=clean[token.end():end]
        kinds=[]
        if re.search(r'undefined\s+behavior|behavior\s+is\s+undefined',text,re.I):kinds.append('explicit_ub_wording')
        if re.search(r'\\expects\b',text):kinds.append('library_precondition')
        if not kinds:continue
        line=clean.count('\n',0,token.start())+1
        records.append({'id':f'{path.stem}:{section}:{paragraph}', 'section':section,'paragraph':paragraph,
            'source':str(path.relative_to(root)),'line':line,'kinds':kinds,
            'paragraph_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'source_url':f'https://github.com/cplusplus/draft/blob/n4861/source/{path.name}#L{line}',
            'formal_status':'unproved','implementation_evidence':[],
            'review_status':'pending'})
if hashes!=manifest['sources']:raise SystemExit('N4861 source fingerprint mismatch')
report={'specification':'C++20 working draft N4861','tag':'n4861',
    'archive_sha256':archive_hash,
    'sources':hashes,'candidate_count':len(records),'candidates':records,
    'complete_semantic_ub_catalog':False,
    'limitations':['Lexical extraction requires normative review, including notes and examples.',
      'Implicit preconditions, referenced C/POSIX specifications and implementation extensions are not exhaustively extracted.',
      'No candidate is automatically marked proved merely because code is rejected or tests pass.']}
args.output.parent.mkdir(parents=True,exist_ok=True)
text=json.dumps(report,indent=2,sort_keys=True)+'\n'
if args.check:
    if not args.output.is_file() or args.output.read_text()!=text:raise SystemExit('UB inventory is stale or changed')
    mapping=json.loads((root/'proofs/safety-clause-map.json').read_text())
    indexed={record['id']:record for record in records}
    if mapping['inventory_complete'] or mapping['candidate_count']!=len(records):
        raise SystemExit('partial safety map must preserve the full unproved candidate count')
    for clause in mapping['clauses']:
        original=indexed.get(clause['id'])
        if not original or clause['paragraph_sha256']!=original['paragraph_sha256']:
            raise SystemExit('safety clause mapping is detached from its pinned paragraph')
        if clause['formal_status']!='unproved':
            raise SystemExit('local models and tests do not prove normative clause coverage')
        for name in clause['implementation']+clause['tests']:
            if not (root/name).is_file():raise SystemExit('missing mapped implementation/test: '+name)
    print(f'{len(mapping["clauses"])} partial safety clause mappings checked; all remain unproved')
else:args.output.write_text(text)
print(f'{len(records)} review candidates from {len(files)} pinned source files; formal coverage remains unproved')
