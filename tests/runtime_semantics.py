#!/usr/bin/env python3
"""Independent runtime oracles for relocation, patterns, tuple and slice values."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety', '-fcircle-borrow-values',
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
API = r'''
unsigned relocations=0u,drops=0u,tuple_calls=0u,guards=0u;
struct Count {
 unsigned value;
 operator rel(Count) {unsafe {++relocations;}return Count{value+1u};}
 ~Count() safe {unsafe {++drops;}}
};
struct Aggregate {Count value;};
struct Defaulted {Count value;operator rel(Defaulted)=default;};
struct Asserted {Count value;operator rel(Asserted)=trivial;};
choice Owned {default empty, some(Count)};
unsigned run_relocation() safe {unsafe {
 relocations=0u;drops=0u;
 {Count a{3u};Count b=rel a;if(b.value!=4u)return 1u;}
 if(relocations!=1u || drops!=1u)return 2u;
 {Aggregate a{Count{5u}};auto b=rel a;if(b.value.value!=6u)return 3u;}
 if(relocations!=2u || drops!=2u)return 4u;
 {Defaulted a{Count{7u}};auto b=rel a;if(b.value.value!=8u)return 5u;}
 if(relocations!=3u || drops!=3u)return 6u;
 {Asserted a{Count{9u}};auto b=rel a;if(b.value.value!=9u)return 7u;}
 if(relocations!=3u || drops!=4u)return 8u;
 {Owned a=.some(Count{11u});auto b=rel a;
  unsigned n=match(b)->unsigned {.some(x)=>x.value;.empty=>0u;};
  if(n!=12u)return 9u;}
 if(relocations!=4u || drops!=5u)return 10u;
 return 0u;
}}
unsigned constructor_calls=0u,located_drops=0u;
struct Located {
 Count left;Count right;
 relocate(Located rhs) noexcept :left(relocate rhs.left),right(relocate rhs.right) {unsafe {++constructor_calls;}}
};
struct PartialLocated {
 Count left;Count right;
 relocate(PartialLocated rhs) noexcept :left(relocate rhs.left),right(Count{11u}) {unsafe {++constructor_calls;}}
};
struct WholeLocated {
 unsigned value;
 relocate(WholeLocated rhs) noexcept :value(rhs.value+1u) {unsafe {++constructor_calls;}}
 ~WholeLocated() safe {unsafe {++located_drops;}}
};
template<class T> struct LocatedTemplate {
 T value;
 relocate(LocatedTemplate rhs) noexcept :value(relocate rhs.value) {unsafe {++constructor_calls;}}
};
struct DefaultLocated {
 Count value;
 DefaultLocated(unsigned n):value{n}{}
 relocate(DefaultLocated rhs)=default;
};
struct ImplicitLocated {
 Count value;
 ImplicitLocated(unsigned n):value{n}{}
};
unsigned default_copies=0u,default_drops=0u;
struct DefaultLocatedDrop {
 unsigned value;
 DefaultLocatedDrop(unsigned n):value(n){}
 DefaultLocatedDrop(const DefaultLocatedDrop& rhs):value(rhs.value) {unsafe {++default_copies;}}
 ~DefaultLocatedDrop() safe {unsafe {++default_drops;}}
 relocate(DefaultLocatedDrop rhs)=default;
};
static_assert(__is_aggregate(Located));
static_assert(__is_constructible(Located));
static_assert(!__is_constructible(Located,Located&,unsigned));
struct ConstructorPinned {relocate(ConstructorPinned rhs)=delete;};
// A pinned type constrains this wrapper's type graph, not its physical storage.
struct PhantomPinned {
 ConstructorPinned __phantom_data;
 unsigned value;
 PhantomPinned(unsigned n):value(n){}
};
unsigned run_phantom() safe {
 PhantomPinned source(41u);auto target=relocate source;
 return target.value==41u?0u:1u;
}

struct OperatorPinned {operator rel(OperatorPinned)=delete;};
template<class T> concept CanRelocate=requires(T value){relocate value;};
static_assert(!CanRelocate<ConstructorPinned> && !CanRelocate<OperatorPinned>);
static_assert(CanRelocate<Located> && CanRelocate<LocatedTemplate<Count>>);
static_assert(__is_aggregate(LocatedTemplate<Count>));
unsigned run_constructors() safe {unsafe {
 relocations=0u;drops=0u;constructor_calls=0u;located_drops=0u;
 {Located a{Count{1u},Count{3u}};auto b=relocate a;if(b.left.value!=2u || b.right.value!=4u)return 1u;}
 if(relocations!=2u || drops!=2u)return 2u;
 {PartialLocated a{Count{5u},Count{7u}};auto b=relocate a;if(b.left.value!=6u || b.right.value!=11u)return 3u;}
 if(relocations!=3u || drops!=5u)return 4u;
 {WholeLocated a{17u};auto b=relocate a;if(b.value!=18u || located_drops!=1u)return 5u;}
 if(located_drops!=2u)return 6u;
 {LocatedTemplate<Count> a{Count{23u}};auto b=relocate a;if(b.value.value!=24u)return 7u;}
 if(relocations!=4u || drops!=6u || constructor_calls!=4u)return 8u;
 {DefaultLocated a{29u};auto b=relocate a;if(b.value.value!=30u)return 9u;}
 if(relocations!=5u || drops!=7u)return 10u;
 {DefaultLocatedDrop a{31u};auto b=relocate a;if(b.value!=31u || default_copies!=1u || default_drops!=1u)return 11u;}
 if(default_drops!=2u)return 12u;
 {ImplicitLocated a{37u};auto b=relocate a;if(b.value.value!=38u)return 13u;}
 if(relocations!=6u || drops!=8u)return 14u;
 return 0u;
}}
choice Number {default none, left(unsigned), right(unsigned)};
choice Product {default absent, pair((unsigned,unsigned))};
unsigned choice_or(Number value) safe {
 return match(value)->unsigned {.left(x)|.right(x)=>x;.none=>0u;};
}
unsigned guarded(Number value) safe {
 return match(value)->unsigned {
  .left(x)|.right(x) if (x>10u) => x;
  .left(x)|.right(x) => x+100u;
  .none=>0u;
 };
}
template<class T> unsigned dependent_guarded(T value) safe {
 return match(value)->unsigned {
  .left(x)|.right(x) if (x>10u) => x;
  .left(x)|.right(x) => x+100u;
  .none=>0u;
 };
}
unsigned product(Product value) safe {
 return match(value)->unsigned {.pair([a,b])=>a*10u+b;.absent=>0u;};
}
template<class T> unsigned destructure(T value) safe {
 return match(value)->unsigned {[a,b]=>a*10u+b;};
}
unsigned crossed((bool,bool) value) safe {
 return match(value)->unsigned {
  [true,true]=>1u;[true,false]=>2u;[false,true]=>3u;[false,false]=>4u;
 };
}
unsigned run_patterns() safe {
 if(choice_or(.left(7u))!=7u || choice_or(.right(9u))!=9u || choice_or(.none)!=0u)return 1u;
 if(guarded(.none)!=0u || guarded(.left(3u))!=103u || guarded(.right(17u))!=17u)return 2u;
 Number small=.left(3u),large=.right(17u);
 if(dependent_guarded(small)!=103u || dependent_guarded(large)!=17u)return 6u;
 Product p=.pair((2u,3u));if(product(rel p)!=23u)return 3u;
 if(destructure((4u,5u,))!=45u)return 4u;
 if(crossed((true,true))!=1u || crossed((true,false))!=2u ||
    crossed((false,true))!=3u || crossed((false,false))!=4u)return 5u;
 return 0u;
}
(unsigned,unsigned) tuple_factory() safe {unsafe {++tuple_calls;}return (7u,11u);}
unsigned add(unsigned a,unsigned b) safe {return a+b;}
unsigned consume_counts(Count a,Count b) safe {return a.value*10u+b.value;}
template<class... T> unsigned iterate(T... items) safe {
 unsigned result=0u;((result=result*10u+static_cast<unsigned>(items)),...);return result;
}
template<class T> unsigned tuple_pack(T seed) safe {
 return add(tuple_factory().[:] ...);
}
template<class T> unsigned tuple_iteration(T values) safe {
 return iterate(values.[:] ...);
}
unsigned run_tuples() safe {unsafe {
 tuple_calls=0u;if(add.(tuple_factory())!=18u || tuple_calls!=1u)return 1u;
 auto pair=(3u,5u,);if(add.(pair)!=8u)return 2u;
 tuple_calls=0u;if(tuple_pack(0u)!=18u || tuple_calls!=1u)return 3u;
 if(tuple_iteration((2u,3ul,true,))!=231u || tuple_iteration((,))!=0u)return 4u;
 relocations=0u;drops=0u;
 {auto owned=(Count{1u},Count{3u},);if(consume_counts.(rel owned)!=24u)return 5u;}
 if(relocations!=2u || drops!=2u)return 6u;
 return 0u;
}}
const unsigned^/a first_borrow/(a)(const unsigned^/a first,const unsigned^/a second) safe {return first;}
const unsigned^/a tuple_borrow/(a)(const unsigned^/a input) safe {
 auto pair=(input,input,);return first_borrow.(pair);
}
struct LocatedView/(a) {
 const unsigned^/a value;
 relocate(LocatedView rhs) noexcept :value(rhs.value) {}
};
template<class... T> auto packed_tuple(T... args) safe {return (rel args...,);}
template<class... T> struct NestedPacket {
 (unsigned,(T...,)) value;
 NestedPacket(unsigned tag,T... args):value((tag,(rel args...,),)) {}
};
unsigned run_tuple_packs() safe {
 auto empty=packed_tuple();auto pair=packed_tuple(43u,47u);
 NestedPacket<> zero(41u);NestedPacket<unsigned,unsigned> packet(53u,59u,61u);
 if(pair.0!=43u || pair.1!=47u || zero.value.0!=41u)return 1u;
 return packet.value.0==53u && (packet.value.1).0==59u && (packet.value.1).1==61u?0u:2u;
}
unsigned run_tuple_borrows() safe {
 unsigned value=19u;auto view=tuple_borrow(^const value);
 LocatedView source{view};auto target=relocate source;
 return *view==19u && *target.value==19u?0u:1u;
}
const [unsigned;dyn]^/a relay_slice/(a)(const [unsigned;dyn]^/a input) safe {return input;}
unsigned run_slices() safe {unsafe {
 unsigned values[3]={7u,11u,13u};
 auto slice=^const *__slice_pointer(&values[0],3ul);
 auto copy=cpy slice;auto moved=rel slice;auto returned=relay_slice(copy);
 if((*copy)~length!=3ul || (*moved)~length!=3ul || (*returned)~length!=3ul)return 1u;
 if((*copy)~as_pointer!=&values[0] || (*moved)~as_pointer!=&values[0] || (*returned)~as_pointer!=&values[0])return 2u;
 if(copy[0]!=7u || moved[1]!=11u || returned[2]!=13u)return 3u;
 return 0u;
}}
template<class T> constexpr const char* type_name() safe {return T~string;}
template<class T> struct Types {using associated=T;};
constexpr bool names_equal(const char* left,const char* right) safe {
 unsafe {return __builtin_strcmp(left,right)==0;}
}
static_assert(names_equal(type_name<unsigned>(),"unsigned int"));
static_assert(names_equal(type_name<const unsigned*>(),"const unsigned int *"));
static_assert(names_equal(unsigned int~string,"unsigned int"));
static_assert(names_equal(Types<unsigned>::associated~string,"unsigned int"));
'''
ENTRY = '''int main() safe {
 auto r=run_relocation();if(r)return 10+r;
 auto c=run_constructors();if(c)return 80+c;
 auto p=run_patterns();if(p)return 30+p;
 auto t=run_tuples();if(t)return 50+t;
 auto s=run_slices();if(s)return 60+s;
 if(run_tuple_borrows())return 70;
 if(run_phantom())return 71;
 if(run_tuple_packs())return 72;
 return 0;
}'''
NEGATIVES = [
 ('unsafe_fn Count bad(Count value){return rel value;}', 'local owning record variable'),
 ('const unsigned^ bad() safe {unsigned local=1u;LocatedView source{^const local};auto target=relocate source;return target.value;}', 'module-safety:'),
 ('struct UnsafeMove {unsigned value;UnsafeMove():value(1u){} unsafe_fn UnsafeMove(UnsafeMove&& rhs):value(rhs.value){}};void bad() safe {UnsafeMove p;auto q=rel p;}', 'unsafe or unclassified'),
 ('struct Both {operator rel(Both)=trivial;relocate(Both rhs)=trivial;};void bad() safe {Both p{};auto q=rel p;}', 'relocation is deleted'),
 ('struct Wrong {relocate(unsigned rhs){}};', 'one by-value parameter'),
 ('struct Pinned {relocate(Pinned rhs)=delete;};void bad() safe {Pinned p{};auto q=relocate p;}', 'relocation is deleted'),
 ('const unsigned^ bad() safe {unsigned local=1u;auto pair=(^const local,^const local,);return first_borrow.(pair);}', 'module-safety:'),
 ('struct Wrong {operator rel(unsigned) {return 1u;}};', 'enclosing class type'),
 ('struct Pin {operator rel(Pin)=delete;};void bad() safe {Pin p;auto q=rel p;}', 'relocation is deleted'),
 ('struct Pin {operator rel(Pin)=delete;};struct Box {Pin p;};void bad() safe {Box p;auto q=rel p;}', 'relocation is deleted'),
 ('struct Private {private:operator rel(Private){return Private{};}};void bad() safe {Private p;auto q=rel p;}', 'private'),
 ('unsigned bad((bool,bool) p) safe {return match(p)->unsigned {[true,true]=>1u;[false,false]=>2u;};}', 'nested payload patterns'),
 ('unsigned bad(Number p) safe {return match(p)->unsigned {.left(1)=>1u;.right(x)=>x;.none=>0u;};}', 'nested payload patterns'),
 ('unsigned bad(Number p) safe {return match(p)->unsigned {.left(x)|.right(y)=>1u;.none=>0u;};}', 'same names'),
 ('choice Mixed {integer(unsigned), flag(bool)};unsigned bad(Mixed p) safe {return match(p)->unsigned {.integer(x)|.flag(x)=>1u;};}', 'same types'),
 ('unsigned bad(Number p) safe {return match(p)->unsigned {.left(x) if(x>0u)=>x;.right(x)=>x;.none=>0u;};}', 'every alternative'),
 ('template<class T> unsigned incomplete(T p) safe {return match(p)->unsigned {.left(x) if(x>0u)=>x;.right(x)=>x;.none=>0u;};}unsigned bad(Number p) safe {return incomplete(p);}', 'every alternative'),
]
PANIC = r'''
#include <exception>
#include <cstdlib>
struct ThrowOperator {operator rel(ThrowOperator) {unsafe {throw 7u;}}};
struct ThrowConstructor {relocate(ThrowConstructor rhs) {unsafe {throw 7u;}}};
struct ThrowMove {
 ThrowMove() {}
 ThrowMove(ThrowMove&& rhs) {unsafe {throw 7u;}}
};
unsafe_fn void terminated() {std::_Exit(77);}
unsafe_fn int main() {
 std::set_terminate(terminated);
 try {TEST_TYPE source;auto target=relocate source;}
 catch (...) {return 99;}
 return 1;
}
'''

with tempfile.TemporaryDirectory(prefix='runtime-semantics-') as directory:
    d = pathlib.Path(directory)
    source, module, pcm, obj, exe = (d/name for name in ('client.cpp','api.cppm','api.pcm','api.o','run'))
    def compile(arguments, okay=True, diagnostic=''):
        result = subprocess.run([str(CLANG)]+FLAGS+arguments, capture_output=True, text=True, timeout=120)
        assert (result.returncode == 0) == okay, result.stderr
        assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr, result.stderr
        assert diagnostic in result.stderr, result.stderr
        return result
    module.write_text('export module runtime_semantics;export {\n'+API+'}\n')
    for opt in ('-O0','-O2'):
        for sanitizer in ([], ['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
            options = [opt]+sanitizer
            compile(options+['--precompile',str(module),'-o',str(pcm)])
            compile(options+['-c',str(pcm),'-o',str(obj)])
            for imported in (False,True):
                source.write_text(('import runtime_semantics;\n' if imported else API)+ENTRY)
                compile(options+(['-fmodule-file=runtime_semantics='+str(pcm)] if imported else [])+
                        [str(source)]+([str(obj)] if imported else [])+['-o',str(exe)])
                run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
                assert run.returncode == 0, f'exit {run.returncode}: {run.stderr}'
    for imported in (False,True):
        for body, diagnostic in NEGATIVES:
            source.write_text(('import runtime_semantics;\n' if imported else API)+body)
            compile((['-fmodule-file=runtime_semantics='+str(pcm)] if imported else [])+
                    ['-fsyntax-only',str(source)], False, diagnostic)
    for opt in ('-O0','-O2'):
        for sanitizer in ([], ['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
            for kind in ('ThrowOperator','ThrowConstructor','ThrowMove'):
                source.write_text(PANIC.replace('TEST_TYPE',kind))
                compile([opt]+sanitizer+[str(source),'-o',str(exe)])
                run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
                assert run.returncode==77,(kind,opt,sanitizer,run.returncode,run.stderr)
                assert 'runtime error:' not in run.stderr and 'ERROR: AddressSanitizer' not in run.stderr,run.stderr
print(f'Runtime semantics: both relocation hooks, default policies and exact drops, composed/guarded/dependent choice patterns, single tuple evaluation, slice pointer/count and instantiated type names; 8 local/PCM executions, 12 noexcept termination executions and {2*len(NEGATIVES)} refusals at O0/O2 plain ASan/UBSan passed')
