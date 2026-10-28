#!/usr/bin/env python3
"""Cross-PCM generic lifetime intersections and exception cleanup, O0/O2."""
import pathlib, subprocess, sys, tempfile
clang, plugin, root = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='safecpp-lifecycle-') as directory:
    tmp=pathlib.Path(directory)
    for optimization in ('-O0','-O2'):
        flags=['-std=c++20',optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all','-fprebuilt-module-path='+str(tmp),'-I'+root+'/include']
        checked=[clang]+flags+['-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe']
        def compile(args,ok=True,needle=''):
            result=subprocess.run(args,text=True,capture_output=True)
            assert (result.returncode==0)==ok and needle in result.stderr,result.stderr+'\n'+(client.read_text() if 'client' in locals() or 'client' in globals() else '')
            assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr,result.stderr
        for name,file in [('safety','safety.cppm'),('safety_atomic','atomic.cppm'),('safety_ownership','ownership.cppm'),('safety_borrows','borrows.cppm'),('safety_lifetimes','lifetimes.cppm')]:
            compile(checked+['--precompile',root+'/runtime/'+file,'-o',str(tmp/(name+'.pcm'))])
        api=tmp/'lifetimes.cppm'
        api.write_text('''module;
#include "module_safety.h"
export module lifetimes;
import safety_atomic;
import safety_ownership;
import safety_borrows;
import safety_lifetimes;
export template<class T> SAFETY_RETURNS_LIFETIME(region)
const T& choose(bool first,SAFETY_LIFETIME(region) const T&a,SAFETY_LIFETIME(region) const T&b){if(first)return a;return b;}
export template<class T> SAFETY_RETURNS_BORROW(a) SAFETY_RETURNS_BORROW(b)
const T& relay(bool first,const T&a,const T&b){return choose(first,a,b);}
export template<class T> SAFETY_RETURNS_BORROW(a)
const T& wrong(const T&a){T local{};return local;}
export struct OperatorView {const unsigned& value;};
export struct ParameterPicker {
  SAFETY_RETURNS_BORROW(value) const OperatorView& operator()(const OperatorView& value)const{return value;}
};
export SAFETY_RETURNS_BORROW(value) const OperatorView& relay_operator(const OperatorView& value){ParameterPicker picker;return picker(value);}
export struct ReceiverPicker {
  OperatorView view;
  SAFETY_RETURNS_THIS const OperatorView& operator()()const{return view;}
};
export SAFETY_RETURNS_BORROW(value) const OperatorView& relay_receiver(const ReceiverPicker& value){return value();}
export struct GoodDrop {static void finish(){}};
export struct BadDrop {unsafe_fn static void finish(){}};
export template<class T> struct DeferredDrop {~DeferredDrop(){T::finish();}};
export unsigned read(const unsigned& owner){return owner;}
export SAFETY_RETURNS_LIFETIME(a) const unsigned& reborrow(SAFETY_LIFETIME(a) const unsigned&owner){return owner;}
export struct Guard {
  const std2::atomic<unsigned>& count;
  SAFETY_STORES_LIFETIME(region) explicit Guard(SAFETY_LIFETIME(region) const std2::atomic<unsigned>&c):count(c){}
  ~Guard()noexcept{count.fetch_add(1u);}
};
export struct Partial {
  Guard first;
  SAFETY_STORES_BORROW(c) Partial(const std2::atomic<unsigned>&c,bool fail):first(c){if(fail)throw 7u;}
};
export struct SAFETY_PINNED PinnedPartial {
  Guard first;unsigned value;const unsigned& self;
  SAFETY_STORES_SELF SAFETY_STORES_BORROW(c)
  PinnedPartial(const std2::atomic<unsigned>&c,bool fail):first(c),value(9u),self(value){if(fail)throw 8u;}
  PinnedPartial(const PinnedPartial&)=delete;PinnedPartial(PinnedPartial&&)=delete;
};
export struct CopyOwner {std2::atomic<unsigned> drops;unsigned payload=42u;};
export struct CopyView {
  const std2::atomic<unsigned>& drops; const unsigned& value;unsigned generation;
  SAFETY_STORES_BORROW(owner) explicit CopyView(const CopyOwner&owner):drops(owner.drops),value(owner.payload),generation(0u){}
  SAFETY_STORES_BORROW(other) CopyView(const CopyView&other):drops(other.drops),value(other.value),generation(other.generation+1u){if(generation==2u)throw 9u;}
  ~CopyView()noexcept{drops.fetch_add(1u);}
};
export template<class T> void nested(const std2::atomic<unsigned>& c){
  Guard outer(c);
  T inner(c,true);
}
''')
        compile(checked+['--precompile',str(api),'-o',str(tmp/'lifetimes.pcm')])
        client=tmp/'lifetime_client.cppm'
        prefix='export module lifetime_client; import lifetimes; import safety_atomic; import safety_ownership; import safety_borrows; import safety_lifetimes;\n'
        client.write_text(prefix+'''void consume_deferred(DeferredDrop<GoodDrop> value){}
export unsigned run(){
  unsigned x=42u,y=17u;
  { OperatorView view{x};const auto& loan=relay_operator(view);if(loan.value!=42u)return 16u; }
  { ReceiverPicker picker{{x}};const auto& loan=relay_receiver(picker);if(loan.value!=42u)return 17u; }

  {const unsigned&r=relay(true,x,y);if(r!=42u)return 1u;}
  if(std2::with_borrow<read>(x)!=42u)return 14u;
  {const auto&r=std2::map_borrow<reborrow>(x);if(r!=42u)return 15u;}
  x=3u;y=4u;
  if(relay(false,x,y)!=4u)return 2u;
  std2::atomic<unsigned> count;
  try{nested<Partial>(count);return 3u;}catch(unsigned n){if(n!=7u)return 4u;}
  if(count.load()!=2u)return 5u;
  {Partial complete(count,false);}
  if(count.load()!=3u)return 6u;
  try{std2::pin_region<PinnedPartial,std2::atomic<unsigned>> pinned(count,true);return 7u;}
  catch(unsigned n){if(n!=8u)return 8u;}
  if(count.load()!=4u)return 9u;
  CopyOwner owner;
  {
    std2::borrowed_vector<CopyView,CopyOwner> values(owner);
    {CopyView view(owner);values.push_back(view);}
    try{values.reserve(32u);return 10u;}catch(unsigned n){if(n!=9u)return 11u;}
    if(values.size()!=1u)return 12u;
  }
  if(owner.drops.load()!=2u)return 13u;
  return 0u;
}''')
        compile(checked+['--precompile',str(client),'-o',str(tmp/'lifetime_client.pcm')])
        objects=[]
        for name in ['safety','safety_atomic','safety_ownership','safety_borrows','safety_lifetimes','lifetimes','lifetime_client']:
            obj=tmp/(name+'.o');objects.append(str(obj))
            compile([clang]+flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)])
        main=tmp/'main.cpp';main.write_text('import lifetime_client; int main(){return int(run());}')
        binary=tmp/'run';compile([clang]+flags+[str(main)]+objects+['-o',str(binary)])
        subprocess.run([str(binary)],check=True,timeout=30)
        for body,needle in [
          ('unsigned f(){unsigned x=1u;OperatorView view{x};const auto&r=relay_operator(view);x=2u;return r.value;}','borrow'),
          ('unsigned f(){unsigned x=1u;ReceiverPicker picker{{x}};const auto&r=relay_receiver(picker);x=2u;return r.value;}','borrow'),
          ('__attribute__((annotate("safecpp.borrow.from:x"))) const OperatorView& bad(const unsigned&x){OperatorView view{x};return relay_operator(view);}','lifetime'),
          ('unsigned f(){const auto&r=relay_operator(OperatorView{1u});return r.value;}','provenance'),
          ('void bad(DeferredDrop<BadDrop> value){}','unsafe'),
          ('unsigned f(){unsigned n=1u;const auto&r=std2::with_borrow<reborrow>(n);return r;}', 'borrow result'),
          ('unsigned f(){unsigned n=1u;const auto&r=std2::map_borrow<reborrow>(n);n=2u;return r;}', 'borrow'),
          ('__attribute__((annotate("safecpp.borrow.lifetime:missing"))) const unsigned& bad(const unsigned&a){return a;}', 'invalid borrow'),
          ('unsigned bad(__attribute__((annotate("safecpp.lifetime:a"))) unsigned a){return a;}', 'borrow-carrying'),
          ('__attribute__((annotate("safecpp.borrow.from:a"))) const unsigned& redecl(const unsigned&a,const unsigned&b); __attribute__((annotate("safecpp.borrow.from:b"))) const unsigned& redecl(const unsigned&a,const unsigned&b){return b;}', 'error:'),
          ('unsigned f(){unsigned a=1u,b=2u;const auto&r=relay(true,a,b);b=3u;return r;}','borrow'),
          ('unsigned f(){unsigned a=1u;const auto&r=relay(false,a,2u);return r;}','provenance'),
          ('unsigned f(){unsigned a=1u;return wrong(a);}','lifetime'),
          ('unsigned f(){std2::atomic<unsigned> c;try{Guard g(c);throw 1u;}catch(unsigned){auto moved=std2::move(c);return c.load();}}','moved'),
        ]:
            client.write_text(prefix+body)
            compile(checked+['-fsyntax-only',str(client)],False,needle)
print('Cross-PCM generic intersection lifetimes, nested/partial exception cleanup and 28 refusals passed at O0/O2 under ASan/UBSan')
