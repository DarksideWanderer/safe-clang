#!/usr/bin/env python3
"""A borrow of a borrow, and `cpy`/`rel` of a whole slice borrow."""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'
policy = root/'build/circle-compatibility.policy.json'
driver = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
          '-fcircle-borrow-values', '-fmodule-safety-policy='+str(policy)]

PROGRAM = '''#include <cstdio>
#feature on safety

unsigned long length(const [char; dyn]^ s) noexcept safe { return (*s)~length; }
const char* address(const [char; dyn]^ s) noexcept safe { unsafe { return (*s)~as_pointer; } }

void exercise(const [char; dyn]^ slice) safe {

  // The whole slice borrow is a pair of address and count: `cpy` reads it
  // again, and `rel` takes it out of the place it was.
  const [char; dyn]^ copied = cpy slice;
  const [char; dyn]^ moved = rel slice;

  // A borrow of a borrow names the storage the handle occupies, so the handle
  // is read back through it.
  const [char; dyn]^ restored = cpy copied;
  const decltype(restored)^ handle = ^const restored;
  static_assert(__is_const(__remove_reference_t(decltype(*handle))));
  const [char; dyn]^ read = *handle;

  unsafe { std::printf("%lu %lu %lu %lu\\n", length(copied), length(moved),
              length(restored), length(read));
  std::printf("%d %d\\n", address(copied) == address(restored),
              address(moved) == address(read)); }
}

void mutable_exercise([unsigned; dyn]^ slice) safe {
  auto moved=rel slice;
  moved[0]=7u;
  auto handle=^moved;
  (*handle)[1]=9u;
}

// The raw pointer intrinsic is an unsafe entry boundary. All handle transfers
// and nested borrowing above are checked in the independent safe function.
int main() unsafe {
  const char* text = "hi";
  exercise(^*__slice_pointer(text, 2));
  unsigned values[2]={1u,2u};
  mutable_exercise(^*__slice_pointer(&values[0], 2));
  std::printf("%u %u\\n",values[0],values[1]);
  return 0;
}
'''

EXPECTED = ['2 2 2 2', '1 1', '7 9']

with tempfile.TemporaryDirectory(prefix='nested-borrows-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version':1, 'modules':{'nested_borrows':'safe','nested_borrows_other':'safe'}}))
    driver[-1] = '-fmodule-safety-policy='+str(policy)
    driver += ['-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    source = tmp/'borrows.cpp'

    def check(arguments, ok=True, diagnostic=None):
        result = subprocess.run([str(clang)]+arguments, text=True,
                                capture_output=True, timeout=120)
        assert (result.returncode == 0) == ok, result.stderr+"\n"+source.read_text()
        assert 'PLEASE submit' not in result.stderr, result.stderr
        assert 'frontend command failed' not in result.stderr, result.stderr
        if diagnostic:
            assert diagnostic in result.stderr, result.stderr
        return result

    def execute(binary):
        run = subprocess.run([str(binary)], text=True, capture_output=True,
                             timeout=60)
        assert run.returncode == 0 and run.stdout.splitlines() == EXPECTED, (
            run.returncode, run.stdout, run.stderr)

    entry = PROGRAM[PROGRAM.index('int main() unsafe'):]
    implementation = PROGRAM[:PROGRAM.index('// The raw pointer intrinsic')]
    implementation = implementation.replace('#include <cstdio>',
                                            'module;\n#include <cstdio>')
    implementation = implementation.replace('#feature on safety',
        'export module nested_borrows;\n#feature on safety\nexport {') + '}\n'
    for optimization in ('-O0','-O2'):
        for sanitize in (False, True):
            flags = driver+[optimization]
            if sanitize:
                flags += ['-fsanitize=address,undefined','-fno-sanitize-recover=all']
            source.write_text(PROGRAM)
            binary = tmp/'borrows'
            check(flags+[str(source), '-o', str(binary)])
            execute(binary)
            module = tmp/'borrows.cppm'; module.write_text(implementation)
            pcm = tmp/'nested_borrows.pcm'; obj = tmp/'nested_borrows.o'
            check(flags+['--precompile', str(module), '-o', str(pcm)])
            check(flags+['-c', str(pcm), '-o', str(obj)])
            other = tmp/'other.cppm'
            other.write_text('export module nested_borrows_other;\n'
                'export unsigned long count_other(const [char;dyn]^ s) safe {return (*s)~length;}\n'
                'export unsigned long mutable_count_other([unsigned;dyn]^ s) safe {return (*s)~length;}\n')
            other_pcm=tmp/'nested_borrows_other.pcm'; other_obj=tmp/'other.o'
            check(flags+['--precompile',str(other),'-o',str(other_pcm)])
            check(flags+['-c',str(other_pcm),'-o',str(other_obj)])
            consumer = tmp/'consumer.cpp'
            module_entry=entry.replace('  exercise(',
                '  if(count_other(^*__slice_pointer(text,2))!=2ul) return 1;\n  exercise(')
            module_entry=module_entry.replace('  mutable_exercise(',
                '  if(mutable_count_other(^*__slice_pointer(&values[0],2))!=2ul) return 2;\n  mutable_exercise(')
            for reverse in (False, True):
                imports=('import nested_borrows_other;\nimport nested_borrows;\n'
                         if reverse else 'import nested_borrows;\nimport nested_borrows_other;\n')
                force='count_other' if reverse else 'exercise'
                consumer.write_text('#include <cstdio>\n'+imports+
                    'static_assert(sizeof(&'+force+')==sizeof(void*));\n'+module_entry)
                check(flags+['-fprebuilt-module-path='+str(tmp),str(consumer),
                             str(obj),str(other_obj),'-o',str(binary)])
                execute(binary)

    negatives = (
        ('void bad(const [unsigned; dyn]^ s) safe { s[0]=1u; }',
         'const'),
        ('void bad([unsigned; dyn]^ s) safe { auto copy=cpy s; s[0]=1u; copy[0]=2u; }',
         'exclusive borrow'),
        ('void bad(const [char; dyn]^ s) safe { auto moved=rel s; length(s); }',
         'moved'),
        ('void bad(const [char; dyn]^ s) safe { const decltype(s)^ h=^const s; *h=cpy s; }',
         'const'),
        ('void bad(const [char; dyn]^ s) safe { auto h=^s; length(s); length(*h); }',
         'borrow'),
        ('void bad() safe { std::printf("bad"); }',
         'unsafe or unclassified'),
        ('void bad() safe { unsafe { auto f=[]() { std::printf("bad"); }; } }',
         'unsafe or unclassified'),
        ('void bad(const char* p) safe { const [char; dyn]^ s=^*__slice_pointer(p,2); }',
         'provenance'),
    )
    prefix = '#include <cstdio>\nunsigned long length(const [char; dyn]^ s) safe {return (*s)~length;}\n'
    for body, diagnostic in negatives:
        for imported in (False, True):
            declarations = ('#include <cstdio>\nimport nested_borrows;\n'
                            'static_assert(sizeof(&exercise)==sizeof(void*));\n'
                            if imported else prefix)
            source.write_text(declarations+body)
            # The last positive PCM was sanitized/O2; preserve its build flags.
            negative_flags = flags+['-fprebuilt-module-path='+str(tmp)] if imported else driver
            check(negative_flags+['-fsyntax-only',str(source)], False, diagnostic)

print('Shared slice copy/relocation and const nested handle storage: local/two-PCM '
      'O0/O2 with ASan/UBSan, exact output and sixteen local/two-PCM safety refusals passed')
