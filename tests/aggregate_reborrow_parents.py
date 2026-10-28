#!/usr/bin/env python3
"""Aggregate reborrows retain ancestors without granting sibling permissions.

Exercise real reads/writes, nested aggregates, conditional joins and imported
templates. Refusals cover exclusivity, storage/referent lifetime, qualification
and initializer effects; compilation failure alone is not a passing oracle.
"""
import json
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
BASE = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
        '-fcircle-borrow-values', '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']

API = r'''
struct Slot/(a) {unsigned^^/a value;};
struct Slots/(a) {unsigned^^/a values[2];};
struct Nested/(a) {Slots/a inner;};
struct ReadSlot/(a) {const unsigned^/a value;};
template<class T+> struct Carrier {T value;};
unsigned read_slot(const [unsigned^^;dyn]^ input, unsigned index) safe {
  unsigned^const^ value = input[index];
  return **value;
}
unsigned take_slot(Slot/a input) safe {return **input.value;}
unsigned take_nested(Nested/a input) safe {
  return **input.inner.values[0u]+**input.inner.values[1u];
}
unsigned pair_slots(Slot/a first, Slot/b second) safe {
  return **first.value+**second.value;
}
unsigned take_with_tag(Slot/a input, unsigned tag) safe {return **input.value+tag;}
unsigned consume_borrow(unsigned^ input) safe {return *input;}
unsigned consume_with_tag(unsigned^ input, unsigned tag) safe {return *input+tag;}
template<class T> unsigned dependent_array() safe {
  T x=7u, y=11u;
  T^ p=^x; T^ q=^y;
  T^^ values[2][1]={{^p},{^q}};
  **values[0u][0u]=13u;
  return static_cast<unsigned>(**values[0u][0u]+**values[1u][0u]);
}
template<class T+> unsigned dependent_carrier(T input) safe {
  Carrier<T> holder{rel input};
  return **holder.value.value;
}
unsigned run_aggregate(bool branch) safe {
  unsigned x=1u,y=2u;
  unsigned^ p=^x; unsigned^ q=^y;
  {
    unsigned^^ values[2]={^p,^q};
    **values[0u]=3u; **values[1u]=5u;
    if(**values[0u]+**values[1u]!=8u) return 1u;
    const [unsigned^^;dyn]^ slice=^const values;
    auto copy=slice;
    auto indirect=&read_slot;
    if(read_slot(copy,0u)!=3u || indirect(slice,1u)!=5u) return 2u;
  }
  // Last-use expiry permits the parents again, including writes.
  *p=7u; *q=11u;
  {
    unsigned^^ values[1][2]={{^p,^q}};
    if(**values[0u][0u]!=7u || **values[0u][1u]!=11u) return 3u;
  }
  {
    Slot holder{^p};
    **holder.value=13u;
    Slot moved=rel holder;
    if(**moved.value!=13u) return 4u;
  }
  {
    Nested holder{Slots{{^p,^q}}};
    if(**holder.inner.values[0u]!=13u || **holder.inner.values[1u]!=11u) return 5u;
  }
  {
    Slot values[2]={{^p},{^q}};
    if(**values[0u].value!=13u || **values[1u].value!=11u) return 6u;
  }
  {
    ReadSlot first{^const *p}; ReadSlot copied=first;
    if(*copied.value!=13u || *first.value!=13u) return 7u;
  }
  {
    unsigned^^ values[1]={branch ? ^p : ^p};
    unsigned^const^ alias;
    if(branch) alias=^const *values[0u];
    else alias=^const *values[0u];
    if(**alias!=13u) return 8u;
  }
  // Earlier side effects followed by a later borrow are sequenced safely.
  {
    unsigned z=17u;
    unsigned^ a=^z;
    unsigned^^ values[2]={(*p=19u,^a),^p};
    if(**values[0u]!=17u || **values[1u]!=19u) return 9u;
  }
  return 0u;
}
'''

CLIENT = r'''
unsigned client() safe {
  if(run_aggregate(false)!=0u || run_aggregate(true)!=0u) return 1u;
  if(dependent_array<unsigned>()!=24u) return 2u;
  unsigned x=23u;
  unsigned^ p=^x;
  Slot holder{^p};
  if(dependent_carrier(rel holder)!=23u) return 3u;
  if(dependent_carrier(Slot{^p})!=23u) return 4u;
  if(take_slot(Slot{^p})!=23u) return 5u;
  auto indirect=&take_slot;
  if(indirect(Slot{^p})!=23u) return 6u;
  unsigned y=29u;unsigned^ q=^y;
  if(pair_slots(Slot{^p},Slot{^q})!=52u) return 7u;
  if(take_nested(Nested{Slots{{^p,^q}}})!=52u) return 8u;
  *p=31u;
  if(*p!=31u) return 9u;
  if(consume_borrow(rel p)!=31u) return 10u;
  return 0u;
}
int main() safe {return static_cast<int>(client());}
'''

