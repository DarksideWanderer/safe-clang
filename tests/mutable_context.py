#!/usr/bin/env python3
"""Explicit mutable borrow binding, receiver selection and nested context boundaries."""
import json,pathlib,subprocess,sys,tempfile
root=pathlib.Path(__file__).resolve().parent.parent
clang=pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'llvm-build/bin/clang'
body='''
template<class T> struct Cell {
 T value;
 T^ operator*(self^) noexcept safe {return ^self->value;}
 const T^ operator*(const self^) noexcept safe {return ^const self->value;}
 unsigned choose(self^) safe {return 1u;}
 unsigned choose(const self^) safe {return 0u;}
 unsigned consume(self^,unsigned x) safe {return x;}
};
template<class T> unsigned generic_run() safe {
 Cell<T> cell{7u};
 static_assert(__is_same(decltype(*cell),const T&));
 static_assert(__is_same(decltype(mut *cell),T&));
 {T^ loan=mut *cell; *loan=13u;}
 Cell<T> other{3u};
 if (*cell!=13u || cell.choose()!=0u || (mut cell.choose())!=1u) return 0u;
 if ((mut cell.consume(other.choose()))!=0u) return 0u;
 return *cell;
}
template<class T> unsigned known_operator() safe {
 Cell<unsigned> cell{19u};
 return *cell;
}
unsigned run() safe {
 Cell<unsigned> cell{5u};
 {unsigned^ loan=mut *cell; *loan=11u;}
 if (*cell!=11u) return 0u;
 if (generic_run<unsigned>()!=13u || known_operator<unsigned>()!=19u) return 0u;
 return 11u;
}
'''
with tempfile.TemporaryDirectory(prefix='circle-mutable-context-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json'
 policy.write_text(json.dumps({'version':1,'modules':{'mutable_context':'safe'}}))
 base=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values',
       '-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def compile(args,ok=True,expected=None):
  r=subprocess.run([str(clang)]+args,capture_output=True,text=True)
  assert (r.returncode==0)==ok,r.stderr
  assert 'PLEASE submit' not in r.stderr,r.stderr
  if expected: assert expected in r.stderr,r.stderr
  return r
 for opt in ('-O0','-O2'):
  for sanitizer in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   flags=base+[opt]+sanitizer
   source=d/'main.cpp';binary=d/'run'
   source.write_text(body+'int main() {return run()==11u ? 0 : 1;}')
   compile(flags+[str(source),'-o',str(binary)])
   r=subprocess.run([str(binary)],capture_output=True,text=True);assert r.returncode==0,r.stderr
   module=d/'mutable_context.cppm';pcm=d/'mutable_context.pcm';obj=d/'mutable_context.o'
   module.write_text('export module mutable_context; export {\n'+body+'}\n')
   compile(flags+['--precompile',str(module),'-o',str(pcm)])
   compile(flags+['-c',str(pcm),'-o',str(obj)])
   source.write_text('import mutable_context; int main() {return run()==11u && generic_run<unsigned>()==13u && known_operator<unsigned>()==19u ? 0 : 1;}')
   compile(flags+['-fmodule-file=mutable_context='+str(pcm),str(source),str(obj),'-o',str(binary)])
   r=subprocess.run([str(binary)],capture_output=True,text=True);assert r.returncode==0,r.stderr
   for text,expected in (
    ('unsigned f() safe {Cell<unsigned> c{1u}; unsigned^ r=*c; return *r;}','cannot initialize'),
    ('void f() safe {Cell<unsigned> c{1u}; *c=2u;}','read-only'),
    ('unsigned f() safe {const Cell<unsigned> c{1u}; unsigned^ r=mut *c; return *r;}','cannot initialize'),
    ('unsigned f() safe {Cell<unsigned> c{1u}; auto r=^const *c; unsigned^ m=mut *c; *m=2u; return *r;}','mutation conflicts'),
    ('unsigned f() safe {Cell<unsigned> c{1u}; auto r=^const *c; mut c.consume(1u); return *r;}','mutation conflicts'),
    ('unsigned f() safe {Cell<unsigned> a{1u}, b{2u}; return mut a.consume(b.consume(0u));}','no viable conversion'),
    ('template<class T> unsigned f() safe {Cell<T> a{1u}, b{2u}; return mut a.consume(b.consume(0u));} unsigned g() safe {return f<unsigned>();}','no viable conversion'),
    ('unsigned f() safe {return mut []() {Cell<unsigned> c{1u}; return c.consume(0u);}();}','no viable conversion'),
    ('unsigned f() safe {Cell<unsigned> c{1u}; return mut (c.consume(0u));}','no viable conversion'),
    ('template<class T> unsigned unsafe_read(T p) safe {return *p;} unsigned f(unsigned* p) safe {return unsafe_read(p);}','raw pointer dereference'),
   ):
    source.write_text('import mutable_context;\n'+text)
    compile(flags+['-fmodule-file=mutable_context='+str(pcm),'-fsyntax-only',str(source)],False,expected)
print('Mutable scalar loans, shared/default and explicit/mutable receivers, template/PCM projection and argument boundaries pass O0/O2 ASan/UBSan; const/alias/missing-mut violations rejected')
