#!/usr/bin/env python3
"""A class-value result binds its region to the one borrow the signature supplies."""
import json, os, pathlib, subprocess, tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = root/'llvm-build/bin/clang'
api = '''struct Word/(a) {const unsigned^/a value;};
struct Sample/(a) {const unsigned^/a value;};
Word make(const unsigned^ input) safe {return Word{input};}
struct Owner {
 unsigned value = 0u;
 Sample view(self const^) safe {return Sample{^self->value};}
};
template<class T> struct Boxed/(a) {const T^/a value;};
template<class T> Boxed<T> box(const T^ input) safe {return Boxed<T>{input};}
struct SliceView/(a) {const [unsigned; dyn]^/a data;};
struct TextView/(a) {const [char; dyn]^/a data;};
struct SliceHolder/(a) {
 const [unsigned; dyn]^/a data;
 SliceView to_view(self const^) safe {return SliceView{self->data};}
 operator SliceView(self const^) safe {return SliceView{self->data};}
};
inline auto operator""_sv(const char* p, unsigned long n) noexcept safe -> TextView/static {
 unsafe { return TextView{^*__slice_pointer(p, n)}; }
}
'''
main = '''const [unsigned; dyn]^/a raw_slice/(a)(const unsigned* p, unsigned n) unsafe {
 return ^*__slice_pointer(p, n);
}
int main() safe {
 unsigned one = 11u;
 auto first = make(^const one);
 if(*first.value != 11u) return 1;
 Owner owner{}; owner.value = 13u;
 auto second = owner.view();
 if(*second.value != 13u) return 2;
 unsigned long wide = 17ul;
 auto third = box<unsigned long>(^const wide);
 if(*third.value != 17ul) return 3;
 unsigned raw[3] = {4u, 5u, 6u};
 unsafe {
  auto slice = raw_slice(raw, 3u);
  SliceHolder holder{slice};
  auto view = holder.to_view();
  if((*view.data)[1u] != 5u) return 4;
  SliceView converted = holder;
  if((*converted.data)[2u] != 6u) return 5;
 }
 auto literal = "hi"_sv;
 if((*literal.data)[1u] != 'i') return 6;
 return 0;
}
'''
negative = [
 ('Word bad(const unsigned^ input) safe {unsigned local = 1u;return Word{^const local};}',
  'returned reference does not borrow from the declared lifetime source'),
 ('Word bad(const unsigned^ a,const unsigned^ b) safe {return Word{a};}',
  'native borrow result requires a checked lifetime contract'),
 ('unsigned bad() safe {unsigned one = 1u;auto w = make(^const one);one = 2u;return *w.value;}',
  'mutation conflicts with a live borrow'),
 ('unsigned bad() safe {Owner owner{};auto w = owner.view();owner.value = 2u;return *w.value;}',
  'mutation conflicts with a live borrow'),
 ('SliceView/a bad_slice_source/(a,b)(const [unsigned; dyn]^/a a,const [unsigned; dyn]^/b b) safe {return SliceView{b};}',
  'returned reference does not borrow from the declared lifetime source'),
 ('unsigned bad_literal() safe {char local[2] = {"x"};auto v = operator""_sv(local, 1u);return 0;}',
  'static lifetime contract requires permanent non-thread-local borrow origins'),
]
with tempfile.TemporaryDirectory(prefix='class-lifetime-elision-') as td:
 d = pathlib.Path(td); policy = d/'policy.json'
 policy.write_text(json.dumps({'version': 1, 'modules': {'elided_api': 'safe'}}))
 flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety', '-fcircle-borrow-values',
          '-fmodule-safety-policy='+str(policy), '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 source = d/'main.cpp'; exe = d/'run'
 for opt in ('-O0', '-O2'):
  for san in ([], ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']):
   options = flags+[opt]+san
   module = d/'api.cppm'; pcm = d/'api.pcm'; obj = d/'api.o'
   module.write_text('export module elided_api;\nexport {\n'+api+'\n}\n')
   for args in (['--precompile', str(module), '-o', str(pcm)], ['-c', str(pcm), '-o', str(obj)]):
    result = subprocess.run([str(clang)]+options+args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
   for imported in (False, True):
    prefix = 'import elided_api;\n' if imported else api
    imports = ['-fmodule-file=elided_api='+str(pcm)] if imported else []
    source.write_text(prefix+main)
    result = subprocess.run([str(clang)]+options+imports+[str(source)]+([str(obj)] if imported else [])+['-o', str(exe)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(exe)], capture_output=True, text=True,
                            env=dict(os.environ, ASAN_OPTIONS='detect_stack_use_after_return=1'))
    assert result.returncode == 0, result.stderr
    for body, diag in negative:
     source.write_text(prefix+body)
     result = subprocess.run([str(clang)]+options+imports+['-fsyntax-only', str(source)],
                             capture_output=True, text=True)
     assert result.returncode != 0 and diag in result.stderr and 'PLEASE submit' not in result.stderr, result.stderr
print('Class results elide their region to the one borrow input they declare: free, receiver and template '
      'results, local/PCM O0/O2 plain ASan/UBSan, 8 runs, {} refusals'.format(8*len(negative)))
