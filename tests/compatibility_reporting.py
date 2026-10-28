"""Compatibility reports must distinguish execution evidence from syntax checks."""
import copy
import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('circle_compatibility', ROOT/'tools/circle_compatibility.py')
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class CompatibilityReporting(unittest.TestCase):
    def test_negative_attribution_does_not_credit_crashes_or_unrelated_errors(self):
        source=ROOT/'example.cpp'
        oracle={'upstream_enabled':True,'oracle_status':'reviewed_native_diagnostic',
                'first_error_line':9,'diagnostic_regex':'borrow outlives'}
        diagnostic=f'{source}:9:3: error: borrow outlives its owner\n'
        good=REPORT.classify_negative(source,1,diagnostic,oracle)
        self.assertTrue(good['expected_rule_verified'])
        for code,text in [(0,diagnostic),(-11,diagnostic),
                          (1,diagnostic+'PLEASE submit a bug report'),
                          (1,f'{source}:2:1: error: expected expression\n'+diagnostic),
                          (1,diagnostic.replace(':9:',':8:')),
                          (1,diagnostic.replace('borrow outlives','unknown type'))]:
            self.assertFalse(REPORT.classify_negative(source,code,text,oracle)['expected_rule_verified'])
        self.assertFalse(REPORT.classify_negative(source,1,diagnostic)['expected_rule_verified'])
        disabled=dict(oracle,upstream_enabled=False)
        self.assertFalse(REPORT.classify_negative(source,1,diagnostic,disabled)['expected_rule_verified'])

    def test_constraint_rejection_needs_its_reason_and_oracles_bind_sources(self):
        source=ROOT/'example.cpp'
        oracle={'oracle_status':'reviewed_native_diagnostic','first_error_line':9,
                'diagnostic_regex':'no matching constructor','required_note_regex':'evaluated to false'}
        diagnostic=f'{source}:9:3: error: no matching constructor\n'
        self.assertFalse(REPORT.classify_negative(source,1,diagnostic,oracle)['expected_rule_verified'])
        self.assertTrue(REPORT.classify_negative(source,1,diagnostic+'note: constraint evaluated to false',oracle)['expected_rule_verified'])
        cases=REPORT.load_negative_oracles(ROOT/'downloads/safe-cpp-reference')
        self.assertEqual(len(cases),34)
        self.assertFalse(cases['libsafecxx/test/compile-fail/mutex3.cxx']['upstream_enabled'])
        with patch.object(pathlib.Path,'read_bytes',return_value=b'changed upstream input'):
            with self.assertRaises(SystemExit):
                REPORT.load_negative_oracles(ROOT/'downloads/safe-cpp-reference')

    def test_runtime_flags_and_observed_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory)/'test.cxx'
            source.write_text('int main() {return 0;}\n')
            with (patch.object(REPORT.subprocess, 'run') as run,
                  patch.object(pathlib.Path, 'read_bytes', return_value=b'fake executable')):
                run.side_effect = [
                    subprocess.CompletedProcess([], 0, '', ''),
                    subprocess.CompletedProcess([], 0, b'ok', b''),
                    subprocess.CompletedProcess([], 0, '', ''),
                    subprocess.CompletedProcess([], 1, b'', b'assertion failed'),
                ]
                results = REPORT.runtime_probe(source, ['clang', '-fsyntax-only'], [], directory,
                    extra_flags=['-DLIBSAFECXX_PANIC_THROWS'])
            self.assertEqual([r['status'] for r in results],
                             ['executed_successfully', 'runtime_failed'])
            for call in (run.call_args_list[0], run.call_args_list[2]):
                self.assertIn('-DLIBSAFECXX_PANIC_THROWS', call.args[0])
                self.assertNotIn('-fsyntax-only', call.args[0])
            self.assertFalse(REPORT.positive_runtime_succeeded([{'returncode': 0, 'runtime': results}]))

    def test_summary_requires_both_optimizations_and_zero_exits(self):
        good = {'returncode': 0, 'runtime': [
            {'optimization': opt, 'status': 'executed_successfully',
             'execution': {'returncode': 0}} for opt in ('-O0', '-O2')]}
        self.assertTrue(REPORT.positive_runtime_succeeded([good]))
        self.assertFalse(REPORT.positive_runtime_succeeded([]))
        self.assertFalse(REPORT.positive_runtime_succeeded([{'returncode': 0}]))
        for field, value in (('optimization', '-O0'), ('status', 'build_failed'),
                             ('execution', {'returncode': -6})):
            bad = copy.deepcopy(good)
            bad['runtime'][1][field] = value
            self.assertFalse(REPORT.positive_runtime_succeeded([bad]), field)
        bad = copy.deepcopy(good)
        bad['returncode'] = 1
        self.assertFalse(REPORT.positive_runtime_succeeded([bad]))


if __name__ == '__main__':
    unittest.main()
