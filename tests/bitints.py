#!/usr/bin/env python3
"""Actual integer value widths, conversions and shifts across PCM boundaries."""
import pathlib
import resource
import signal
import subprocess
import sys
import tempfile

clang, plugin, root = sys.argv[1:]
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with tempfile.TemporaryDirectory(prefix='safety-bitints-') as directory:
    tmp = pathlib.Path(directory)
    for optimization in ('-O0', '-O2'):
        flags = ['-std=c++20', optimization,
                 '-fsanitize=address,undefined,float-cast-overflow',
                 '-fno-sanitize-recover=all', '-fprebuilt-module-path='+str(tmp)]
        checked = [clang]+flags+['-Xclang', '-load', '-Xclang', plugin,
                                '-Xclang', '-add-plugin', '-Xclang', 'module-safety',
                                '-Xclang', '-plugin-arg-module-safety', '-Xclang', 'safe']

        def compile(arguments, ok=True):
            result = subprocess.run(arguments, text=True, capture_output=True, timeout=60)
            assert (result.returncode == 0) == ok, result.stderr
            assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr
            return result

        for name, filename in [('safety', 'safety'), ('safety_conversions', 'conversions')]:
            compile(checked+['--precompile', root+'/runtime/'+filename+'.cppm',
                             '-o', str(tmp/(name+'.pcm'))])
        source = tmp/'bit_checks.cppm'
        prefix = '''export module bit_checks;import safety;import safety_conversions;
using U1=unsigned _BitInt(1);using U7=unsigned _BitInt(7);using S7=_BitInt(7);
using U17=unsigned _BitInt(17);using S17=_BitInt(17);
using U63=unsigned _BitInt(63);using U127=unsigned _BitInt(127);
static_assert(std2::integer_traits<U1>::digits==1);
static_assert(std2::integer_traits<U7>::digits==7);
static_assert(std2::integer_traits<S7>::digits==6);
static_assert(std2::integer_traits<U17>::digits==17);
static_assert(std2::integer_traits<S17>::digits==16);
static_assert(std2::integer_traits<U63>::digits==63);
static_assert(std2::integer_traits<U127>::digits==127);
static_assert(!std2::integer<const bool>);
static_assert(!std2::lossless_conversion<S17,int>);
static_assert(!std2::lossless_conversion<U7,U17>);
static_assert(std2::lossless_conversion<int,S17>);
static_assert(std2::lossless_conversion<float,U17>);
'''
        # Compile every value width supported by this pinned arm64 frontend,
        # independently of the runtime's formula and libc++ storage traits.
        for width in range(1, 129):
            prefix += f'static_assert(std2::integer_traits<unsigned _BitInt({width})>::digits=={width});\n'
            if width > 1:
                prefix += f'static_assert(std2::integer_traits<_BitInt({width})>::digits=={width-1});\n'
        source.write_text(prefix+'''
export unsigned run(unsigned test){
  if(test==1u)return static_cast<unsigned>(std2::checked_shl(static_cast<U17>(1u),17u));
  if(test==2u)return static_cast<unsigned>(std2::checked_shr(static_cast<U17>(1u),17u));
  if(test==3u)return static_cast<unsigned>(std2::checked_shl(static_cast<U17>(1u),20u));
  if(test==4u)return static_cast<unsigned>(std2::checked_shr(static_cast<U17>(1u),20u));
  if(test==5u)return static_cast<unsigned>(std2::checked_shl(static_cast<U17>(65536u),1u));
  if(test==6u)return static_cast<unsigned>(std2::checked_into<S17>(65536.0));
  if(test==7u)return static_cast<unsigned>(std2::checked_into<U17>(131072.0));
  if(test==8u)return static_cast<unsigned>(std2::checked_into<U1>(2u));
  if(test==9u)return static_cast<unsigned>(std2::checked_shl(static_cast<U1>(1u),1u));
  if(test==10u)return static_cast<unsigned>(std2::checked_shr(static_cast<U7>(1u),7u));
  if(test==11u)return static_cast<unsigned>(std2::checked_shl(static_cast<U127>(1u),127u));
  if(test==12u)return static_cast<unsigned>(std2::checked_shr(static_cast<U63>(1u),63u));
  if(std2::checked_shl(static_cast<U17>(1u),16u)!=static_cast<U17>(65536u))return 1u;
  if(std2::checked_shr(static_cast<U17>(65536u),16u)!=static_cast<U17>(1u))return 2u;
  if(!std2::try_into<S17>(-65536.0).ok)return 3u;
  if(std2::try_into<S17>(65536.0).ok)return 4u;
  if(std2::try_into<S17>(-65537.0).ok)return 5u;
  if(!std2::try_into<U17>(131071.0).ok)return 6u;
  if(std2::try_into<U17>(131072.0).ok)return 7u;
  if(std2::try_into<S7>(64.0).ok || !std2::try_into<S7>(-64.0).ok)return 8u;
  if(!std2::try_into<U1>(1u).ok || std2::try_into<U1>(2u).ok)return 9u;
  if(std2::into<float>(static_cast<U17>(131071u))!=131071.0f)return 10u;
  for(unsigned n=0u;n<=131072u;++n){
    auto a=std2::try_into<S17>(n);auto b=std2::try_into<U17>(n);
    if(a.ok!=(n<=65535u) || b.ok!=(n<=131071u))return 11u;
    if(a.ok && static_cast<unsigned>(a.value)!=n)return 12u;
    if(b.ok && static_cast<unsigned>(b.value)!=n)return 13u;
  }
  return 0u;
}
''')
        compile(checked+['--precompile', str(source), '-o', str(tmp/'bit_checks.pcm')])
        objects = []
        for name in ('safety', 'safety_conversions', 'bit_checks'):
            obj = tmp/(name+'.o')
            compile([clang]+flags+['-c', str(tmp/(name+'.pcm')), '-o', str(obj)])
            objects.append(str(obj))
        main = tmp/'main.cpp'
        main.write_text('''import bit_checks;
int main(int argc,char**argv){unsigned n=0; if(argc>1)for(char*p=argv[1];*p;++p)n=n*10u+unsigned(*p-'0');return int(run(n));}
''')
        binary = tmp/'run'
        compile([clang]+flags+[str(main)]+objects+['-o', str(binary)])
        result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, (result.returncode, result.stderr)
        for case in range(1, 13):
            result = subprocess.run([str(binary), str(case)], text=True, capture_output=True, timeout=30)
            assert result.returncode in (-signal.SIGILL, -signal.SIGTRAP, -signal.SIGABRT), result.stderr
            assert 'runtime error:' not in result.stderr and 'ERROR: AddressSanitizer' not in result.stderr, result.stderr
        source.write_text(prefix+'U7 f(U17 x){return std2::into<U7>(x);}')
        result = compile(checked+['-fsyntax-only', str(source)], False)
        assert 'constraints not satisfied' in result.stderr, result.stderr

print('Actual 1/7/17/63/127-bit widths, 131073 conversion inputs and 24 guarded panics at O0/O2 under ASan/UBSan passed')
