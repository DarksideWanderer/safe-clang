#!/usr/bin/env python3
"""Safe generic APIs must validate every user constructor/drop/callback."""
import pathlib
import subprocess
import sys
import tempfile

clang, plugin, root = sys.argv[1:]
root = pathlib.Path(root)
with tempfile.TemporaryDirectory(prefix='safety-boundaries-') as directory:
    tmp = pathlib.Path(directory)
    checked = [clang, '-std=c++20', '-I'+str(root/'include'),
               '-fprebuilt-module-path='+str(tmp), '-Xclang', '-load', '-Xclang', plugin,
               '-Xclang', '-add-plugin', '-Xclang', 'module-safety', '-Xclang',
               '-plugin-arg-module-safety', '-Xclang', 'safe']

    def compile(args, ok=True, needle=''):
        result = subprocess.run(args, text=True, capture_output=True)
        assert (result.returncode == 0) == ok, result.stderr
        assert needle in result.stderr, result.stderr
        assert 'PLEASE submit' not in result.stderr and 'frontend command failed' not in result.stderr

    modules = [('safety', 'safety'), ('safety_borrows', 'borrows'),
               ('safety_mutable_borrows', 'mutable_borrows'),
               ('safety_ownership', 'ownership'), ('safety_threads', 'threads')]
    for module, file in modules:
        compile(checked+['--precompile', str(root/'runtime'/(file+'.cppm')),
                         '-o', str(tmp/(module+'.pcm'))])
    source = tmp/'boundary.cppm'
    prefix = '''module;
#include "module_safety.h"
export module boundary;
import safety; import safety_borrows; import safety_mutable_borrows;
import safety_ownership; import safety_threads;
'''
    bad_copy = '''struct Bad {const unsigned& value;
      SAFETY_UNSAFE_FN Bad(const Bad& other):value(other.value){} };
    '''
    bad_drop = '''struct Bad {const unsigned& value;
      SAFETY_UNSAFE_FN ~Bad() noexcept {} };
    '''
    cases = [
        bad_copy+'void f(const Bad& value){std2::borrowed_vector<Bad,Bad> v(value);v.push_back(value);}',
        bad_copy+'void f(const Bad& value){std2::borrowed_vector<Bad,Bad> v(value);v.reserve(8u);}',
        bad_copy+'void f(const std2::borrowed_vector<Bad,Bad>& v){v.get(0u);}',
        bad_drop+'void f(const Bad& value){std2::borrowed_vector<Bad,Bad> v(value);}',
        bad_drop+'void f(Bad& value){std2::mutable_borrowed_vector<Bad,Bad> v(value);}',
        bad_drop+'void f(std2::pin_box<Bad> value){}',
        bad_drop+'void f(std2::pin_region<Bad,unsigned> value){}',
        '''struct Bad {SAFETY_UNSAFE_FN unsigned operator()(unsigned x)const{return x;}};
        unsigned f(){std2::mutex<unsigned> m(1u);return m.update<Bad{}>();}''',
    ]
    for body in cases:
        source.write_text(prefix+body)
        compile(checked+['--precompile', str(source), '-o', str(tmp/'boundary.pcm')],
                False, 'unsafe or unclassified')

    # This used to compile and produce an ASan heap-use-after-free: a field
    # assignment cleared the moved state of a holder whose loan was transferred.
    for declaration, restore in [
        ('struct View{unsigned tag;const unsigned& value;};', 'source.tag=1u;'),
        ('struct Tag{unsigned value=0u;};struct View{Tag tag;const unsigned& value;};', 'source.tag.value=1u;'),
        ('struct Tag{unsigned value=0u;};struct View{Tag tag;const unsigned& value;};', 'source.tag=Tag{};'),
        ('struct View{unsigned tag;const unsigned& value;SAFETY_STORES_BORROW(v) View(unsigned t,const unsigned& v):tag(t),value(v){} View(View&&)=default;void operator=(const View& other){tag=other.tag;}};',
         'unsigned other=17u;View replacement{{},other};source=replacement;'),
    ]:
        source.write_text(prefix+declaration+'''
          unsigned f(){auto box=std2::pin_box<unsigned>::make(42u);
            View source{{},box.get()};View target(static_cast<View&&>(source));
            unsigned copy=target.value;'''+restore+'''
            box.reset(17u);return source.value;}
        ''')
        compile(checked+['-fsyntax-only', str(source)], False, 'moved')

    source.write_text(prefix+'''struct Good{unsigned operator()(unsigned x)const{return x;}};
      struct CustomAllocation {
        unsigned value=7u;
        SAFETY_UNSAFE_FN static void* operator new(std2::size_type){std2::panic();}
        SAFETY_UNSAFE_FN static void operator delete(void*)noexcept{std2::panic();}
      };
      struct RegionalAllocation {
        const unsigned& value;
        SAFETY_STORES_BORROW(owner) RegionalAllocation(unsigned& owner):value(owner){}
        SAFETY_UNSAFE_FN static void* operator new(std2::size_type){std2::panic();}
        SAFETY_UNSAFE_FN static void operator delete(void*)noexcept{std2::panic();}
      };
      export unsigned run(){
        std2::mutex<unsigned> m(1u);if(m.update<Good{}>()!=1u)return 1u;
        auto box=std2::pin_box<CustomAllocation>::make();
        if(box.get().value!=7u)return 2u;
        box.reset();
        auto taken=box.take();if(taken.value!=7u)return 3u;
        unsigned owner=9u;
        std2::pin_region<RegionalAllocation,unsigned> region(owner);
        if(region.get().value!=9u)return 4u;
        // A whole owning value can still be restored after a move.
        std2::vector<unsigned> first;first.push_back(3u);
        std2::vector<unsigned> second(std2::move(first));
        first=std2::vector<unsigned>{};first.push_back(5u);
        if(first.get(0u)!=5u || second.get(0u)!=3u)return 5u;
        std2::vector<unsigned> third(std2::move(first));
        first.operator=(std2::vector<unsigned>{});first.push_back(7u);
        if(first.get(0u)!=7u || third.get(0u)!=5u)return 6u;
        return 0u;
      }
      consteval int immediate(){return 2;}
      constexpr int materialized=2;
      int arithmetic(){return immediate()+materialized+1;}
    ''')
    compile(checked+['--precompile', str(source), '-o', str(tmp/'boundary.pcm')])
    runtime_flags=['-std=c++20','-O2','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                   '-fprebuilt-module-path='+str(tmp)]
    objects=[]
    for name in ['safety','safety_borrows','safety_mutable_borrows','safety_ownership','safety_threads','boundary']:
        obj=tmp/(name+'.o');objects.append(str(obj))
        compile([clang]+runtime_flags+['-c',str(tmp/(name+'.pcm')),'-o',str(obj)])
    main=tmp/'main.cpp';main.write_text('import boundary;int main(){return int(run());}')
    binary=tmp/'run'
    compile([clang]+runtime_flags+[str(main)]+objects+['-o',str(binary)])
    subprocess.run([str(binary)],check=True)

print('12 cross-PCM unsafe copy/drop/callback and moved-holder refusals; whole-owner restoration, global allocation, safe callbacks and materialized constants passed under ASan/UBSan')
