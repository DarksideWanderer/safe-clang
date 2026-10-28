#!/usr/bin/env python3
"""Validate local T+ aggregate projection, storage and lifetime rejection."""
import json
import pathlib
import subprocess
import sys
import tempfile
root = pathlib.Path(__file__).resolve().parent.parent
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'llvm-build/bin/clang'
with tempfile.TemporaryDirectory(prefix='circle-binders-') as directory:
    tmp = pathlib.Path(directory)
    policy=tmp/'policy.json'
    policy.write_text(json.dumps({'version':1,'modules':{'binder':'safe','consumer':'safe'}}))
    flags=['-std=c++20','-fcircle-safety','-fcircle-borrow-values',
           '-fmodule-safety-policy='+str(policy),
           '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    src=tmp/'binder.cppm'
    api='''export module binder;
export template<class T+> struct Holder { T value; };
export template<typename... Ts+> struct Pack { Ts ...m; };
export template<class T+> struct Pair { T first; T second; };
export template<class A+, class B+> struct Pair2 { A first; B second; };
export template<class A+, class B+, class C+> struct Mixed3 {
  Pair2<A,B> pair;
  C tail;
};
export template<class Tag, class T+> struct Tagged { Tag tag; T value; };
export template<unsigned N, class T+> struct SizedTagged {
  unsigned tag;
  T value;
};
export struct View/(a) { const unsigned^/a value; };
export template<> struct Holder<View> { View value; };
export Holder<View>/a wrap_view/(a)(const unsigned^/a input) safe {
  return Holder<View>{View{input}};
}
export Holder<View>/a wrap_explicit/(a)(const unsigned^/a input) safe {
  return Holder<View>{View{input}};
}
export unsigned hoisted_explicit/(a)(const unsigned^/a input) safe {
  Holder<View>/a holder = wrap_explicit(input);
  return *holder.value.value;
}
export template<class A+, class B+> struct PairHolder { A first; B second; };
export PairHolder<View,View>/a/b wrap_pair/(a,b)(const unsigned^/a left,const unsigned^/b right) safe {
  return PairHolder<View,View>{View{left},View{right}};
}
export unsigned hoisted_pair/(a,b)(const unsigned^/a left,const unsigned^/b right) safe {
  PairHolder<View,View>/a/b pair = wrap_pair(left,right);
  return *pair.first.value + *pair.second.value;
}
export Holder<Pair2<View,View>>/a/b wrap_nested_pair/(a,b)(const unsigned^/a left,const unsigned^/b right) safe {
  return Holder<Pair2<View,View>>{Pair2<View,View>{View{left},View{right}}};
}
export unsigned hoisted_nested_pair/(a,b)(const unsigned^/a left,const unsigned^/b right) safe {
  Holder<Pair2<View,View>>/a/b holder = wrap_nested_pair(left,right);
  return *holder.value.first.value + *holder.value.second.value;
}
export Holder<Holder<View>>/a wrap_deep_one/(a)(const unsigned^/a input) safe {
  return Holder<Holder<View>>{Holder<View>{View{input}}};
}
export Holder<Holder<Pair2<View,View>>>/a/b wrap_deep_pair/(a,b)(
    const unsigned^/a left,const unsigned^/b right) safe {
  return Holder<Holder<Pair2<View,View>>>{
      Holder<Pair2<View,View>>{Pair2<View,View>{View{left},View{right}}}};
}
export Mixed3<View,View,View>/a/b/c wrap_mixed/(a,b,c)(
    const unsigned^/a first,const unsigned^/b second,const unsigned^/c third) safe {
  return Mixed3<View,View,View>{
      Pair2<View,View>{View{first},View{second}},View{third}};
}
export Pack<View,View>/a/b wrap_pack/(a,b)(
    const unsigned^/a left,const unsigned^/b right) safe {
  return Pack<View,View>{View{left},View{right}};
}
export Pack<View,View,View>/a/b/c wrap_pack3/(a,b,c)(
    const unsigned^/a left,const unsigned^/b right,const unsigned^/c third) safe {
  return Pack<View,View,View>{View{left},View{right},View{third}};
}
export Pack<Pair2<View,View>,View>/a/b/c wrap_pack_nested/(a,b,c)(
    const unsigned^/a left,const unsigned^/b right,const unsigned^/c third) safe {
  return Pack<Pair2<View,View>,View>{
      Pair2<View,View>{View{left},View{right}},View{third}};
}
export Tagged<unsigned,View>/a wrap_tagged/(a)(const unsigned^/a input) safe {
  return Tagged<unsigned,View>{7u,View{input}};
}
export SizedTagged<3u,View>/a wrap_sized/(a)(const unsigned^/a input) safe {
  return SizedTagged<3u,View>{9u,View{input}};
}
export unsigned deep/(a,b,c)(const unsigned^/a left,const unsigned^/b right,
                             const unsigned^/c third) safe {
  Holder<Holder<View>>/a one = wrap_deep_one(left);
  Holder<Holder<Pair2<View,View>>>/a/b two = wrap_deep_pair(left,right);
  Mixed3<View,View,View>/a/b/c three = wrap_mixed(left,right,third);
  Pack<View,View>/a/b four = wrap_pack(left,right);
  Pack<View,View,View>/a/b/c five = wrap_pack3(left,right,third);
  Pack<Pair2<View,View>,View>/a/b/c eight =
      wrap_pack_nested(left,right,third);
  Tagged<unsigned,View>/a six = wrap_tagged(left);
  SizedTagged<3u,View>/a seven = wrap_sized(left);
  return *one.value.value.value + *two.value.value.first.value +
         *two.value.value.second.value + *three.pair.first.value +
         *three.pair.second.value + *three.tail.value +
         *six.value.value + *seven.value.value;
}
export Holder<const unsigned^>/a wrap_borrow/(a)(const unsigned^/a input) safe {
  return Holder<const unsigned^>{input};
}
export unsigned hoisted/(a)(const unsigned^/a input) safe {
  Holder<View>/a nested = wrap_view(input);
  Holder<const unsigned^>/a direct = wrap_borrow(input);
  return *nested.value.value + *direct.value;
}
export unsigned run() safe {
 unsigned before=1u,after=2u;
 Holder<const unsigned^> rebound{^const before};
 rebound.value=^const after;
 before=7u;
 if (*rebound.value!=2u) return 0u;
 Holder<const unsigned^> destination{^const before};
 Holder<const unsigned^> source{^const after};
 destination=source;
 before=8u;
 if (*destination.value!=2u) return 0u;
 unsigned a=1u,b=2u;
 Pair<unsigned^> parts{^a,^b};
 auto taken=rel parts.first;
 *taken=5u;
 *parts.second=6u;
 if (*taken!=5u || *parts.second!=6u) return 0u;
 unsigned left=3u,right=4u;
 Holder<unsigned^> move_source{^left};
 Holder<unsigned^> move_target{^right};
 move_target=rel move_source;
 *move_target.value=9u;
 right=10u;
 if (*move_target.value!=9u || right!=10u) return 0u;
 unsigned branch_a=1u,branch_b=2u;
 Holder<const unsigned^> branch{^const branch_a};
 for (unsigned i=0u;i<2u;++i) branch.value=^const branch_b;
 if (*branch.value!=2u) return 0u;
 Holder<unsigned> plain{9u};
 unsigned n=2u;
 Holder<const unsigned^> shared{^const n};
 auto copied=shared;
 Holder<Holder<const unsigned^>> nested{shared};
 unsigned sum=*shared.value+*copied.value+*nested.value.value;
 unsigned x=3u;
 Holder<unsigned^> unique{^x};
 auto moved=rel unique;
 *moved.value=5u;
 unsigned hoisted_value=4u;
 if (hoisted(^const hoisted_value) != 8u) return 0u;
 if (hoisted_explicit(^const hoisted_value) != 4u) return 0u;
 unsigned pair_left=6u,pair_right=7u;
 if (hoisted_pair(^const pair_left,^const pair_right) != 13u) return 0u;
 if (hoisted_nested_pair(^const pair_left,^const pair_right) != 13u) return 0u;
 unsigned deep_left=3u,deep_right=4u,deep_third=5u;
 if (deep(^const deep_left,^const deep_right,^const deep_third) != 28u) return 0u;
 return plain.value+sum+*moved.value;
}
'''
    src.write_text(api)
    def invoke(args, success=True):
        r=subprocess.run([str(clang)]+args,text=True,capture_output=True)
        if (r.returncode==0)!=success or 'PLEASE submit' in r.stderr:
            raise AssertionError(r.stderr+'\n'+src.read_text())
        return r
    dump=invoke(flags+['-fsyntax-only','-Xclang','-ast-dump',str(src)]).stdout
    if dump.count('safecpp.native.lifetime_binder')!=12:
        raise AssertionError('lifetime binder declaration metadata lost')
    if 'Implicit "safecpp.native.lifetime_projection"' not in dump:
        raise AssertionError('instantiated projection metadata lost')
    for optimization in ('-O0','-O2'):
        src.write_text(api)
        checked=flags+[optimization,'-fsanitize=address,undefined','-fno-sanitize-recover=all']
        pcm=tmp/'binder.pcm';obj=tmp/'binder.o'
        invoke(checked+['--precompile',str(src),'-o',str(pcm)])
        invoke(checked+['-c',str(pcm),'-o',str(obj)])
        client=tmp/'consumer.cppm'
        client.write_text('''export module consumer;import binder;
export unsigned check() safe {
 unsigned n=7u;Holder<const unsigned^> h{^const n};auto copied=h;
 return run()+*copied.value;
}
''')
        client_pcm=tmp/'consumer.pcm';client_obj=tmp/'consumer.o'
        invoke(checked+['-fprebuilt-module-path='+str(tmp),'--precompile',str(client),'-o',str(client_pcm)])
        invoke(checked+['-fprebuilt-module-path='+str(tmp),'-c',str(client_pcm),'-o',str(client_obj)])
        main=tmp/'main.cpp';main.write_text('import consumer;int main(){return check()==27u?0:1;}')
        executable=tmp/'run'
        invoke(['--driver-mode=g++','-std=c++20',optimization,
                '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22',
                '-fsanitize=address,undefined','-fno-sanitize-recover=all',
                '-fprebuilt-module-path='+str(tmp),str(main),str(obj),str(client_obj),'-o',str(executable)])
        subprocess.run([str(executable)],check=True,timeout=30)
    prefix='export module binder;struct View/(a){const unsigned^/a value;};template<class T+> struct Holder { T value; };template<class... Ts+>struct Pack{Ts ...m;};template<class A+,class B+>struct PairHolder{A first;B second;};template<class A+,class B+>struct Pair2{A first;B second;};template<class A+,class B+,class C+>struct Mixed3{Pair2<A,B> pair;C tail;};Holder<View>/a wrap_view/(a)(const unsigned^/a input)safe{return Holder<View>{View{input}};}\n'
    negatives=[
      ('void f()safe{unsigned n=1u;Holder<const unsigned^> h{^const n};n=2u;unsigned x=*h.value;}', 'live borrow'),
      ('void f()safe{unsigned n=1u;Holder<unsigned^> h{^n};auto copied=h;*copied.value=2u;}', 'cannot initialize'),
      ('void f()safe{unsigned n=1u;Holder<unsigned^> h{^n};auto moved=rel h;*h.value=2u;}', 'relocated'),
      ('void f()safe{Holder<const unsigned^> h{};}', 'initialization'),
      ('void f()safe{unsigned n=1u;Holder<const unsigned^> h{^const n};{unsigned inner=2u;h.value=^const inner;}unsigned x=*h.value;}', 'owner'),
      ('void f()safe{unsigned n=1u;Holder<const unsigned^> h{^const n};{unsigned inner=2u;h=Holder<const unsigned^>{^const inner};}unsigned x=*h.value;}', 'owner'),
      ('const unsigned^/a f/(a)(const unsigned^/a p) safe {unsigned local=1u;Holder<const unsigned^> h{^const local};return h.value;}', 'lifetime source'),
      ('void f()safe{unsigned n=1u;Holder<unsigned^> first{^n};Holder<unsigned^> second{^n};*first.value=2u;*second.value=3u;}', 'borrow'),
      ('void f()safe{Holder<Holder<const unsigned^>> h{};}', 'initialization'),
      ('template<class T+>struct Pair{T first;T second;};void f()safe{unsigned a=1u,b=2u;Pair<unsigned^> p{^a,^b};auto x=rel p.first;b=3u;*p.second=4u;}', 'live borrow'),
      ('const Holder<const unsigned^>^/a bad/(a)(const unsigned^/a p)safe{Holder<const unsigned^> local{p};return ^const local;}', 'lifetime source'),
      ('void f()safe{unsigned n=1u;Holder<const unsigned^> outer{^const n};const Holder<const unsigned^>^ p=^const outer;{Holder<const unsigned^> inner{^const n};p=^const inner;}unsigned x=*p->value;}', 'owner'),
      ('void f(bool choose)safe{unsigned a=1u,b=2u;Holder<const unsigned^> h{^const a};if(choose)h.value=^const b;b=3u;unsigned x=*h.value;}', 'live borrow'),
      ('template<class T+>struct Pair{T first;T second;};void f()safe{unsigned a=1u,b=2u;Pair<unsigned^> h{^a,^b};h.first=^b;*h.second=3u;}', 'exclusive'),
      ('void f()safe{unsigned a=1u,b=2u;Holder<unsigned^> src{^a},dst{^b};dst=rel src;*src.value=3u;}', 'relocated'),
      ('template<class T+>struct Pair{T first;T second;};void f()safe{unsigned a=1u,b=2u;Pair<unsigned^> h{^a,^b};auto moved=rel h.first;*h.first=3u;}', 'relocated'),
      ('void f()safe{unsigned a=1u,b=2u;Holder<unsigned^> h{^a};auto moved=rel h.value;h.value=^b;}', 'replacement'),
      ('Holder<View>/a bad/(a,b)(const unsigned^/b input) safe {return Holder<View>{View{input}};}', 'lifetime'),
      ('unsigned bad() safe {unsigned value=1u;Holder<View>/a h=wrap_view(^const value);value=2u;return *h.value.value;}', 'borrow'),
      ('Holder<View>/a leak/(a)() safe {unsigned local=1u;return wrap_view(^const local);}', 'lifetime'),
      ('void f() safe {Holder<unsigned>/a h{};}', 'class lifetime argument count mismatch'),
      ('void f() safe {Holder<View>/a/b h{};}', 'class lifetime argument count mismatch'),
      ('PairHolder<View,View>/a/b bad/(a,b)(const unsigned^/b left,const unsigned^/a right) safe {return PairHolder<View,View>{View{left},View{right}};}', 'does not borrow from the parameter'),
      ('void f() safe {PairHolder<View,View>/a h{};}', 'class lifetime argument count mismatch'),
      ('Holder<View>/a bad_explicit/(a,b)(const unsigned^/b input) safe {return Holder<View>{View{input}};}', 'generative return lifetime cannot expose'),
      ('template<class Q+> Holder<Q>/a bad/(a)(Q value) safe {return Holder<Q>{value};} unsigned f() safe {return bad(1u).value;}', 'class lifetime argument count mismatch'),
      ('Holder<Pair2<View,View>>/a/b bad_nested/(a,b)(const unsigned^/b left,const unsigned^/a right) safe {return Holder<Pair2<View,View>>{Pair2<View,View>{View{left},View{right}}};}', 'does not borrow from the parameter'),
      ('Holder<Holder<Pair2<View,View>>>/a/b bad_deep/(a,b)(const unsigned^/b left,const unsigned^/a right) safe {return Holder<Holder<Pair2<View,View>>>{Holder<Pair2<View,View>>{Pair2<View,View>{View{left},View{right}}}};}', 'does not borrow from the parameter'),
      ('Mixed3<View,View,View>/a/b/c bad_mixed/(a,b,c)(const unsigned^/a first,const unsigned^/b second,const unsigned^/c third) safe {return Mixed3<View,View,View>{Pair2<View,View>{View{first},View{third}},View{second}};}', 'does not borrow from the parameter'),
      ('Pack<View,View>/a/b bad_pack/(a,b)(const unsigned^/b left,const unsigned^/a right) safe {return Pack<View,View>{View{left},View{right}};}', 'does not borrow from the parameter'),
      ('Pack<Pair2<View,View>,View>/a/b/c bad_pack_nested/(a,b,c)(const unsigned^/a first,const unsigned^/b second,const unsigned^/c third) safe {return Pack<Pair2<View,View>,View>{Pair2<View,View>{View{first},View{third}},View{second}};}', 'does not borrow from the parameter'),
      ('void f() safe {Pack<View,View>/a h{};}', 'class lifetime argument count mismatch'),
    ]
    for body,needle in negatives:
        src.write_text(prefix+body)
        r=invoke(flags+['-fsyntax-only',str(src)],False)
        if needle not in r.stderr:raise AssertionError(r.stderr)
    for declaration, diagnostic in (
      ('template<class T> struct Unbound{T value;};','class lifetime parameters'),
      ('template<class T> struct Unbound{[[clang::annotate("safecpp.native.lifetime_projection")]] T value;};',
       'compiler-owned safety metadata cannot be written in source'),
    ):
        src.write_text('export module binder;'+declaration+'void f()safe{unsigned n=1u;Unbound<const unsigned^> h{^const n};}')
        r=invoke(flags+['-fsyntax-only',str(src)],False)
        if diagnostic not in r.stderr:raise AssertionError(r.stderr)
    src.write_text('''export module binder;template<class T+>struct Holder{T value;};
template<class T>struct Unbound{T value;};
void f()safe{unsigned n=1u;Holder<const unsigned^> h{^const n};Unbound<Holder<const unsigned^>> outer{h};}
''')
    r=invoke(flags+['-fsyntax-only',str(src)],False)
    if 'class lifetime parameters' not in r.stderr:raise AssertionError(r.stderr)
print('T+/Ts+ declarations, per-field rebinding/relocation, default aggregate assignment, nested composite projection, named lifetime arguments, single- and multi-parameter hoisted class lifetimes, three-level nesting, mixed type/non-type parameters, parameter-pack hoisting, explicit specialization hoisting, cross-module instantiation and {} refusals passed at O0/O2 under ASan/UBSan; runtime-checked slice subranges are covered separately'.format(len(negatives)+2))
