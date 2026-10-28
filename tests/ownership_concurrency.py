#!/usr/bin/env python3
"""Pinned heap ownership and sequentially consistent integer atomics."""
import os, pathlib, subprocess, sys, tempfile
clang, plugin, root = sys.argv[1:]
sanitizer = os.environ.get('MODULE_SAFETY_THREAD_SANITIZER', 'address,undefined')
with tempfile.TemporaryDirectory(prefix='safecpp-ownership-') as directory:
    tmp = pathlib.Path(directory)
    flags = ['-std=c++20', '-O2', '-fsanitize='+sanitizer, '-fno-sanitize-recover=all', '-fprebuilt-module-path='+str(tmp), '-I'+root+'/include']
    checked = [clang]+flags+['-Xclang','-load','-Xclang',plugin,'-Xclang','-add-plugin','-Xclang','module-safety','-Xclang','-plugin-arg-module-safety','-Xclang','safe']
    def compile(args, ok=True, needle=''):
        result = subprocess.run(args, text=True, capture_output=True)
        assert (result.returncode == 0) == ok and needle in result.stderr, result.stderr
        assert 'PLEASE submit' not in result.stderr, result.stderr
    modules = [('safety','safety.cppm'),('safety_threads','threads.cppm'),('safety_atomic','atomic.cppm'),('safety_ownership','ownership.cppm')]
    for name, file in modules:
        compile(checked+['--precompile',root+'/runtime/'+file,'-o',str(tmp/(name+'.pcm'))])
    prefix = '''module;
#include "module_safety.h"
export module ownership_checks;
import safety; import safety_threads; import safety_atomic; import safety_ownership;
struct SAFETY_PINNED Self {
  unsigned value; const unsigned& reference;
  SAFETY_STORES_SELF explicit Self(unsigned n):value(n),reference(value){if(n==99u)throw n;}
  Self(const Self&)=delete; Self(Self&&)=delete;
  unsigned read()const {return reference;}
};
struct SAFETY_PINNED Regional {
  unsigned& external; unsigned local; const unsigned& self;
  SAFETY_STORES_SELF SAFETY_STORES_BORROW(owner)
  Regional(unsigned& owner,unsigned n):external(owner),local(n),self(local){}
  Regional(const Regional&)=delete; Regional(Regional&&)=delete;
  unsigned read()const{return self;}
  void update(){external=self;}
};
struct Payload {unsigned value;};
struct Holder {Payload value;explicit Holder(Payload p):value(std2::move(p)){} };
SAFETY_RETURNS_BORROW(s) const unsigned& projected(const Self&s){return s.reference;}
struct Message {
  std2::atomic<unsigned> payload;
  std2::atomic<unsigned> ready;
};
void publish(const Message& m){
  m.payload.store<std2::memory_order::relaxed>(42u);
  m.ready.store<std2::memory_order::release>(1u);m.ready.notify_all();
}
unsigned receive(const Message&m){
  m.ready.wait<std2::memory_order::acquire>(0u);
  return m.payload.load<std2::memory_order::relaxed>();
}
void increment(const std2::atomic<unsigned>& value) {
  for(unsigned n=0u;n<10000u;++n) value.fetch_add(1u);
}
'''
    source=tmp/'ownership_checks.cppm'
    order_matrix = 'unsigned order_matrix(){'
    for success in range(5):
        for failure in (0,1,4):
            order_matrix += ('{std2::atomic<unsigned> value(1u);'
                f'auto result=value.compare_exchange<{success}u,{failure}u>(1u,2u);'
                'if(!result.exchanged || result.previous!=1u)return 1u;'
                f'auto weak=value.compare_exchange_weak<{success}u,{failure}u>(0u,3u);'
                'if(weak.exchanged || weak.previous!=2u)return 2u;}')
    order_matrix += 'return 0u;}'
    source.write_text(prefix+order_matrix+'''unsigned read_owned(std2::pin_box<Self> value){return value.get().read();}
export unsigned run(){
  if(order_matrix()!=0u)return 27u;
  auto holder=std2::pin_box<Holder>::make(Payload{19u});
  auto extracted=holder.take();
  if(extracted.value.value!=19u)return 23u;
  auto first=std2::pin_box<Self>::make(1u);
  first.reset(42u);
  try{first.reset(99u);return 28u;}catch(unsigned n){if(n!=99u)return 29u;}
  if(first.get().read()!=42u)return 30u;
  if(first.project<projected>()!=42u)return 24u;
  { const Self& value=first.get(); if(value.read()!=42u) return 1u; }
  { auto borrowed=first.as_ref(); auto copied=borrowed; if(copied.get().read()!=42u)return 25u; }
  Self stack(8u);
  {std2::pin_ref<const Self> borrowed(stack); if(borrowed.project<projected>()!=8u)return 26u;}
  auto second=std2::move(first);
  if(second.get().read()!=42u) return 2u;
  if(std2::run_thread<read_owned>(std2::move(second))!=42u) return 3u;
  unsigned owner=0u;
  {
    std2::pin_region<Regional,unsigned> pinned(owner,42u);
    if(pinned.get().read()!=42u)return 15u;
    auto transferred=std2::move(pinned);
    transferred.get_mut().update();
  }
  if(owner!=42u)return 16u;
  std2::atomic<unsigned> counter;
  std2::parallel_share<increment,increment>(counter);
  if(counter.load()!=20000u) return 4u;
  auto no=counter.compare_exchange(1u,9u);
  if(no.exchanged || no.previous!=20000u) return 5u;
  auto yes=counter.compare_exchange(20000u,9u);
  if(!yes.exchanged || yes.previous!=20000u) return 6u;
  if(counter.exchange(7u)!=9u || counter.load()!=7u) return 7u;
  std2::atomic<int> signed_counter(2147483647);
  if(signed_counter.fetch_add(1)!=2147483647 || signed_counter.load()!=(-2147483647-1)) return 8u;
  signed_counter.fetch_sub(1);
  if(signed_counter.load()!=2147483647) return 9u;
  counter.store<std2::memory_order::relaxed>(3u);
  if(counter.fetch_and<std2::memory_order::acquire>(1u)!=3u) return 10u;
  if(counter.fetch_or<std2::memory_order::release>(4u)!=1u) return 11u;
  if(counter.fetch_xor<std2::memory_order::acq_rel>(2u)!=5u) return 12u;
  counter.store<std2::memory_order::release>(8u);
  counter.wait<std2::memory_order::acquire>(7u);
  counter.notify_one();counter.notify_all();
  auto weak=counter.compare_exchange_weak<std2::memory_order::acq_rel>(8u,9u);
  if(weak.previous!=8u) return 13u;
  std2::atomic_fence<std2::memory_order::acquire>();
  if(counter.load<std2::memory_order::relaxed>()!=(weak.exchanged?9u:8u))return 14u;
  Message message;
  if(std2::parallel_share<publish,receive>(message)!=42u)return 17u;
  unsigned pointee=3u;
  std2::atomic_ptr<unsigned> pointer(&pointee);
  if(pointer.load()!=&pointee)return 18u;
  if(pointer.fetch_add(0)!=&pointee || pointer.fetch_sub(0)!=&pointee)return 19u;
  if(!pointer.compare_exchange(&pointee,nullptr).exchanged)return 20u;
  if(pointer.load()!=nullptr)return 21u;
  std2::atomic<bool> bit(false);
  if(bit.fetch_or(true) || !bit.fetch_and(true) || !bit.fetch_xor(true) || bit.load())return 22u;
  return 0u;
}''')
    compile(checked+['--precompile',str(source),'-o',str(tmp/'ownership_checks.pcm')])
    objects=[]
    for name in [n for n,_ in modules]+['ownership_checks']:
        obj=tmp/(name+'.o');objects.append(str(obj))
        compile([clang]+flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)])
    main=tmp/'main.cpp';main.write_text('import ownership_checks; int main(){return int(run());}')
    binary=tmp/'checks';compile([clang]+flags+[str(main)]+objects+['-o',str(binary)])
    result=subprocess.run([str(binary)],text=True,capture_output=True,timeout=60)
    assert result.returncode==0,(result.returncode,result.stderr)
    cases = [
      ('void f(){auto box=std2::pin_box<Self>::make(1u);const Self&r=box.get();auto other=std2::move(box);r.read();}', 'borrow'),
      ('void f(){auto box=std2::pin_box<Self>::make(1u);auto other=std2::move(box);box.get();}', 'moved'),
      ('struct Bad { unsafe_fn Bad(unsigned){} }; void f(){auto b=std2::pin_box<Bad>::make(1u);}', 'unsafe'),
      ('struct Borrow { const unsigned& value; explicit Borrow(unsigned n):value(n){} }; void f(){auto b=std2::pin_box<Borrow>::make(1u);}', 'self-only pinned'),
      ('struct BadDrop { ~BadDrop()noexcept(false){throw 1u;} }; void f(){auto b=std2::pin_box<BadDrop>::make();}', 'non-throwing destructor'),
      ('void f(){std2::atomic<unsigned __int128> value;}', 'up to 64 bits'),
    ]
    cases += [
      ('struct Input{const unsigned& ref;};struct ResetValue{unsigned value;ResetValue(unsigned n):value(n){}ResetValue(Input x):value(x.ref){}};void f(){unsigned n=1u;auto box=std2::pin_box<ResetValue>::make(1u);box.reset(Input{n});}', 'replacement arguments'),
      ('void f(){auto box=std2::pin_box<Self>::make(1u);const auto&r=box.get();box.reset(2u);r.read();}', 'borrow'),
      ('unsigned inspect(const Holder& h,Holder value){return h.value.value;} unsigned f(){auto box=std2::pin_box<Holder>::make(Payload{1u});return inspect(box.get(),box.take());}', 'temporary borrow'),
      ('struct View {const Holder& ref;Holder value;};void f(){auto box=std2::pin_box<Holder>::make(Payload{1u});View v{box.get(),box.take()};}', 'temporary borrow'),
      ('struct View {const Holder& ref;Holder value;SAFETY_STORES_BORROW(h) View(const Holder& h,Holder v):ref(h),value(std2::move(v)){} };void f(){auto box=std2::pin_box<Holder>::make(Payload{1u});View v(box.get(),box.take());}', 'temporary borrow'),
      ('struct SAFETY_SYNC_TYPE BadSync {std2::pin_region<Regional,unsigned> value;};', 'Sync'),
      ('struct Node {std2::pin_box<Node> next;unsigned* raw;};struct SAFETY_SEND_TYPE BadSend {std2::pin_box<Node> next;};', 'Send'),
      ('void f(){std2::pin_ref<const unsigned> p(1u);p.get();}', 'provenance'),
      ('void f(){Self stack(1u);std2::pin_ref<Self> p(stack);auto q=p;}', 'error:'),
      ('void f(){auto box=std2::pin_box<Self>::make(1u);auto borrow=box.as_ref();auto moved=std2::move(box);borrow.get();}', 'borrow'),
      ('unsigned f(){unsigned n=1u;std2::atomic_ptr<unsigned> p(&n);return *p.load();}', 'raw pointer dereference'),
      ('void f(){auto box=std2::pin_box<Self>::make(1u);auto value=box.take();}', 'non-throwing move'),
      ('void f(){auto box=std2::pin_box<Self>::make(1u);const auto&r=box.project<projected>();auto moved=std2::move(box);unsigned v=r;}', 'borrow'),
      ('void f(){unsigned owner=0u;std2::pin_region<Regional,unsigned> p(owner,1u);owner=2u;p.get();}', 'borrow'),
      ('void f(){std2::pin_region<Regional,unsigned> p(1u,1u);}', 'error:'),
      ('void f(){unsigned owner=0u;std2::pin_region<Regional,unsigned> p(owner,1u);auto&r=p.get();auto q=std2::move(p);r.read();}', 'borrow'),
      ('struct Wrong{const unsigned& ref; SAFETY_STORES_BORROW(n) Wrong(unsigned& owner,const unsigned& n):ref(n){}};void f(){unsigned o=0u;std2::pin_region<Wrong,unsigned> p(o,1u);}', 'regional construction'),
    ]
    for method, order, arguments, needle in [
      ('load','release','', 'invalid atomic load order'),
      ('store','acquire','1u', 'invalid atomic store order'),
      ('wait','acq_rel','0u', 'invalid atomic wait order'),
      ('compare_exchange','seq_cst, std2::memory_order::release','0u,1u', 'invalid atomic CAS failure order'),
      ('compare_exchange_weak','relaxed, std2::memory_order::acq_rel','0u,1u', 'invalid atomic CAS failure order'),
    ]:
        cases.append((f'void f(){{std2::atomic<unsigned> a;a.{method}<std2::memory_order::{order}>({arguments});}}', needle))
    for method,arguments,allowed in [('load','',{0,1,4}),('store','1u',{0,2,4}),('wait','0u',{0,1,4}),('exchange','1u',set(range(5)))]:
        for order in set(range(7))-allowed:
            cases.append((f'void f(){{std2::atomic<unsigned> a;a.{method}<{order}u>({arguments});}}', 'invalid atomic'))
    cases.append(('void f(){std2::atomic<unsigned> a;a.exchange<99u>(1u);}', 'invalid atomic memory order'))
    cases.append(('struct Node {std2::pin_box<Node> next;}; struct SAFETY_SEND_TYPE Owned {std2::pin_box<Node> next;};', ''))
    # Recursive type is a positive compile case, not a refusal.
    recursive, _ = cases.pop()
    source.write_text(prefix+recursive+'unsigned read_owned(std2::pin_box<Self> value){return value.get().read();}')
    compile(checked+['-fsyntax-only',str(source)])
    for body, needle in cases:
        source.write_text(prefix+body)
        compile(checked+['-fsyntax-only',str(source)],False,needle)
print(f'Pinned heap factories, handle transfer, Send, atomic parallel updates/CAS/wraparound and {len(cases)} refusals passed under {sanitizer}')
