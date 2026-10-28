#!/usr/bin/env python3
"""Check real POSIX thread ownership/sharing through module boundaries."""
import pathlib
import os
import subprocess
import sys
import tempfile
clang, plugin, root = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safecpp-threads-') as directory:
    tmp = pathlib.Path(directory)
    sanitizer = os.environ.get('MODULE_SAFETY_THREAD_SANITIZER','address,undefined')
    flags = ['-std=c++20','-pthread','-fsanitize='+sanitizer,'-fno-sanitize-recover=all','-g']
    checked = [clang]+flags+['-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe','-fprebuilt-module-path='+str(tmp)]
    def compile(command, ok=True):
        r = subprocess.run(command, text=True, capture_output=True)
        if (r.returncode == 0) != ok: raise AssertionError(r.stderr)
        if not ok and ('PLEASE submit' in r.stderr or 'frontend command failed' in r.stderr): raise AssertionError(r.stderr)
    for name, source in [('safety','safety.cppm'),('safety_threads','threads.cppm')]:
        compile(checked+['--precompile',root+'/runtime/'+source,'-o',str(tmp/(name+'.pcm'))])
    source = tmp/'thread_checks.cppm'
    source.write_text('''export module thread_checks;
import safety; import safety_threads;
unsigned owned(unsigned x) { return x+1u; }
unsigned shared(const unsigned& x) { return x+2u; }
unsigned container(std2::vector<unsigned> value) { return value.get(0u); }
struct View { const unsigned& ref; };
unsigned read_view(const View& value) { return value.ref; }
struct MutView { unsigned& ref; };
unsigned write_view(MutView value) { value.ref=45u; return value.ref; }
unsigned increment(unsigned value) { return value+1u; }
unsigned throwing(unsigned value) { throw 1; }
unsigned update(const std2::mutex<unsigned>& value) { return value.update<increment>(); }
void update_void(const std2::mutex<unsigned>& value) { auto ignored=value.update<increment>(); }
void own_void(unsigned value) {}
void write_void(MutView value) { value.ref=46u; }
export unsigned run() {
  unsigned x=40u;
  if(std2::run_thread<owned>(x)!=41u) return 1u;
  if(std2::share_thread<shared>(x)!=42u) return 2u;
  std2::vector<unsigned> value; value.push_back(43u);
  if(std2::run_thread<container>(std2::move(value))!=43u) return 3u;
  View view{x};
  if(std2::share_thread<read_view>(view)!=40u) return 4u;
  MutView mutation{x};
  if(std2::scoped_thread<write_view>(std2::move(mutation))!=45u) return 5u;
  if(x!=45u) return 6u;
  for(unsigned i=0u;i<32u;++i) {
    std2::mutex<unsigned> counter(0u);
    auto results=std2::parallel_share<update,update>(counter);
    if(results.first+results.second!=3u || counter.load()!=2u) return 7u;
  }
  std2::mutex<unsigned> guarded(7u);
  try { auto ignored=guarded.update<throwing>(); return 8u; } catch(int) {}
  if(guarded.load()!=7u) return 9u;
  std2::run_thread<own_void>(1u);
  MutView void_view{x}; std2::scoped_thread<write_void>(std2::move(void_view));
  if(x!=46u) return 10u;
  std2::share_thread<update_void>(guarded);
  std2::parallel_share<update_void,update_void>(guarded);
  if(guarded.load()!=10u) return 11u;
  return 0u;
}''')
    compile(checked+['--precompile',str(source),'-o',str(tmp/'thread_checks.pcm')])
    for name in ('safety','safety_threads','thread_checks'):
        compile([clang]+flags+['-fprebuilt-module-path='+str(tmp),'-c',str(tmp/(name+'.pcm')),'-o',str(tmp/(name+'.o'))])
    main=tmp/'main.cpp';main.write_text('import thread_checks; int main() { return run(); }')
    binary=tmp/'threads'
    compile([clang]+flags+['-fprebuilt-module-path='+str(tmp),str(main)]+[str(tmp/(name+'.o')) for name in ('safety','safety_threads','thread_checks')]+['-o',str(binary)])
    subprocess.run([str(binary)],check=True)
    for name, body in [
        ('send_borrow','struct View { const unsigned& ref; }; unsigned target(View v) { return v.ref; } unsigned f() { unsigned x=1u; View v{x}; return std2::run_thread<target>(v); }'),
        ('unsafe_mutex_callback','unsafe_fn unsigned raw(unsigned x) { return x; } unsigned f() { std2::mutex<unsigned> v(1u); return v.update<raw>(); }'),
        ('unsafe_factory','unsafe_fn unsigned raw(unsigned x) { return x; } constexpr auto factory() { unsafe { return &raw; } } unsigned f() { return std2::run_thread<factory()>(1u); }'),
        ('unsafe_functor','struct Target { unsafe_fn unsigned operator()(unsigned x) const { return x; } }; unsigned f() { return std2::run_thread<Target{}>(1u); }'),
        ('unsafe_target','unsafe_fn unsigned target(unsigned x) { return x; } unsigned f() { return std2::run_thread<target>(1u); }'),
        ('moved_owner','unsigned target(std2::vector<unsigned> v) { return v.size(); } unsigned f() { std2::vector<unsigned> v; auto result=std2::run_thread<target>(std2::move(v)); return v.size(); }'),
        ('sync_exclusive_view','struct View { unsigned& ref; }; unsigned target(const View& v) { return v.ref; } unsigned f() { unsigned x=1u; View v{x}; return std2::share_thread<target>(v); }')]:
        source.write_text('export module thread_checks; import safety; import safety_threads; '+body)
        compile(checked+['-fsyntax-only',str(source)],False)
print('Send/Sync: owned/scoped borrowed POSIX threads, parallel mutex updates under '+sanitizer+' and 7 rejection cases passed')
