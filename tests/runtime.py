#!/usr/bin/env python3
"""Check the audited runtime under ASan/UBSan, including intentional panics."""
import pathlib
import resource
import signal
import subprocess
import sys
import tempfile
clang, plugin, root = sys.argv[1:]
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='module-safety-runtime-') as tmp:
    tmp = pathlib.Path(tmp)
    flags = ['-std=c++20', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-g']
    checked = [clang] + flags + ['-Xclang', '-load', '-Xclang', plugin, '-Xclang', '-add-plugin', '-Xclang', 'module-safety', '-Xclang', '-plugin-arg-module-safety', '-Xclang', 'safe']
    def compile(cmd):
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode: raise AssertionError(result.stderr)
    compile(checked + ['--precompile', root+'/runtime/safety.cppm', '-o', str(tmp/'safety.pcm')])
    source = tmp/'checks.cppm'
    source.write_text('''export module checks;
import safety;
unsigned identity(unsigned value) { return value; }
export unsigned run(unsigned test) {
  if (test == 0u) {
    std2::vector<unsigned> values;
    for (unsigned i=0u; i<128u; ++i) values.push_back(i);
    for (unsigned i=0u; i<128u; ++i) if (values.get(i) != i) return 1u;
    values.set(0u, 42u);
    std2::vector<unsigned> moved(static_cast<std2::vector<unsigned>&&>(values));
    if (moved.size() != 128u || moved.get(0u) != 42u) return 2u;
    if (moved.pop_back() != 127u) return 3u;
    moved.clear(); if (!moved.empty()) return 4u;
    std2::array<int, 3u> a; a.set(1u, -7);
    if (a[1u] != -7 || a[0u] != 0) return 5u;
    if (std2::checked_add(10, 20) != 30) return 6u;
    if (std2::checked_sub(10, 20) != -10) return 7u;
    if (std2::checked_mul(-7, 3) != -21) return 8u;
    if (std2::checked_div(-21, 3) != -7) return 9u;
    if (std2::checked_rem(-22, 3) != -1) return 10u;
    if (std2::checked_shl(3u, 2u) != 12u || std2::checked_shr(12u, 2u) != 3u) return 11u;
    if (std2::checked_cast<unsigned char>(255u) != 255u) return 12u;
    std2::function<unsigned(unsigned)> fn(std2::callable<identity>{});
    auto copy=fn; if (copy(42u) != 42u) return 13u;
    return 0u;
  }
  if (test == 1u) { std2::vector<unsigned> v; return v.get(0u); }
  if (test == 2u) return std2::checked_add(4294967295u, 1u);
  if (test == 3u) return std2::checked_div(1u, 0u);
  if (test == 4u) return std2::checked_div(-2147483647-1, -1);
  if (test == 5u) return std2::checked_cast<unsigned char>(256u);
  if (test == 6u) return std2::checked_shl(1u, 32u);
  if (test == 7u) { std2::array<unsigned, 2u> a; return a.get(2u); }
  if (test == 8u) { std2::vector<unsigned> v; return v.pop_back(); }
  if (test == 9u) return std2::checked_mul(2147483647, 2);
  if (test == 10u) return std2::checked_sub(0u, 1u);
  if (test == 11u) return std2::checked_rem(-2147483647-1, -1);
  if (test == 12u) return std2::checked_shl(2147483648u, 1u);
  if (test == 13u) return std2::checked_cast<unsigned>(-1);
  if (test == 14u) { std2::function<unsigned(unsigned)> empty; return empty(1u); }
  return 0u;
}
''')
    compile(checked + ['-fprebuilt-module-path='+str(tmp), '--precompile', str(source), '-o', str(tmp/'checks.pcm')])
    objects = []
    for module in ('safety', 'checks'):
        obj = tmp/(module+'.o')
        compile([clang]+flags+['-fprebuilt-module-path='+str(tmp), '-c', str(tmp/(module+'.pcm')), '-o', str(obj)])
        objects.append(str(obj))
    main = tmp/'main.cpp'
    main.write_text('import checks; int main(int argc, char** argv) { unsigned n=0u; if(argc>1) for(char* p=argv[1]; *p; ++p) n=n*10u+unsigned(*p-\'0\'); return int(run(n)); }')
    binary = tmp/'checks'
    compile([clang]+flags+['-fprebuilt-module-path='+str(tmp), str(main)]+objects+['-o', str(binary)])
    result = subprocess.run([str(binary), '0'], text=True, capture_output=True)
    if result.returncode: raise AssertionError(result.stderr or f'normal checks failed: {result.returncode}')
    for case in range(1, 15):
        result = subprocess.run([str(binary), str(case)], text=True, capture_output=True)
        if 'runtime error:' in result.stderr or 'ERROR: AddressSanitizer' in result.stderr:
            raise AssertionError(f'case {case}: UB before panic\n{result.stderr}')
        if result.returncode not in (-signal.SIGILL, -signal.SIGTRAP, -signal.SIGABRT):
            raise AssertionError(f'case {case}: expected a panic signal, got {result.returncode}\n{result.stderr}')
print('ASan/UBSan: normal container/arithmetic/callback checks and 14 panic cases passed')