NEGATIVES = [
    ('duplicate_element',
     'void bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[2]={^p,^p};(void)a;}',
     'array elements alias an exclusive borrow'),
    ('duplicate_nested_element',
     'void bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[2][1]={{^p},{^p}};(void)a;}',
     'array elements alias an exclusive borrow'),
    ('parent_write',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};*p=2u;return **a[0u];}',
     'mutation conflicts with a live borrow'),
    ('owner_write',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};x=2u;return **a[0u];}',
     'mutation conflicts with a live borrow'),
    ('parent_rebind',
     'unsigned bad() safe {unsigned x=1u,y=2u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};p=^y;return **a[0u];}',
     'container mutation conflicts with a live storage borrow'),
    ('sibling_loan',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};unsigned^^ b[1]={^p};return **a[0u]+**b[0u];}',
     'object borrow conflicts with a live borrow'),
    ('grandparent_write',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};const [unsigned^^;dyn]^ s=^const a;'
     '*p=2u;return read_slot(s,0u);}',
     'mutation conflicts with a live borrow'),
    ('live_slice_array_write',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};const [unsigned^^;dyn]^ s=^const a;'
     '**a[0u]=2u;return read_slot(s,0u);}',
     'conflicts with a live'),
    ('shared_slice_exclusive_copy',
     'void bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};const [unsigned^^;dyn]^ s=^const a;'
     'unsigned^^ copy=s[0u];**copy=2u;}',
     'cannot initialize'),
    ('readonly_handle_rebind',
     'void bad() safe {unsigned x=1u,y=2u;unsigned^ p=^x;'
     'unsigned^const^ a[1]={^const p};*a[0u]=^y;}',
     'read-only variable'),
    ('aggregate_parent_write',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'Slot holder{^p};*p=2u;return **holder.value;}',
     'mutation conflicts with a live borrow'),
    ('nested_parent_write',
     'unsigned bad() safe {unsigned x=1u,y=2u;unsigned^ p=^x;unsigned^ q=^y;'
     'Nested holder{Slots{{^p,^q}}};*p=3u;return **holder.inner.values[0u];}',
     'mutation conflicts with a live borrow'),
    ('moved_holder_use',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'Slot holder{^p};Slot moved=rel holder;return **holder.value+**moved.value;}',
     'moved'),
    ('local_escape',
     'ReadSlot/a bad/(a)(const unsigned^/a input) safe {'
     'unsigned local=1u;unsigned^ p=^local;ReadSlot h{^const *p};return h;}',
     'returned reference does not borrow from the declared lifetime source'),
    ('expired_nested_owner',
     'unsigned bad() safe {unsigned^^ escaped;{unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};escaped=^*a[0u];}return **escaped;}',
     'borrow outlives its owner'),
    ('static_escape',
     'void bad() safe {unsigned x=1u;unsigned^ p=^x;unsigned^^ a[1]={^p};'
     'const [unsigned^^;dyn]^/static leaked=^const a;(void)leaked;}',
     'static borrow variable lifetime contract'),
    ('unrelated_constituent',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'const unsigned^ a[2]={^const *p,^const x};return *a[0u]+*a[1u];}',
     'object borrow conflicts with a live borrow'),
    ('conditional_unrelated_source',
     'unsigned bad(bool b) safe {unsigned x=1u;unsigned^ p=^x;'
     'const unsigned^ a[1]={b ? ^const *p : ^const x};return *a[0u];}',
     'object borrow conflicts with a live borrow'),
    ('later_initializer_rebind',
     'unsigned bad() safe {unsigned x=1u,y=2u,z=3u;unsigned^ p=^x;unsigned^ q=^y;'
     'unsigned^^ a[2]={^p,(p=^z,^q)};return **a[0u]+**a[1u];}',
     'argument evaluation invalidates a temporary borrow'),
    ('later_initializer_write',
     'unsigned bad() safe {unsigned x=1u,y=2u;unsigned^ p=^x;unsigned^ q=^y;'
     'unsigned^^ a[2]={^p,(*p=3u,^q)};return **a[0u]+**a[1u];}',
     'argument evaluation invalidates a temporary borrow'),
    ('conditional_rebind',
     'unsigned bad(bool b) safe {unsigned x=1u,y=2u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};if(b)p=^y;return **a[0u];}',
     'container mutation conflicts with a live storage borrow'),
    ('joined_parent_write',
     'unsigned bad(bool b) safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};unsigned^const^ alias;'
     'if(b)alias=^const *a[0u];else alias=^const *a[0u];'
     '*p=2u;return **alias;}',
     'mutation conflicts with a live borrow'),
    ('temporary_argument_duplicate',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'return pair_slots(Slot{^p},Slot{^p});}',
     'aliased arguments violate exclusive borrowing'),
    ('temporary_argument_sibling_write',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'return take_with_tag(Slot{^p},(*p=2u,0u));}',
     'argument evaluation invalidates a temporary borrow'),
    ('temporary_argument_live_child',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;Slot holder{^p};'
     'unsigned value=take_slot(Slot{^p});return value+**holder.value;}',
     'conflicts with a live'),
    ('temporary_nested_duplicate',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'return take_nested(Nested{Slots{{^p,^p}}});}',
     'array elements alias an exclusive borrow'),
    ('indirect_temporary_duplicate',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;auto call=&pair_slots;'
     'return call(Slot{^p},Slot{^p});}',
     'aliased arguments violate exclusive borrowing'),
    ('temporary_expired_owner',
     'unsigned bad() safe {unsigned^^ escaped;{unsigned x=1u;unsigned^ p=^x;'
     'unsigned^^ a[1]={^p};escaped=^*a[0u];}return take_slot(Slot{^*escaped});}',
     'borrow outlives its owner'),
    ('transfer_twice',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;Slot holder{^p};'
     'unsigned value=take_slot(rel holder);return value+take_slot(rel holder);}',
     'relocated'),
    ('transfer_sibling_write',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;Slot holder{^p};'
     'return take_with_tag(rel holder,(*p=2u,0u));}',
     'argument evaluation invalidates a temporary borrow'),
    ('expired_borrow_transfer',
     'unsigned bad() safe {unsigned^ escaped;{unsigned x=1u;escaped=^x;}'
     'return consume_borrow(rel escaped);}',
     'borrow outlives its owner'),
    ('borrow_use_after_transfer',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'unsigned value=consume_borrow(rel p);return value+*p;}',
     'relocated'),
    ('borrow_transfer_sibling_write',
     'unsigned bad() safe {unsigned x=1u;unsigned^ p=^x;'
     'return consume_with_tag(rel p,(x=2u,0u));}',
     'argument evaluation invalidates a temporary borrow'),
]


