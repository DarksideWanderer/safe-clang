#!/usr/bin/env python3
"""Distinguish mutable holder storage from shared and exclusive carried data."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
API = '''
struct View/(a) {const unsigned^/a value;};
void set/(a,b,c where a:b)(View/b^/c target,const unsigned^/a input) safe {
 target->value=input;
}
using Setter=decltype(set);
Setter* setter() safe {return &set;}
struct Install {
 Install/(a,b,c where a:b)(View/b^/c target,const unsigned^/a input) safe {set(target,input);}
};
struct Writer {Writer(unsigned^ input) safe {*input=0u;}};
unsigned sum(const unsigned^ x,const unsigned^ y) safe {return *x+*y;}
struct Mixed/(a,b) {const unsigned^/a read;unsigned^/b edit;};
void bump/(a,b,c)(Mixed/a/b^/c holder,const unsigned^/a input) safe {
 *holder->edit+=*input;
}
void touch/(a,b,c,d)(Mixed/a/b^/c holder,unsigned^/d output) safe {*output=1u;}
struct Counted/(a) {unsigned count;const unsigned^/a value;};
void counted/(a,c)(Counted/a^/c holder,const unsigned^/c input) safe {
 holder->count=*input;
}
void increment(unsigned^ value) safe {*value+=1u;}
'''
PROGRAM = '''
int main() safe {
 unsigned a=1u,b=2u,out=10u;View first{^const a},second{^const a};
 auto shared=^const a;
 set(^first,shared);setter()(^first,^const b);
 Install install(^first,shared);
 if(*first.value!=1u || *shared!=1u)return 1;
 {
  auto alias=^first;
  set(alias,shared);set(alias,^const b);set(alias,shared);
  if(*shared!=1u)return 2;
 }
 {
  auto alias=^first;
  if(b==2u)alias=^second;
  set(alias,shared);
 }
 for(unsigned i=0u;i<4u;++i) {
  set(^first,^const b);set(^first,shared);
 }
 if(sum(shared,(set(^first,shared),^const a))!=2u)return 3;
 Mixed mixed{shared,^out};
 bump(^mixed,shared);
 if(*mixed.edit!=11u || *mixed.read!=1u)return 4;
 if(*first.value!=1u || *second.value!=1u)return 5;
 return 0;
}
'''
BAD = [
    ('scalar_write', 'void bad() safe {unsigned a=1u;View holder{^const a};'
     'increment(^a);unsigned read=*holder.value;}'),
    ('shared_data_write', 'void bad() safe {unsigned a=1u,b=2u;'
     'Mixed holder{^const a,^b};touch(^holder,^a);unsigned read=*holder.read;}'),
    ('exclusive_data_alias', 'void bad() safe {unsigned a=1u,b=2u;'
     'Mixed holder{^const a,^b};bump(^holder,^const b);}'),
    ('holder_storage_alias', 'void bad() safe {unsigned a=1u;Counted holder{2u,^const a};'
     'counted(^holder,^const holder.count);}'),
    ('live_holder_alias', 'void bad() safe {unsigned a=1u,b=2u;View holder{^const a};'
     'auto alias=^holder;set(^holder,^const b);unsigned read=*alias->value;}'),
    ('live_holder_field_read', 'void bad() safe {unsigned a=1u;View holder{^const a};'
     'auto alias=^holder;auto copy=holder.value;unsigned read=*alias->value+*copy;}'),
    ('short_data', 'void bad() safe {unsigned a=1u;View holder{^const a};'
     '{unsigned b=2u;set(^holder,^const b);}unsigned read=*holder.value;}'),
    ('constructor_invalidates_argument', 'void bad() safe {unsigned a=1u;'
     'unsigned read=sum(^const a,(Writer(^a),^const a));}'),
    ('constructor_invalidates_reverse_argument', 'void bad() safe {unsigned a=1u;'
     'unsigned read=sum((Writer(^a),^const a),^const a);}'),
    ('joined_storage_expires', 'void bad(bool branch) safe {unsigned a=1u;View first{^const a};'
     'auto alias=^first;{View second{^const a};if(branch)alias=^second;}'
     'set(alias,^const a);}'),
]


def main():
    base = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety', '-fcircle-borrow-values',
            '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    with tempfile.TemporaryDirectory(prefix='borrow-capabilities-') as directory:
        d = pathlib.Path(directory)
        module, pcm, obj, source, binary = (d/name for name in ('api.cppm','api.pcm','api.o','client.cpp','run'))
        module.write_text('export module capabilities;export {\n'+API+'}\n')

        def compile(flags, okay=True):
            result = subprocess.run([str(CLANG)]+flags, capture_output=True, text=True, timeout=120)
            assert (result.returncode == 0) == okay, result.stderr+'\n'+source.read_text()
            assert 'PLEASE submit' not in result.stderr, result.stderr
            if not okay:
                assert 'module-safety:' in result.stderr, result.stderr

        # One local/PCM refusal matrix; only execution varies optimization and sanitizer.
        source.write_text(API+PROGRAM)
        compile(base+['-fsyntax-only',str(source)])
        compile(base+['--precompile',str(module),'-o',str(pcm)])
        imported = ['-fmodule-file=capabilities='+str(pcm)]
        for name, body in BAD:
            for use_pcm in (False,True):
                source.write_text(('import capabilities;\n' if use_pcm else API)+body)
                compile(base+(imported if use_pcm else [])+['-fsyntax-only',str(source)],False)
        for opt in ('-O0','-O2'):
            for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
                options = base+[opt]+san
                compile(options+['--precompile',str(module),'-o',str(pcm)])
                compile(options+['-c',str(pcm),'-o',str(obj)])
                for use_pcm in (False,True):
                    source.write_text(('import capabilities;\n' if use_pcm else API)+PROGRAM)
                    compile(options+(imported if use_pcm else [])+[str(source)]+
                            ([str(obj)] if use_pcm else [])+['-o',str(binary)])
                    result = subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
                    assert result.returncode == 0, result.stderr+str(result.returncode)
    print('Holder/data capabilities: repeated direct/indirect/constructor writes, live shared '
          'aliases, mutable alias/rebinding/joins/loops, mixed shared/exclusive fields and '
          'sibling effects execute locally/PCM at O0/O2 plain ASan/UBSan; '
          f'{len(BAD)*2} storage/data/short-life/evaluation refusals passed')


if __name__ == '__main__':
    main()
