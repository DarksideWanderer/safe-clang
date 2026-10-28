"""Independent composition probes; preserve diagnostics instead of assuming success."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLANG = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'llvm-build/bin/clang'
FLAGS = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety',
         '-fcircle-borrow-values', '-Wno-everything',
         '-I' + str(ROOT / 'downloads/safe-cpp-reference/libsafecxx/single-header'),
         '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
PREFIX = '#feature on safety\n#include <std2.h>\n'
STORE = '''struct Store {std2::vector<std2::string_view> values;
 Store() safe {} ~Store() safe {}};
'''
CASES = [
    ('retained_field_mutation', False, STORE + '''
int main() safe {char text[]={'o','k'};Store store;
 store.values^.push_back(std2::string_view(text));text[0]='n';
 std2::println(*store.values[0]);}
''', ''),
    ('retained_mutable_acquisition', False, '''
int main() safe {char text[]={'o','k'};
 std2::vector<std2::string_view> values;
 values^.push_back(std2::string_view(text));char^ alias=^text[0];
 std2::println(*values[0]);*alias='n';return 0;}
''', ''),
    ('retained_shared_mutation', False, '''
int main() safe {char text[]={'o','k'};
 std2::vector<std2::string_view> values;
 values^.push_back(std2::string_view(text));text[0]='n';
 std2::println(*values[0]);}
''', ''),
    ('retained_exclusive_alias', False, '''
int main() safe {unsigned value=7u;
 std2::vector<unsigned^> first,second;
 first^.push_back(^value);second^.push_back(^value);
 **first[0]=1u;**second[0]=2u;return 0;}
''', ''),
    ('retained_shared_destroyed', True, '''
int main() safe {char text[]={'o','k'};
 {std2::vector<std2::string_view> values;
 values^.push_back(std2::string_view(text));std2::println(*values[0]);
 }
 text[0]='n';return text[0]=='n'?0:1;}
''', 'ok\n'),
    ('field_container_live', True, STORE + '''
int main() safe {const char text[]={'o','k'};Store store;
 store.values^.push_back(std2::string_view(text));
 std2::println(*store.values[0]);return 0;}
''', 'ok\n'),
    ('field_container_expired', False, STORE + '''
int main() safe {Store store;
 {const char text[]={'n','o'};store.values^.push_back(std2::string_view(text));}
 std2::println(*store.values[0]);}
''', ''),
    ('moved_field_container_live', True, STORE + '''
int main() safe {const char text[]={'o','k'};Store store;
 store.values^.push_back(std2::string_view(text));auto moved=rel store;
 std2::string_view copy="ok";
 {auto last=rel moved;copy := std2::string_view(*last.values[0]);}
 std2::println(copy);return 0;}
''', 'ok\n'),
    ('moved_field_container_expired', False, STORE + '''
int main() safe {Store store;
 {const char text[]={'n','o'};store.values^.push_back(std2::string_view(text));}
 auto moved=rel store;std2::println(*moved.values[0]);}
''', ''),
    ('uncontracted_field_escape', False, STORE + '''
Store escape() safe {Store store;const char text[]={'n','o'};
 store.values^.push_back(std2::string_view(text));return rel store;}
int main() safe {auto store=escape();std2::println(*store.values[0]);}
''', ''),
    ('template_loop_live', True, '''
template<class V, class T> void append(V^ v,T item) safe {v.push_back(item);}
int main() safe {const char text[]={'o','k'};
 std2::vector<std2::string_view> v;
 for(int i=0;i<3;++i) append(^v,std2::string_view(text));
 std2::println(*v[2]); return 0;}
''', 'ok\n'),
    ('template_loop_expired', False, '''
template<class V, class T> void append(V^ v,T item) safe {v.push_back(item);}
int main() safe {std2::vector<std2::string_view> v;
 for(int i=0;i<3;++i) {const char text[]={'o','k'};append(^v,std2::string_view(text));}
 std2::println(*v[2]);}
''', ''),
    ('element_copy_expired', False, '''
int main() safe {std2::string_view result="ok";
 {const char text[]={'o','k'};std2::vector<std2::string_view> v;
 v^.push_back(std2::string_view(text));result := std2::string_view(*v[0]);}
 std2::println(result);}
''', ''),
    ('element_copy_live', True, '''
int main() safe {const char text[]={'o','k'};std2::string_view result="ok";
 {std2::vector<std2::string_view> v;
 v^.push_back(std2::string_view(text));result := std2::string_view(*v[0]);}
 std2::println(result);return 0;}
''', 'ok\n'),
    ('nested_container_live', True, '''
int main() safe {const char text[]={'o','k'};
 std2::vector<std2::vector<std2::string_view>> outer;
 {std2::vector<std2::string_view> inner;
 inner^.push_back(std2::string_view(text));outer^.push_back(rel inner);}
 std2::println(*(*outer[0])[0]);return 0;}
''', 'ok\n'),
    ('nested_scalar_live', True, '''
int main() safe {std2::vector<std2::vector<unsigned>> outer;
 std2::vector<unsigned> inner;inner^.push_back(42u);
 outer^.push_back(rel inner);return *(*outer[0])[0]==42u?0:1;}
''', ''),
    ('element_slot_borrow_expired', False, '''
int main() safe {const char text[]={'o','k'};
 std2::string_view fallback(text);const std2::string_view^ result=^const fallback;
 {std2::vector<std2::string_view> v;
 v^.push_back(std2::string_view(text));result=v[0];}
 std2::println(*result);}
''', ''),
    ('two_container_move_live', True, '''
int main() safe {const char text[]={'o','k'};
 std2::vector<std2::string_view> first;
 first^.push_back(std2::string_view(text));
 auto second=rel first;auto third=rel second;
 std2::println(*third[0]);return 0;}
''', 'ok\n'),
    ('two_container_move_expired', False, '''
int main() safe {std2::vector<std2::string_view> first;
 {const char text[]={'o','k'};first^.push_back(std2::string_view(text));}
 auto second=rel first;auto third=rel second;std2::println(*third[0]);}
''', ''),
    ('nested_container_expired', False, '''
int main() safe {std2::vector<std2::vector<std2::string_view>> outer;
 {const char text[]={'o','k'};std2::vector<std2::string_view> inner;
 inner^.push_back(std2::string_view(text));outer^.push_back(rel inner);}
 std2::println(*(*outer[0])[0]);}
''', ''),
    ('branch_live', True, '''
int main(int argc,char**) safe {const char left[]={'o','k'},right[]={'o','k'};
 std2::vector<std2::string_view> v;
 if(argc) v^.push_back(std2::string_view(left));
 else v^.push_back(std2::string_view(right));
 std2::println(*v[0]);return 0;}
''', 'ok\n'),
    ('branch_one_expired', False, '''
int main(int argc,char**) safe {const char live[]={'o','k'};
 std2::vector<std2::string_view> v;
 {const char dead[]={'n','o'};
 if(argc) v^.push_back(std2::string_view(dead));
 else v^.push_back(std2::string_view(live));}
 std2::println(*v[0]);}
''', ''),
    ('unsafe_wrapper_live', True, '''
const unsigned^/a foreign/(a)(const unsigned^/a input) unsafe {return input;}
const unsigned^/a wrapper/(a)(const unsigned^/a input) safe {
 unsafe {return foreign(input);}}
int main() safe {unsigned value=42u;auto loan=wrapper(^const value);
 return *loan==42u?0:1;}
''', ''),
    ('unsafe_wrong_return_source', False, '''
const unsigned^/a foreign/(a)(const unsigned^/a input) unsafe {
 unsigned local=42u;return ^const local;}
int main() safe {unsigned value=1u;unsafe {auto loan=foreign(^const value);}
 return *loan==42u?0:1;}
''', ''),
    ('lambda_no_unsafe_inheritance', False, '''
unsigned legacy(unsigned value) unsafe {return value;}
int main() safe {unsafe {auto fn=[](unsigned x) safe {return legacy(x);};
 return fn(42u)==42u?0:1;}}
''', ''),
    ('exception_cleanup_once', True, '''
unsigned drops=0u;
struct Guard {Guard() safe {} ~Guard() safe {unsafe {++drops;}}};
int main() safe {try {Guard a;{Guard b;throw 7;}}catch(int value) {
 if(value!=7)return 1;}
 unsafe {return drops==2u?0:2;}}
''', ''),
]

results = []
with tempfile.TemporaryDirectory(prefix='safety-composition-review-') as directory:
    tmp = pathlib.Path(directory)
    for opt in ('-O0', '-O2'):
        for name, valid, body, output in CASES:
            source = tmp / (name + '.cpp')
            source.write_text(PREFIX + body)
            executable = tmp / name
            command = [str(CLANG)] + FLAGS + [opt, '-fsanitize=address,undefined',
                       '-fno-sanitize-recover=all', str(source), '-o', str(executable)]
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=120)
            entry = dict(name=name, optimization=opt, expected_valid=valid,
                         compiled=compiled.returncode == 0, diagnostics=compiled.stderr)
            if compiled.returncode == 0:
                ran = subprocess.run([str(executable)], capture_output=True, text=True,
                                     timeout=15, env=dict(os.environ,
                                     ASAN_OPTIONS='detect_stack_use_after_return=1'))
                entry.update(returncode=ran.returncode, stdout=ran.stdout, stderr=ran.stderr)
                entry['passed'] = valid and ran.returncode == 0 and ran.stdout == output
            else:
                diagnostic = ('returned reference does not borrow from the declared lifetime source'
                              if name == 'unsafe_wrong_return_source' else
                              'mutation conflicts with a live borrow'
                              if name in ('retained_shared_mutation',
                                          'retained_field_mutation') else
                              'access conflicts with a live exclusive borrow'
                              if name in ('retained_exclusive_alias',
                                          'retained_mutable_acquisition') else
                              'requires an explicit SAFETY_UNSAFE block'
                              if name == 'lambda_no_unsafe_inheritance' else
                              'returned borrow has unknown lifetime provenance'
                              if name == 'uncontracted_field_escape' else
                              'borrow outlives its owner')
                entry['passed'] = not valid and diagnostic in compiled.stderr
            results.append(entry)
            print(opt, name, 'PASS' if entry['passed'] else 'REVIEW', flush=True)

report = ROOT / 'build/safety-composition-review.json'
report.write_text(json.dumps(results, indent=2))
print(f'{sum(r["passed"] for r in results)}/{len(results)} expected outcomes; {report}')
raise SystemExit(0 if all(r['passed'] for r in results) else 1)
