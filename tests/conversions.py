#!/usr/bin/env python3
"""Exercise exact conversions across PCM boundaries under ASan/UBSan."""
import pathlib, resource, signal, subprocess, sys, tempfile
clang, plugin, root = sys.argv[1:]
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='safecpp-conversions-') as directory:
    tmp = pathlib.Path(directory)
    flags = ['-std=c++20', '-O2', '-fsanitize=address,undefined,float-cast-overflow', '-fno-sanitize-recover=all']
    checked = [clang] + flags + ['-Xclang', '-load', '-Xclang', plugin, '-Xclang', '-add-plugin', '-Xclang', 'module-safety', '-Xclang', '-plugin-arg-module-safety', '-Xclang', 'safe']
    def compile(args, ok=True, needle=''):
        r = subprocess.run(args, text=True, capture_output=True)
        assert (r.returncode == 0) == ok and needle in r.stderr, r.stderr
        return r
    for name, source in [('safety', 'safety'), ('safety_conversions', 'conversions')]:
        compile(checked + ['-fprebuilt-module-path='+str(tmp), '--precompile', root+'/runtime/'+source+'.cppm', '-o', str(tmp/(name+'.pcm'))])
    source = tmp/'convert_checks.cppm'
    source.write_text('''export module convert_checks;
import safety_conversions;
export unsigned run(unsigned test) {
  if (test == 1u) return std2::checked_into<unsigned char>(256u);
  if (test == 2u) return std2::checked_into<unsigned>(-1);
  if (test == 3u) return std2::checked_into<unsigned>(3.5);
  if (std2::into<unsigned long long>(42u) != 42ull) return 1u;
  if (std2::into<double>(42u) != 42.0) return 2u;
  if (!std2::try_into<unsigned char>(255u).ok) return 3u;
  if (std2::try_into<unsigned char>(256u).ok) return 4u;
  if (std2::try_into<unsigned>(-1).ok) return 5u;
  if (std2::try_into<int>(2147483648.0).ok) return 6u;
  if (!std2::try_into<int>(-2147483648.0).ok) return 7u;
  if (std2::try_into<unsigned long long>(0x1p64).ok) return 8u;
  if (std2::try_into<unsigned __int128>(0x1p128).ok) return 9u;
  if (std2::try_into<int>(3.5).ok) return 10u;
  if (!std2::try_into<unsigned>(42.0).ok) return 11u;
  if (std2::try_into<float>(16777217u).ok) return 12u;
  if (!std2::try_into<float>(16777216u).ok) return 13u;
  if (std2::try_into<float>(9007199254740993ull).ok) return 14u;
  if (!std2::try_into<double>(9007199254740992ull).ok) return 15u;
  if (std2::try_into<double>(9007199254740993ull).ok) return 16u;
  if (std2::try_into<float>(0x1p128).ok) return 17u;
  if (std2::try_into<float>(1.1).ok) return 18u;
  if (!std2::try_into<float>(1.5).ok) return 19u;
  unsigned __int128 maxfloat = 340282346638528859811704183484516925440uwb;
  if (!std2::try_into<float>(maxfloat).ok) return 20u;
  if (std2::try_into<float>(maxfloat + 1u).ok) return 21u;
  if (std2::try_into<float>(~static_cast<unsigned __int128>(0u)).ok) return 22u;
  // Exhaust all 16-bit unsigned inputs against an independent range oracle.
  for (unsigned n=0u; n<65536u; ++n) {
    auto byte=std2::try_into<unsigned char>(n);
    if (byte.ok != (n <= 255u)) return 23u;
    if (byte.ok && byte.value != n) return 24u;
    auto signedbyte=std2::try_into<signed char>(n);
    if (signedbyte.ok != (n <= 127u)) return 25u;
  }
  return 0u;
}
export bool nonfinite(double x) { return std2::try_into<int>(x).ok; }
'''.replace('340282346638528859811704183484516925440uwb', '(static_cast<unsigned __int128>(0xffffffu) << 104u)'))
    # Shifts are deliberately expressed in an audited setup region.
    source.write_text(source.read_text().replace('unsigned __int128 maxfloat = (static_cast<unsigned __int128>(0xffffffu) << 104u);', 'unsigned __int128 maxfloat = 0u; unsafe { maxfloat = (static_cast<unsigned __int128>(0xffffffu) << 104u); }'))
    compile(checked + ['-fprebuilt-module-path='+str(tmp), '--precompile', str(source), '-o', str(tmp/'convert_checks.pcm')])
    objects=[]
    for name in ['safety','safety_conversions','convert_checks']:
        obj=tmp/(name+'.o'); objects.append(str(obj))
        compile([clang]+flags+['-fprebuilt-module-path='+str(tmp), '-c', str(tmp/(name+'.pcm')), '-o', str(obj)])
    main=tmp/'main.cpp'
    main.write_text('import convert_checks; int main(int argc,char**argv) { if(argc>1) return int(run(unsigned(argv[1][0]-\'0\'))); if(nonfinite(__builtin_nan("")) || nonfinite(__builtin_inf()) || nonfinite(-__builtin_inf())) return 99; return int(run(0u)); }')
    binary=tmp/'checks'
    compile([clang]+flags+['-fprebuilt-module-path='+str(tmp), str(main)]+objects+['-o',str(binary)])
    r=subprocess.run([str(binary)], text=True,capture_output=True)
    assert r.returncode==0, (r.returncode,r.stderr)
    for n in range(1,4):
        r=subprocess.run([str(binary),str(n)],text=True,capture_output=True)
        assert r.returncode in (-signal.SIGILL,-signal.SIGTRAP,-signal.SIGABRT),r.stderr
        assert 'runtime error:' not in r.stderr and 'ERROR: AddressSanitizer' not in r.stderr,r.stderr
    for name,body in [('narrow','unsigned char f(unsigned x) { return std2::into<unsigned char>(x); }'),('signed','unsigned f(int x) { return std2::into<unsigned>(x); }'),('round','float f(unsigned x) { return std2::into<float>(x); }')]:
        bad=tmp/(name+'.cppm');bad.write_text('export module '+name+'; import safety_conversions; '+body)
        compile(checked+['-fprebuilt-module-path='+str(tmp),'-fsyntax-only',str(bad)],False,'constraints not satisfied')
    retired=tmp/'retired.cppm'
    retired.write_text('export module retired;import safety_conversions;unsigned f(){return std2::onto<unsigned>(1u);}')
    compile(checked+['-fprebuilt-module-path='+str(tmp),'-fsyntax-only',str(retired)],False,"'onto'")
print('Exact conversions: 65536 inputs, integer/float boundaries, NaN/Inf, 3 panics, 3 rejected infallible conversions and retired alias rejection passed under ASan/UBSan')
