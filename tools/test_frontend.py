#!/usr/bin/env python3
"""Run compiler, module-graph, and sanitizer regressions on native Clang.

The regressions are independent processes with their own temporary
workspaces, so they run concurrently; --jobs bounds how many at once.
"""
import argparse
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

root = pathlib.Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('clang', nargs='?', default=str(root/'llvm-build/bin/clang'))
parser.add_argument('--jobs', type=int, default=max(1, min(os.cpu_count() or 1, 8)),
                    help='regressions to run at once (default: up to eight)')
arguments = parser.parse_args()
clang = pathlib.Path(arguments.clang).resolve()
env = dict(os.environ, MODULE_SAFETY_CLANG=str(clang))
tasks = []
failures = []


def run_regression(command, **kwargs):
    # Register the script instead of running it: the independent temporary
    # workspaces make the whole gate parallel. A failed script must fail the
    # gate, but must not hide the results of the remaining scripts.
    kwargs.pop('check', None)
    environ = kwargs.pop('env', env)
    if kwargs:
        raise TypeError('unexpected regression arguments: '+', '.join(kwargs))
    name = pathlib.Path(command[1]).name
    if environ.get('MODULE_SAFETY_THREAD_SANITIZER'):
        name += ' (tsan)'
    tasks.append((name, lambda: subprocess.run(command, env=environ, capture_output=True, text=True)))


def add_inline(name, check):
    # An in-process check reports (returncode, stdout, stderr) and raises to
    # fail, exactly like a script whose process exits nonzero.
    def run():
        return 0, check(), ''
    tasks.append((name, run))


