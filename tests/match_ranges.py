#!/usr/bin/env python3
"""Fixed Circle half-open ranges, through PCM at actual O0/O2 with sanitizers."""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT/'llvm-build/bin/clang'
MODULE = '''export module ranges;
export constexpr unsigned spaced(unsigned x) safe {
  return match(x) -> unsigned { 10 ... 20 => 1u; _ => 0u; };
}
export constexpr unsigned packed(unsigned x) safe {
  return match(x) -> unsigned { 10...20 => 1u; _ => 0u; };
}
export constexpr unsigned empty(unsigned x) safe {
  return match(x) -> unsigned { 10...10 => 1u; _ => 0u; };
}
export constexpr unsigned reversed(unsigned x) safe {
  return match(x) -> unsigned { 20...10 => 1u; _ => 0u; };
}
export constexpr unsigned narrow(unsigned char x) safe {
  return match(x) -> unsigned { 250...256 => 1u; _ => 0u; };
}
export constexpr unsigned no_wrap(unsigned char x) safe {
  return match(x) -> unsigned { 256 => 1u; _ => 0u; };
}
export constexpr unsigned suffixed(unsigned x) safe {
  return match(x) -> unsigned { 0xaU...024UL => 1u; _ => 0u; };
}
export choice Number { default absent, number(unsigned) };
export unsigned nested(Number value) safe {
  return match(value) -> unsigned {
    .number(10...20) => 1u; .number(_) => 0u; .absent => 2u;
  };
}
export unsigned nested_value(unsigned x) safe {
  Number value=.number(x);
  return nested(rel value);
}
export unsigned nested_absent() safe {
  Number value=.absent;
  return nested(rel value);
}
static_assert(spaced(9u)==0u && spaced(10u)==1u && spaced(19u)==1u && spaced(20u)==0u);
static_assert(packed(20u)==0u && empty(10u)==0u && reversed(15u)==0u);
static_assert(narrow(255)==1u && narrow(249)==0u && no_wrap(0)==0u);
static_assert(suffixed(10u)==1u && suffixed(20u)==0u);
'''
CLIENT = '''export module rangeclient;
import ranges;
static_assert(spaced(20u)==0u && packed(19u)==1u);
export unsigned run_rangeclient() safe {
  for(unsigned i=0u; i<32u; ++i) {
    const unsigned expected = i>=10u && i<20u ? 1u : 0u;
    if(spaced(i)!=expected || packed(i)!=expected || empty(i)!=0u || reversed(i)!=0u)
      return 1;
    Number number=.number(i);
    if(nested(rel number)!=expected || nested_value(i)!=expected) return 2u;
    if(suffixed(i)!=expected) return 4;
  }
  for(unsigned i=0u; i<256u; ++i) {
    const auto value=static_cast<unsigned char>(i);
    if(narrow(value)!=(i>=250u ? 1u : 0u) || no_wrap(value)!=0u) return 5;
  }
  Number missing=.absent;
  return nested(rel missing)==2u && nested_absent()==2u ? 0u : 3u;
}
'''
MAIN = 'import rangeclient; int main(){ return static_cast<int>(run_rangeclient()); }\n'

with tempfile.TemporaryDirectory(prefix='match-ranges-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version':1, 'modules':{'ranges':'safe', 'rangeclient':'safe'}}))
    base = [str(CLANG), '--driver-mode=g++', '-std=c++20',
            '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22',
            '-fprebuilt-module-path='+str(tmp)]
    checked = ['-fcircle-safety', '-fcircle-borrow-values',
               '-fmodule-safety-policy='+str(policy)]
    source = tmp/'ranges.cppm'
    source.write_text(MODULE)
    client = tmp/'rangeclient.cppm'
    client.write_text(CLIENT)
    main = tmp/'main.cpp'
    main.write_text(MAIN)
    def compile(args):
        result = subprocess.run(base+args, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stderr)
    for optimization in ('-O0', '-O2'):
        flags = [optimization, '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        compile(flags+checked+['--precompile', str(source), '-o', str(tmp/'ranges.pcm')])
        compile(flags+['-c', str(tmp/'ranges.pcm'), '-o', str(tmp/'ranges.o')])
        compile(flags+checked+['--precompile', str(client), '-o', str(tmp/'rangeclient.pcm')])
        compile(flags+['-c', str(tmp/'rangeclient.pcm'), '-o', str(tmp/'rangeclient.o')])
        compile(flags+[str(main), str(tmp/'ranges.o'), str(tmp/'rangeclient.o'), '-o', str(tmp/'run')])
        subprocess.run([str(tmp/'run')], check=True, timeout=30)
    for spelling in ('10..20', '10....20', '10...=20'):
        source.write_text('export module ranges; unsigned f(unsigned x) safe {'
                          ' return match(x) -> unsigned { '+spelling+' => 1u; _ => 0u; }; }')
        result = subprocess.run(base+checked+['-fsyntax-only', str(source)], capture_output=True, text=True)
        if result.returncode==0 or ('range pattern' not in result.stderr):
            raise AssertionError('malformed range accepted or unrelated failure: '+result.stderr)
print('Circle half-open match ranges: constexpr, nested payloads, PCM, actual O0/O2 ASan/UBSan and malformed spelling checks passed')