def main():
    with tempfile.TemporaryDirectory(prefix='aggregate-reborrow-') as directory:
        d = pathlib.Path(directory)
        source, module, pcm, obj, binary = (d/name for name in
            ('client.cpp', 'api.cppm', 'api.pcm', 'api.o', 'run'))
        policy = d/'policy.json'
        policy.write_text(json.dumps({'version': 1, 'modules': {'aggregate_parents': 'safe'}}))
        base = BASE+['-fmodule-safety-policy='+str(policy)]
        module.write_text('export module aggregate_parents;\nexport {\n'+API+'}\n')

        def compile(arguments, diagnostic=None, label='positive'):
            result = subprocess.run([str(CLANG)]+arguments, capture_output=True,
                                    text=True, timeout=120)
            assert result.returncode >= 0, label+' compiler signal\n'+result.stderr
            assert 'PLEASE submit' not in result.stderr, label+'\n'+result.stderr
            assert 'frontend command failed' not in result.stderr, label+'\n'+result.stderr
            if diagnostic is None:
                assert result.returncode == 0, label+'\n'+result.stderr
            else:
                assert result.returncode != 0 and diagnostic in result.stderr, (
                    label+' expected '+diagnostic+'\n'+result.stderr)

        refusals = executions = 0
        for optimization in ('-O0', '-O2'):
            for sanitize in (False, True):
                flags = base+[optimization]
                if sanitize:
                    flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
                compile(flags+['--precompile', str(module), '-o', str(pcm)])
                compile(flags+['-c', str(pcm), '-o', str(obj)])
                for imported in (False, True):
                    prefix = 'import aggregate_parents;\n' if imported else API
                    imports = ['-fmodule-file=aggregate_parents='+str(pcm)] if imported else []
                    source.write_text(prefix+CLIENT)
                    compile(flags+imports+[str(source)]+([str(obj)] if imported else [])+
                            ['-o', str(binary)])
                    result = subprocess.run([str(binary)], capture_output=True, text=True,
                        timeout=60, env=dict(os.environ, ASAN_OPTIONS='detect_stack_use_after_return=1'))
                    assert result.returncode == 0, result.stdout+result.stderr
                    executions += 1
                    # Optimization and PCM are relevant to semantic refusal;
                    # sanitizer changes only the execution checks above.
                    if sanitize:
                        continue
                    for name, body, diagnostic in NEGATIVES:
                        source.write_text(prefix+body)
                        compile(flags+imports+['-fsyntax-only', str(source)], diagnostic, name)
                        refusals += 1
        print(f'Aggregate reborrow parents: {executions} local/PCM O0/O2 plain/ASan/UBSan '
              f'executions; {refusals} attributed refusals across {len(NEGATIVES)} cases')


if __name__ == '__main__':
    main()