run_regression([sys.executable, str(root/'tests/compatibility_reporting.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/forged_native_metadata.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/unsafe_declarations.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/lifetime_kind_constraints.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/static_results.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/static_fields.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/static_class_values.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/unsafe_result_contracts.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_function_addresses.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/partial_moves.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/adoption_contracts.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/indirect_borrow_storage.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/indirect_storage_replacement.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/indirect_storage_destruction.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/indirect_storage_construction.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/safety_composition_review.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/container_factory_regions.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/class_value_results.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/class_lifetime_elision.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/generative_lifetimes.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/generative_pointer_origins.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/trivial_copy_borrow.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/sequence_storage_regions.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/slice_rebuild_regions.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/drop_only.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/borrow_slot_arrays.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/aggregate_reborrow_parents.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_effect_paths.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/class_region_results.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/class_lifetime_variance.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/region_relation_entries.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/borrow_capabilities.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/higher_ranked_relations.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/higher_ranked_relation_algebra.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/higher_ranked_pack_substitution.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/array_region_variance.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/generic_region_projection.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/outer_region_captures.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/class_parameter_variance.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/captured_callable_values.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/initializer_traversal.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/multi_region_class_values.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/nested_class_values.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/borrowed_class_results.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_borrows.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_relocation.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_replacement.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_parameters.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_nested_places.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_self.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/choice_match.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/niche_zero.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/match_ranges.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/choice_borrow_patterns.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/dependent_match.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_panic_checks.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/unsafe_legacy_mode.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/command_modes.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/interface_declarations.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/impl_declarations.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/impl_calls.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/impl_selection.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/impl_overloads.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/documentation.py'), str(clang)], env=env, check=True)
adapter = root/'tools/native_clang.py'
for script in ('run.py', 'build_graph.py', 'runtime.py', 'threads.py', 'objects.py', 'borrowed_containers.py', 'conversions.py', 'ownership_concurrency.py', 'mutable_borrows.py', 'lifecycle_system.py', 'unions.py', 'coroutines.py','regions.py', 'runtime_boundaries.py', 'exceptions.py', 'bitints.py', 'borrow_domain.py', 'consuming_receivers.py', 'global_borrows.py'):
    run_regression([sys.executable, str(root/'tests'/script), str(adapter), 'native', str(root)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/threads.py'), str(adapter), 'native', str(root)], env=dict(env, MODULE_SAFETY_THREAD_SANITIZER='thread'), check=True)
run_regression([sys.executable, str(root/'tests/ownership_concurrency.py'), str(adapter), 'native', str(root)], env=dict(env, MODULE_SAFETY_THREAD_SANITIZER='thread'), check=True)
run_regression([sys.executable, str(root/'tests/function_types.py'), str(clang), str(root)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/native_lifetimes.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/borrow_values.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/phantom_data.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/operator_borrow_projection.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/mutable_context.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/template_lifetime_binders.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/safe_effect_atom.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/std2_concepts.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/std2_consumers.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/official_box_test.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/official_string_view_test.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/official_match_test.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/official_positive_tests.py'), str(clang), '--jobs', '4'], env=env, check=True)
run_regression([sys.executable, str(root/'tests/trivial_destructor.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/choice_patterns.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/runtime_semantics.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/array_slice_conversions.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/feature_catalog.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/legacy_value_abi.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/relocation_operators.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/tuple_call.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/tuple_dependent.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/tuple_lifetimes.py')], env=env, check=True)
run_regression([sys.executable, str(root/'tests/nested_borrows.py'), str(clang)], env=env, check=True)
run_regression([sys.executable, str(root/'tests/conditional_contracts.py'), str(clang)], env=env, check=True)
def native_module_modes():
    with tempfile.TemporaryDirectory(prefix='native-module-safety-') as directory:
        tmp = pathlib.Path(directory)
        source = tmp/'native.cppm'
        source.write_text('export module native; unsigned unsafe_fn=1u; unsigned f(int* p) { unsafe { return *p; } }')
        policy = tmp/'policy.json'
        policy.write_text('{"version":1,"modules":{"native":"safe"}}')
        base = [str(clang), '-std=c++20', '-fsyntax-only', str(source)]
        checked = base+['-fmodule-safe', '-fmodule-safety-policy='+str(policy)]
        result = subprocess.run(checked, text=True, capture_output=True)
        if result.returncode: raise AssertionError(result.stderr)
        # The directive alone selects the mode: a project policy is optional and
        # only cross-checks it, so checking is already on without one.
        for directive in (['-fmodule-safe'], ['-fcircle-safety']):
            result = subprocess.run(base+directive, text=True, capture_output=True)
            if result.returncode: raise AssertionError(result.stderr)
        unchecked = tmp/'unchecked.cppm'
        unchecked.write_text('export module native; unsigned f(int* p) { return *p; }')
        for directive in (['-fmodule-safe'], ['-fcircle-safety']):
            result = subprocess.run([str(clang), '-std=c++20', '-fsyntax-only', str(unchecked)]+directive, text=True, capture_output=True)
            if result.returncode == 0 or 'module-safety:' not in result.stderr:
                raise AssertionError(result.stderr)
        result = subprocess.run([str(clang), '-std=c++20', '-fsyntax-only', str(unchecked), '-fmodule-unsafe'], text=True, capture_output=True)
        if result.returncode: raise AssertionError(result.stderr)
        for extra in (['-fmodule-safe', '-fmodule-unsafe', '-fmodule-safety-policy='+str(policy)],):
            result = subprocess.run(base+extra, text=True, capture_output=True)
            if result.returncode == 0 or 'module-safety:' not in result.stderr:
                raise AssertionError(result.stderr)
        preprocessed = subprocess.run([str(clang), '-std=c++20', '-E', str(source), '-fmodule-safe'], text=True, capture_output=True, check=True)
        if 'unsafe { return *p; }' not in preprocessed.stdout:
            raise AssertionError('native safety syntax must not be replaced by preprocessor macros')
        source.write_text('export module native; export void spin() { unsigned n=0u; for (;;) { ++n; } }')
        pcm = tmp/'native.pcm'
        subprocess.run([str(clang), '-std=c++20', '-fmodule-safe', '-fmodule-safety-policy='+str(policy), '--precompile', str(source), '-o', str(pcm)], check=True)
        ir = tmp/'native.ll'
        subprocess.run([str(clang), '-std=c++20', '-O2', '-S', '-emit-llvm', str(pcm), '-o', str(ir)], check=True)
        text = ir.read_text()
        spin = re.search(r'define[^\n]*@_ZW6native4spinv\(\)[^\n]*#(\d+) \{([\s\S]*?)\n\}', text)
        if not spin: raise AssertionError('missing exported spin definition')
        attributes = re.search(r'^attributes #'+spin.group(1)+r' = ([^\n]+)', text, re.MULTILINE)
        if not attributes or 'mustprogress' in attributes.group(1) or 'unreachable' in spin.group(2) or 'br label' not in spin.group(2):
            raise AssertionError('safe PCM codegen must preserve a pure infinite loop')
    return 'Native syntax, directive-only mode selection, conflicting modes and optimized PCM loop semantics passed\n'


add_inline('native-module-modes', native_module_modes)
printed = threading.Lock()


def report(result):
    name, returncode, stdout, stderr = result
    with printed:
        for stream, text in ((sys.stdout, stdout), (sys.stderr, stderr)):
            if text:
                print(text, end='' if text.endswith('\n') else '\n', file=stream, flush=True)
        if returncode:
            failures.append((name, returncode))
            print(f'Frontend regression failed: {name} (exit {returncode})', flush=True)


def execute(task):
    name, run = task
    try:
        outcome = run()
    except BaseException:
        return name, 1, '', traceback.format_exc()
    if isinstance(outcome, subprocess.CompletedProcess):
        return name, outcome.returncode, outcome.stdout or '', outcome.stderr or ''
    return (name,)+outcome


with ThreadPoolExecutor(max_workers=arguments.jobs) as pool:
    for result in pool.map(execute, tasks):
        report(result)

if failures:
    print('Failed frontend regressions: '+', '.join(f'{name} ({code})' for name, code in failures), file=sys.stderr)
    raise SystemExit(1)
print(f'{len(tasks)} frontend regressions passed with {arguments.jobs} jobs')
