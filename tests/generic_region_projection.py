#!/usr/bin/env python3
"""Template identity, rather than field order, determines carried regions."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG', ROOT/'llvm-build/bin/clang'))
API = '''
struct View/(a){const unsigned^/a value;};
template<class A+,class B+> struct Pair{A left;B right;};
template<class A+,class B+> struct Reorder{B first;A second;};
template<class T+> struct Repeat{T first;T second;};
template<class... Ts+> struct Pack{Ts ...items;};
template<class... Ts+> struct RepeatPack{Ts ...first;Ts ...second;};
template<class A+,class B+> struct NestedPack{Pack<B,A> data;};
template<class... Ts> struct PlainPack{Ts ...items;};
using BorrowRow=const unsigned^[2];
template<class T+> struct RowHolder{T rows;};
template<class T> using Identity=T;
template<class A+,class B+> struct Aliased{Identity<B> first;Identity<A> second;};
template<class T> struct Traits{using type=T;};
template<class T> struct MoreTraits{using type=typename Traits<T>::type;};
template<class T> struct Select;
template<class T> struct Select<T*>{using type=T;};
template<class T> struct Outer{template<class U> struct Inner{using left=T;using right=U;};};
template<class T> struct Inherited:Traits<T>{};
template<class T> struct Mapper{template<class U> using first=T;template<class U> using second=U;};
template<unsigned I,class... Ts> struct Nth;
template<class H,class... Ts> struct Nth<0,H,Ts...>{using type=H;};
template<unsigned I,class H,class... Ts> struct Nth<I,H,Ts...>:Nth<I-1,Ts...>{};
template<class... Ts> struct Types{};
template<unsigned I,class T> struct At;
template<unsigned I,class... Ts> struct At<I,Types<Ts...>>{using type=typename Nth<I,Ts...>::type;};
template<class... Ts+> struct PartialPack;
template<class H+,class... Ts+> struct PartialPack<H,Ts...>{
 H first;typename At<0,Types<Ts...>>::type second;
};
template<class A+,class B+> struct AssociatedInherited{
 typename Inherited<B>::type first;typename Inherited<A>::type second;
};
template<class A+,class B+> struct AssociatedAliasTemplate{
 typename Mapper<A>::template second<B> first;
 typename Mapper<A>::template first<B> second;
};
template<class A+,class B+> struct AssociatedMeta{
 typename At<0,Types<B,A>>::type first;typename At<1,Types<B,A>>::type second;
};
template<class A+,class B+> struct Associated{
 typename Traits<B>::type first;typename Traits<A>::type second;
};
template<class A+,class B+> struct AssociatedChain{
 typename MoreTraits<B>::type first;typename MoreTraits<A>::type second;
};
template<class A+,class B+> struct AssociatedPartial{
 typename Select<B*>::type first;typename Select<A*>::type second;
};
template<class A+,class B+> struct AssociatedNested{
 typename Outer<A>::template Inner<B>::right first;
 typename Outer<A>::template Inner<B>::left second;
};
template<class A+,class B+> struct Nested{Pair<B,A> data;A again;};
template<class A+,class B+> struct Deep{Repeat<Pair<B,A>> data;};
template<class A+,class B+,class Tag> struct Partial;
template<class X+,class Y+> struct Partial<Y,X,unsigned>{X first;Y second;};
template<class A+,class B+,class Tag> struct NestedPartial;
template<class X+,class Y+> struct NestedPartial<Repeat<Y>,Repeat<X>,unsigned>{X first;Y second;};
template<class T+> struct Special;
template<> struct Special<View>{View item;};
template<class A+,class B+> struct MutableReorder{B first;A unsafe second;};
using Loan=const unsigned^;
using MutTied=void /(a,b,c)(const MutableReorder<Loan,Loan>/a/b^/c,const unsigned^/a) safe;
using MutFree=void /(a,b,d,c)(const MutableReorder<Loan,Loan>/d/b^/c,const unsigned^/a) safe;
using ReadTied=void /(a,b,c)(const MutableReorder<Loan,Loan>/a/b^/c,const unsigned^/b) safe;
using ReadFree=void /(a,b,d,c)(const MutableReorder<Loan,Loan>/a/d^/c,const unsigned^/b) safe;
template<class From,class To> To* adapt(From* value) safe {return value;}
const unsigned permanent=17u;
'''
# Each tuple names a class parameterization and all paths carrying its first
# and second region. Repeating a field/type must repeat its original mapping.
SHAPES = [
    ('reordered', 'Reorder<View,View>', ['second.value'], ['first.value']),
    ('partial_pack', 'PartialPack<View,View>', ['first.value'], ['second.value']),
    ('aliased', 'Aliased<View,View>', ['second.value'], ['first.value']),
    ('associated_inherited', 'AssociatedInherited<View,View>', ['second.value'], ['first.value']),
    ('associated_alias_template', 'AssociatedAliasTemplate<View,View>', ['second.value'], ['first.value']),
    ('associated_meta', 'AssociatedMeta<View,View>', ['second.value'], ['first.value']),
    ('associated', 'Associated<View,View>', ['second.value'], ['first.value']),
    ('associated_chain', 'AssociatedChain<View,View>', ['second.value'], ['first.value']),
    ('associated_partial', 'AssociatedPartial<View,View>', ['second.value'], ['first.value']),
    ('associated_nested', 'AssociatedNested<View,View>', ['second.value'], ['first.value']),
    ('nested', 'Nested<View,View>', ['data.right.value','again.value'], ['data.left.value']),
    ('deep', 'Deep<View,View>', ['data.first.right.value','data.second.right.value'],
                              ['data.first.left.value','data.second.left.value']),
    ('repeated', 'Repeat<Pair<View,View>>', ['first.left.value','second.left.value'],
                                         ['first.right.value','second.right.value']),
    ('partial', 'Partial<View,View,unsigned>', ['second.value'], ['first.value']),
    ('nested_partial', 'NestedPartial<Repeat<View>,Repeat<View>,unsigned>',
                       ['second.value'], ['first.value']),
]
def initialize(name, a, b):
    av, bv = f'View{{{a}}}', f'View{{{b}}}'
    forward = f'Pair<View,View>{{{av},{bv}}}'
    reverse = f'Pair<View,View>{{{bv},{av}}}'
    if name in ('reordered','aliased','partial','nested_partial','associated',
                'associated_chain','associated_partial','associated_nested',
                'associated_inherited','associated_alias_template','associated_meta'):
        return f'{{{bv},{av}}}'
    if name == 'partial_pack': return f'{{{av},{bv}}}'
    if name == 'nested': return f'{{{reverse},{av}}}'
    if name == 'deep': return f'{{Repeat<Pair<View,View>>{{{reverse},{reverse}}}}}'
    if name == 'repeated': return f'{{{forward},{forward}}}'
    raise AssertionError(name)

for name, shape, first, second in SHAPES:
    for region, paths in (('a', first), ('b', second)):
        for index, path in enumerate(paths):
            API += (f'const unsigned^/{region} pick_{name}_{region}{index}/(a,b)'
                    f'({shape}/a/b input) safe {{return input.{path};}}\n')
    API += (f'{shape}/a/b relay_{name}/(a,b)({shape}/a/b input) safe '
            '{return rel input;}\n')
API += '''
View/a pick_repeat/(a)(Repeat<View>/a input) safe {return input.second;}
View/a pick_special/(a)(Special<View>/a input) safe {return input.item;}
template<class A+,class B+> Reorder<A,B>/a/b generic_relay/(a,b)(Reorder<A,B>/a/b input) safe {return rel input;}
template<class A+,class B+> const unsigned^/a generic_pick/(a,b)(Reorder<A,B>/a/b input) safe {return input.second.value;}
Pack<View,View>/a/b make_pack/(a,b)(const unsigned^/a a,const unsigned^/b b) safe {return Pack<View,View>{View{a},View{b}};}
RepeatPack<unsigned,View,View>/a/b make_repeat_pack/(a,b)(const unsigned^/a a,const unsigned^/b b) safe {return RepeatPack<unsigned,View,View>{1u,View{a},View{b},2u,View{a},View{b}};}
NestedPack<View,View>/a/b make_nested_pack/(a,b)(const unsigned^/a a,const unsigned^/b b) safe {return NestedPack<View,View>{Pack<View,View>{View{b},View{a}}};}
RepeatPack<unsigned,View,View>/a/b relay_pack/(a,b)(RepeatPack<unsigned,View,View>/a/b input) safe {return rel input;}
const unsigned^/a read_row/(a)(RowHolder<BorrowRow>/a input) safe {return input.rows[1];}
const unsigned^/static read_permanent(Repeat<View>/static input) safe {return input.second.value;}
const unsigned^/a read_mixed/(a)(Reorder<View,View>/static/a input) safe {return input.first.value;}
'''
PROGRAM = '''
int main() safe {
 unsigned a=7u,b=11u;
 Reorder<View,View> reordered{View{^const b},View{^const a}};
 PartialPack<View,View> partial_pack{View{^const a},View{^const b}};
 Aliased<View,View> aliased{View{^const b},View{^const a}};
 Associated<View,View> associated{View{^const b},View{^const a}};
 AssociatedInherited<View,View> associated_inherited{View{^const b},View{^const a}};
 AssociatedAliasTemplate<View,View> associated_alias_template{View{^const b},View{^const a}};
 AssociatedMeta<View,View> associated_meta{View{^const b},View{^const a}};
 AssociatedChain<View,View> associated_chain{View{^const b},View{^const a}};
 AssociatedPartial<View,View> associated_partial{View{^const b},View{^const a}};
 AssociatedNested<View,View> associated_nested{View{^const b},View{^const a}};
 Nested<View,View> nested{Pair<View,View>{View{^const b},View{^const a}},View{^const a}};
 Deep<View,View> deep{Repeat<Pair<View,View>>{
     Pair<View,View>{View{^const b},View{^const a}},Pair<View,View>{View{^const b},View{^const a}}}};
 Repeat<Pair<View,View>> repeated{Pair<View,View>{View{^const a},View{^const b}},
                                 Pair<View,View>{View{^const a},View{^const b}}};
 Partial<View,View,unsigned> partial{View{^const b},View{^const a}};
 NestedPartial<Repeat<View>,Repeat<View>,unsigned> nested_partial{View{^const b},View{^const a}};
'''
for name, shape, first, second in SHAPES:
    PROGRAM += f'{{ auto value=relay_{name}(rel {name});\n'
    for region, paths, expected in (('a',first,7),('b',second,11)):
        for index, path in enumerate(paths):
            PROGRAM += f'if(*pick_{name}_{region}{index}(value)!={expected}u)return 1;\n'
    PROGRAM += '}\n'
PROGRAM += '''
 Repeat<View> twice{View{^const a},View{^const a}};
 if(*pick_repeat(twice).value!=7u)return 2;
 Special<View> special{View{^const a}};
 if(*pick_special(special).value!=7u)return 3;
 Reorder<View,View> fresh{View{^const b},View{^const a}};
 auto generic=generic_relay(rel fresh);
 if(*generic_pick(rel generic)!=7u)return 4;
 auto packed=make_pack(^const a,^const b);
 auto twice_packed=relay_pack(make_repeat_pack(^const a,^const b));
 auto nested_packed=make_nested_pack(^const a,^const b);
 Pack<> empty{};PlainPack<unsigned,unsigned> plain{1u,2u};
 RowHolder<BorrowRow> row{{^const a,^const a}};
 if(*read_row(row)!=7u)return 5;
 const unsigned^ saved;
 {Repeat<View> value{View{^const permanent},View{^const permanent}};saved=read_permanent(value);}
 if(*saved!=17u)return 6;
 Reorder<View,View> mixed{View{^const a},View{^const permanent}};
 if(*read_mixed(rel mixed)!=7u)return 7;
 return 0;
}
'''


def main():
    flags = ['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values',
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    count = 0
    with tempfile.TemporaryDirectory(prefix='generic-projection-') as directory:
        d = pathlib.Path(directory)
        source, module, pcm, obj, exe = (d/name for name in ('client.cpp','api.cppm','api.pcm','api.o','run'))
        module.write_text('export module projection;export {\n'+API+'}\n')
        imported = ['-fmodule-file=projection='+str(pcm)]

        def compile(options, okay=True):
            r = subprocess.run([str(CLANG)]+flags+options,capture_output=True,text=True,timeout=120)
            assert (r.returncode == 0) == okay, r.stderr+'\n'+source.read_text()
            assert 'PLEASE submit' not in r.stderr, r.stderr
            if not okay: assert 'error:' in r.stderr, r.stderr

        source.write_text(API)
        compile(['--precompile',str(module),'-o',str(pcm)])

        def check(body, okay):
            nonlocal count
            for use_pcm in (False,True):
                source.write_text(('import projection;\n' if use_pcm else API)+body)
                compile((imported if use_pcm else [])+['-fsyntax-only',str(source)],okay)
                count += 1

        for name, shape, first, second in SHAPES:
            for wanted, paths in (('a', second), ('b', first)):
                for index, path in enumerate(paths):
                    for effect in ('safe','unsafe'):
                        check(f'const unsigned^/{wanted} bad/(a,b)({shape}/a/b input) '
                              f'{effect} {{return input.{path};}}',False)
            # Provenance for indirect calls must retain the same mapping.
            for region, paths in (('a',first),('b',second)):
                for index, path in enumerate(paths):
                    producer=f'pick_{name}_{region}{index}'
                    a = '^const shorter' if region == 'a' else '^const longer'
                    b = '^const shorter' if region == 'b' else '^const longer'
                    check('unsigned bad() safe {unsigned longer=1u;const unsigned^ saved;'
                          '{unsigned shorter=2u;'
                          f'{shape} input{initialize(name,a,b)};'
                          f'auto f=&{producer};saved=f(input);'+'}return *saved;}',False)
                    check('unsigned good() safe {unsigned a=7u,b=11u;'
                          f'{shape} input{initialize(name,"^const a","^const b")};'
                          f'auto f=&{producer};return *f(input);'+'}',True)
            for effect in ('safe','unsafe'):
                check(f'{shape}/a/b wrong/(a,b)({shape}/a/b input) {effect} '
                      '{return '+shape+initialize(name,'input.'+second[0],'input.'+first[0])+';}',False)
        check('template<class A+,class B+> const unsigned^/a wrong/(a,b)('
              'Reorder<A,B>/a/b input) safe {return input.first.value;}'
              'void test() safe {unsigned a=1u,b=2u;Reorder<View,View> value{View{^const b},View{^const a}};'
              'auto loan=wrong(rel value);}',False)
        for src,dst,okay in [('MutTied','MutFree',False),('MutFree','MutTied',True),
                             ('ReadTied','ReadFree',True),('ReadFree','ReadTied',True)]:
            for expression in ('f',f'reinterpret_cast<{dst}*>(f)',f'adapt<{src},{dst}>(f)'):
                check(f'void check({src}* f) unsafe {{{dst}* g={expression};}}',okay)
        for shape, initializer in (
                ('Pack<View,View>','{View{b},View{a}}'),
                ('RepeatPack<unsigned,View,View>','{1u,View{a},View{b},2u,View{b},View{a}}'),
                ('NestedPack<View,View>','{Pack<View,View>{View{a},View{b}}}')):
            for effect in ('safe','unsafe'):
                check(f'{shape}/a/b bad/(a,b)(const unsigned^/a a,const unsigned^/b b)'
                      f' {effect} '+'{return '+shape+initializer+';}',False)
        check('void bad() safe {PlainPack<Loan>/a value;}',False)
        check('const unsigned^/a bad/(a,b)(const unsigned^/a a,const unsigned^/b b) safe {'
              'RowHolder<BorrowRow> row{{a,b}};return read_row(row);}',False)
        # Static payloads are permanent; their parameter carriers are not.
        check('const unsigned^/static good(Repeat<View>/static input) safe {'
              'return input.second.value;}',True)
        check('const View^/static bad(Repeat<View>/static input) safe {'
              'return ^const input.second;}',False)
        check('const View^/static bad(Repeat<View>/static input) unsafe {'
              'return ^const input.second;}',False)
        for binding,path in (('static/a','first'),('a/static','second')):
            for effect in ('safe','unsafe'):
                check(f'const unsigned^/static bad/(a)(Reorder<View,View>/{binding} input)'
                      f' {effect} '+'{return input.'+path+'.value;}',False)
        for opt in ('-O0','-O2'):
            for san in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
                options=[opt]+san
                compile(options+['--precompile',str(module),'-o',str(pcm)])
                compile(options+['-c',str(pcm),'-o',str(obj)])
                for use_pcm in (False,True):
                    source.write_text(('import projection;\n' if use_pcm else API)+PROGRAM)
                    compile(options+(imported if use_pcm else [])+[str(source)]+
                            ([str(obj)] if use_pcm else [])+['-o',str(exe)])
                    r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
                    assert r.returncode==0,r.stderr+str(r.returncode)
    print(f'Generic region projections: {count} local/PCM checks; repeated, reordered, '
          'nested, alias, partial specialization, static and per-region variance; '
          '8 O0/O2 plain ASan/UBSan executions passed')

if __name__ == '__main__':
    main()
